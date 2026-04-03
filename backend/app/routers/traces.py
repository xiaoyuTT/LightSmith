"""
traces.py — Trace 查询 API 路由

提供查询接口：
  - GET /api/traces - 分页列表
  - GET /api/traces/{trace_id} - 完整树形 JSON
  - GET /api/runs/{run_id} - 单个 Run 查询
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from datetime import datetime

from app.db.base import get_db
from app.db.repository import RunRepository
from app.models.run import Run as RunORM
from app.schemas.run import RunSchema
from app.schemas.trace import TraceListItem, TracesListResponse, TraceTreeNode
from app.config import get_settings

router = APIRouter(prefix="/traces", tags=["Traces"])


# ---------------------------------------------------------------------------
# 辅助函数：ORM → Pydantic 转换
# ---------------------------------------------------------------------------


def _orm_to_trace_list_item(run: RunORM) -> TraceListItem:
    """将 ORM Run 转换为 TraceListItem（列表摘要）"""
    # 计算耗时
    duration_ms = None
    if run.start_time and run.end_time:
        try:
            start = datetime.fromisoformat(run.start_time.replace('Z', '+00:00'))
            end = datetime.fromisoformat(run.end_time.replace('Z', '+00:00'))
            duration_ms = (end - start).total_seconds() * 1000
        except (ValueError, AttributeError):
            pass

    # 计算状态
    if run.error:
        status_str = "error"
    elif run.end_time:
        status_str = "success"
    else:
        status_str = "running"

    return TraceListItem(
        id=run.id,
        trace_id=run.trace_id,
        name=run.name,
        run_type=run.run_type,
        status=status_str,
        error=run.error,
        start_time=run.start_time,
        end_time=run.end_time,
        duration_ms=duration_ms,
        tags=run.tags,
    )


def _orm_to_trace_tree_node(run: RunORM) -> TraceTreeNode:
    """将 ORM Run 转换为 TraceTreeNode（不包含 children）"""
    return TraceTreeNode(
        id=run.id,
        trace_id=run.trace_id,
        parent_run_id=run.parent_run_id,
        name=run.name,
        run_type=run.run_type,
        inputs=run.inputs,
        outputs=run.outputs,
        error=run.error,
        start_time=run.start_time,
        end_time=run.end_time,
        metadata=run.run_metadata,  # ORM run_metadata → API metadata
        tags=run.tags,
        exec_order=run.exec_order,
        children=[],  # 初始为空，后续填充
    )


def _build_trace_tree(runs: list[RunORM]) -> Optional[TraceTreeNode]:
    """构建树形结构

    将扁平的 Run 列表转换为递归的树形 JSON。

    Args:
        runs: 已按 exec_order 排序的 Run 列表

    Returns:
        根节点（包含完整的递归子树），若列表为空则返回 None

    算法：
      1. 将所有 Run 转换为 TraceTreeNode
      2. 建立 id → node 映射
      3. 遍历所有节点，将子节点添加到父节点的 children 列表
      4. 找到根节点（parent_run_id 为 None）并返回
    """
    if not runs:
        return None

    # 1. 转换为 TraceTreeNode 并建立映射
    node_map: dict[str, TraceTreeNode] = {}
    for run in runs:
        node = _orm_to_trace_tree_node(run)
        node_map[run.id] = node

    # 2. 建立父子关系
    root_node = None
    for run in runs:
        node = node_map[run.id]
        if run.parent_run_id is None:
            # 根节点
            root_node = node
        else:
            # 子节点：添加到父节点的 children 列表
            parent = node_map.get(run.parent_run_id)
            if parent:
                parent.children.append(node)

    # 3. 对每个节点的 children 按 exec_order 排序
    for node in node_map.values():
        node.children.sort(key=lambda n: n.exec_order)

    return root_node


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------


@router.get("", response_model=TracesListResponse)
def list_traces(
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(50, ge=1, le=1000, description="每页大小"),
    run_type: Optional[str] = Query(None, description="过滤 run_type"),
    tags: Optional[str] = Query(None, description="过滤 tags（逗号分隔，OR 逻辑）"),
    has_error: Optional[bool] = Query(None, description="过滤是否有错误"),
    start_after: Optional[str] = Query(None, description="过滤 start_time >= 此时间（ISO 8601）"),
    start_before: Optional[str] = Query(None, description="过滤 start_time <= 此时间（ISO 8601）"),
    db: Session = Depends(get_db),
):
    """分页查询 Traces 列表

    返回根 Run（parent_run_id 为 NULL）的分页列表，仅包含摘要信息。
    前端可点击查看详情时再调用 GET /api/traces/{trace_id} 获取完整树。

    Args:
        page: 页码（从 1 开始）
        page_size: 每页大小（1-1000）
        run_type: 过滤 run_type（可选）
        tags: 过滤 tags（逗号分隔，OR 逻辑，可选）
        has_error: 过滤是否有错误（True/False/None 不过滤）
        start_after: 过滤 start_time >= 此时间（ISO 8601）
        start_before: 过滤 start_time <= 此时间（ISO 8601）

    Returns:
        TracesListResponse: 分页结果
    """
    settings = get_settings()
    repo = RunRepository(db)

    # 解析 tags（逗号分隔 → 列表）
    tags_list = None
    if tags:
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]

    # 调用 Repository 查询
    result = repo.list_traces(
        page=page,
        page_size=page_size,
        run_type=run_type,
        tags=tags_list,
        has_error=has_error,
        start_after=start_after,
        start_before=start_before,
        max_page_size=settings.max_page_size,
    )

    # 转换为响应 schema
    items = [_orm_to_trace_list_item(run) for run in result["items"]]

    return TracesListResponse(
        items=items,
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )


@router.get("/{trace_id}", response_model=TraceTreeNode)
def get_trace_tree(
    trace_id: str,
    db: Session = Depends(get_db),
):
    """获取完整 Trace 树形 JSON

    返回递归嵌套的树形结构，每个节点包含 children 字段。
    这是前端 P2.2 TypeScript 类型的对齐基准。

    Args:
        trace_id: Trace ID

    Returns:
        TraceTreeNode: 根节点（包含完整子树）

    Raises:
        HTTPException 404: Trace 不存在
    """
    repo = RunRepository(db)
    runs = repo.get_trace(trace_id)

    if not runs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace not found: {trace_id}",
        )

    # 构建树形结构
    tree = _build_trace_tree(runs)

    if not tree:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to build trace tree",
        )

    return tree


@router.get("/{trace_id}/runs/{run_id}", response_model=RunSchema)
def get_run(
    trace_id: str,
    run_id: str,
    db: Session = Depends(get_db),
):
    """获取单个 Run 的完整数据

    Args:
        trace_id: Trace ID（用于验证 Run 是否属于该 Trace）
        run_id: Run ID

    Returns:
        RunSchema: Run 完整数据

    Raises:
        HTTPException 404: Run 不存在或不属于该 Trace
    """
    repo = RunRepository(db)
    run = repo.get_run_by_id(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )

    # 验证 Run 属于该 Trace
    if run.trace_id != trace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} does not belong to trace {trace_id}",
        )

    # 转换为响应 schema
    return RunSchema(
        id=run.id,
        trace_id=run.trace_id,
        parent_run_id=run.parent_run_id,
        name=run.name,
        run_type=run.run_type,
        inputs=run.inputs,
        outputs=run.outputs,
        error=run.error,
        start_time=run.start_time,
        end_time=run.end_time,
        metadata=run.run_metadata,  # ORM run_metadata → API metadata
        tags=run.tags,
        exec_order=run.exec_order,
    )
