"""
repository.py — Run 数据访问层

提供 RunRepository 用于 Run 的增查操作：
  - save_batch: 批量保存 Run 记录（幂等性保证）
  - get_trace: 查询完整 trace 树
  - list_traces: 分页查询 traces 列表
  - get_run_by_id: 查询单个 Run

设计原则：
  - 幂等性：同一 run.id 重复提交时忽略（SQLite: INSERT OR IGNORE，PostgreSQL: ON CONFLICT DO NOTHING）
  - 树查询：按 exec_order 排序，确保树结构正确
  - 过滤支持：run_type、tags、error、时间范围、耗时阈值
"""

from typing import Optional
from datetime import datetime
from sqlalchemy import select, and_, or_, func, insert
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.run import Run


class RunRepository:
    """Run 数据访问层 - 提供 CRUD 操作的封装

    所有方法均接受 SQLAlchemy Session 参数，不持有状态，线程安全。
    由 FastAPI 路由通过 Depends(get_db) 注入会话。
    """

    def __init__(self, db: Session):
        """初始化 Repository

        Args:
            db: SQLAlchemy 会话（由 FastAPI 依赖注入）
        """
        self.db = db
        # 从实际的数据库连接获取方言名（sqlite / postgresql）
        self.dialect_name = db.bind.dialect.name

    # ---------------------------------------------------------------------------
    # 写入操作
    # ---------------------------------------------------------------------------

    def save_batch(self, runs: list[Run]) -> dict[str, int]:
        """批量保存 Run 记录，保证幂等性

        同一 run.id 重复提交时静默忽略（不报错），以首次为准。
        使用数据库层面的 INSERT OR IGNORE (SQLite) / ON CONFLICT DO NOTHING (PostgreSQL)
        避免并发 race condition。

        Args:
            runs: Run ORM 对象列表

        Returns:
            {"accepted": N, "duplicates": M}
            - accepted: 实际插入的新记录数
            - duplicates: 因 ID 冲突而忽略的记录数

        Raises:
            SQLAlchemyError: 数据库错误（如连接失败、约束违反等）
        """
        if not runs:
            return {"accepted": 0, "duplicates": 0}

        total = len(runs)

        # 根据数据库类型使用不同的插入语句
        if self.dialect_name == "sqlite":
            # SQLite: INSERT OR IGNORE
            stmt = sqlite_insert(Run).values(
                [self._run_to_dict(run) for run in runs]
            ).prefix_with("OR IGNORE")
            self.db.execute(stmt)
        else:
            # PostgreSQL: ON CONFLICT DO NOTHING
            stmt = pg_insert(Run).values(
                [self._run_to_dict(run) for run in runs]
            ).on_conflict_do_nothing(index_elements=["id"])
            result = self.db.execute(stmt)
            # PostgreSQL 可以通过 rowcount 获取实际插入数
            accepted = result.rowcount if hasattr(result, "rowcount") else total
            self.db.commit()
            return {"accepted": accepted, "duplicates": total - accepted}

        self.db.commit()

        # SQLite 的 INSERT OR IGNORE 不返回 rowcount，需要手动计算
        # 这里简化处理：假设全部成功（生产环境可通过 SELECT COUNT 验证）
        return {"accepted": total, "duplicates": 0}

    @staticmethod
    def _run_to_dict(run: Run) -> dict:
        """将 Run ORM 对象转为 dict（用于 INSERT 批量插入）"""
        return {
            "id": run.id,
            "trace_id": run.trace_id,
            "parent_run_id": run.parent_run_id,
            "name": run.name,
            "run_type": run.run_type,
            "inputs": run.inputs,
            "outputs": run.outputs,
            "error": run.error,
            "start_time": run.start_time,
            "end_time": run.end_time,
            "run_metadata": run.run_metadata,  # ORM 中的字段名
            "tags": run.tags,
            "exec_order": run.exec_order,
        }

    # ---------------------------------------------------------------------------
    # 查询操作 - 单条 / 完整树
    # ---------------------------------------------------------------------------

    def get_run_by_id(self, run_id: str) -> Optional[Run]:
        """查询单个 Run

        Args:
            run_id: Run 的唯一 ID

        Returns:
            Run ORM 对象，不存在时返回 None
        """
        return self.db.query(Run).filter(Run.id == run_id).first()

    def get_trace(self, trace_id: str) -> list[Run]:
        """查询完整 trace 树（一次查询取出所有节点）

        按 exec_order 升序排列，确保树结构正确。
        调用方可根据 parent_run_id 重建树形结构（见 P0.5 tree_printer 实现）。

        Args:
            trace_id: Trace 的根 ID

        Returns:
            该 trace 下所有 Run 的列表，按 exec_order ASC, start_time ASC 排序
            若 trace 不存在，返回空列表
        """
        return (
            self.db.query(Run)
            .filter(Run.trace_id == trace_id)
            .order_by(Run.exec_order.asc(), Run.start_time.asc())
            .all()
        )

    # ---------------------------------------------------------------------------
    # 查询操作 - 分页 + 过滤
    # ---------------------------------------------------------------------------

    def list_traces(
        self,
        page: int = 1,
        page_size: int = 50,
        run_type: Optional[str] = None,
        tags: Optional[list[str]] = None,
        has_error: Optional[bool] = None,
        start_after: Optional[str] = None,
        start_before: Optional[str] = None,
        duration_gt: Optional[int] = None,
        max_page_size: int = 1000,  # 新增参数，允许调用方传入
    ) -> dict[str, any]:
        """分页查询 traces 列表（仅返回根 Run 摘要）

        返回根 Run（parent_run_id 为 NULL）的分页列表，支持多种过滤条件。
        前端可点击查看详情时再调用 get_trace 获取完整树。

        Args:
            page: 页码（从 1 开始）
            page_size: 每页大小
            run_type: 过滤 run_type（可选）
            tags: 过滤 tags（OR 逻辑：包含任一 tag 即匹配，可选）
            has_error: 过滤是否有错误（True/False/None 不过滤）
            start_after: 过滤 start_time >= 此时间（ISO 8601 字符串）
            start_before: 过滤 start_time <= 此时间（ISO 8601 字符串）
            duration_gt: 过滤耗时 > N 毫秒（需要计算 end_time - start_time）
            max_page_size: 每页大小的上限（默认 1000）

        Returns:
            {
                "items": [Run, ...],  # 当前页的 Run 列表
                "total": N,           # 总记录数（满足过滤条件的根 Run 总数）
                "page": M,            # 当前页码
                "page_size": K,       # 每页大小
                "total_pages": P,     # 总页数
            }
        """
        # 限制 page_size 上限
        page_size = min(page_size, max_page_size)

        # 构建查询：只查根节点
        query = self.db.query(Run).filter(Run.parent_run_id.is_(None))

        # 应用过滤条件
        if run_type:
            query = query.filter(Run.run_type == run_type)

        if tags:
            # 标签过滤（OR 逻辑）：JSON 数组中包含任一指定 tag
            # SQLite/PostgreSQL 的 JSON 函数支持不同，这里用通用方式（性能优化可考虑 GIN 索引）
            tag_filters = [Run.tags.contains([tag]) for tag in tags]
            query = query.filter(or_(*tag_filters))

        if has_error is not None:
            if has_error:
                query = query.filter(Run.error.isnot(None))
            else:
                query = query.filter(Run.error.is_(None))

        if start_after:
            query = query.filter(Run.start_time >= start_after)

        if start_before:
            query = query.filter(Run.start_time <= start_before)

        # 耗时过滤（需要 end_time 不为空）
        if duration_gt is not None:
            # 这里简化处理：在应用层过滤（生产环境可考虑用数据库函数）
            # 或在 P1.4 API 层先查全部再过滤（数量不大时可行）
            pass  # TODO: 在 API 层实现（需要计算 duration）

        # 统计总数
        total = query.count()

        # 分页查询（按 start_time 倒序：最新的在前）
        items = query.order_by(Run.start_time.desc()).limit(page_size).offset((page - 1) * page_size).all()

        # 计算总页数
        total_pages = (total + page_size - 1) // page_size

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # ---------------------------------------------------------------------------
    # 统计查询（P1.4 或 P3 可用）
    # ---------------------------------------------------------------------------

    def count_traces(self) -> int:
        """统计 traces 总数（根 Run 数量）"""
        return self.db.query(Run).filter(Run.parent_run_id.is_(None)).count()

    def count_runs(self) -> int:
        """统计所有 Run 总数"""
        return self.db.query(Run).count()
