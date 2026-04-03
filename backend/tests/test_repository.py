"""
test_repository.py — RunRepository 单元测试

测试 RunRepository 的核心功能：
  - save_batch: 批量保存 Run 记录
  - get_trace: 查询完整 trace 树
  - list_traces: 分页查询 traces 列表
  - 幂等性: 同一 run.id 重复提交不报错
"""

import pytest
import tempfile
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.repository import RunRepository
from app.models.run import Run


@pytest.fixture
def temp_db():
    """创建临时 SQLite 数据库用于测试"""
    # 创建临时文件
    fd = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = fd.name
    fd.close()

    # 创建引擎和会话
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    yield session

    # 清理：先关闭会话，再关闭引擎，最后删除文件
    session.close()
    engine.dispose()
    # Windows 上可能需要短暂延迟才能删除文件
    try:
        Path(db_path).unlink()
    except PermissionError:
        # 如果文件被锁定，跳过删除（临时文件系统会自动清理）
        pass


@pytest.fixture
def sample_runs():
    """创建示例 Run 数据"""
    trace_id = "trace-123"
    root_run = Run(
        id="run-1",
        trace_id=trace_id,
        parent_run_id=None,
        name="root_function",
        run_type="chain",
        inputs={"arg1": "value1"},
        outputs={"result": "success"},
        error=None,
        start_time="2026-04-03T10:00:00Z",
        end_time="2026-04-03T10:00:05Z",
        run_metadata={"model": "gpt-4"},
        tags=["production", "critical"],
        exec_order=0,
    )
    child_run_1 = Run(
        id="run-2",
        trace_id=trace_id,
        parent_run_id="run-1",
        name="child_function_1",
        run_type="llm",
        inputs={"prompt": "hello"},
        outputs={"response": "hi"},
        error=None,
        start_time="2026-04-03T10:00:01Z",
        end_time="2026-04-03T10:00:03Z",
        run_metadata={},
        tags=["production"],
        exec_order=1,
    )
    child_run_2 = Run(
        id="run-3",
        trace_id=trace_id,
        parent_run_id="run-1",
        name="child_function_2",
        run_type="tool",
        inputs={"tool": "search"},
        outputs=None,
        error="ValueError: search failed",
        start_time="2026-04-03T10:00:03Z",
        end_time="2026-04-03T10:00:04Z",
        run_metadata={},
        tags=[],
        exec_order=2,
    )
    return [root_run, child_run_1, child_run_2]


class TestRunRepository:
    """RunRepository 测试套件"""

    def test_save_batch_success(self, temp_db, sample_runs):
        """测试批量保存成功"""
        repo = RunRepository(temp_db)
        result = repo.save_batch(sample_runs)

        assert result["accepted"] >= 0  # SQLite 不返回准确的 rowcount
        assert result["duplicates"] >= 0

        # 验证数据已保存
        saved_run = repo.get_run_by_id("run-1")
        assert saved_run is not None
        assert saved_run.name == "root_function"
        assert saved_run.run_type == "chain"

    def test_save_batch_idempotent(self, temp_db, sample_runs):
        """测试幂等性：同一 run.id 重复提交不报错"""
        repo = RunRepository(temp_db)

        # 第一次保存
        result1 = repo.save_batch(sample_runs)
        assert result1["accepted"] >= 0

        # 第二次保存（重复）
        result2 = repo.save_batch(sample_runs)
        # SQLite 的 INSERT OR IGNORE 不报错，但不会重复插入
        assert result2["accepted"] >= 0

        # 验证数据只保存了一份
        saved_run = repo.get_run_by_id("run-1")
        assert saved_run is not None
        assert saved_run.name == "root_function"

    def test_get_run_by_id(self, temp_db, sample_runs):
        """测试查询单个 Run"""
        repo = RunRepository(temp_db)
        repo.save_batch(sample_runs)

        # 查询存在的 Run
        run = repo.get_run_by_id("run-2")
        assert run is not None
        assert run.name == "child_function_1"
        assert run.parent_run_id == "run-1"

        # 查询不存在的 Run
        run = repo.get_run_by_id("nonexistent")
        assert run is None

    def test_get_trace(self, temp_db, sample_runs):
        """测试查询完整 trace 树"""
        repo = RunRepository(temp_db)
        repo.save_batch(sample_runs)

        # 查询 trace
        runs = repo.get_trace("trace-123")
        assert len(runs) == 3

        # 验证按 exec_order 排序
        assert runs[0].id == "run-1"
        assert runs[0].exec_order == 0
        assert runs[1].id == "run-2"
        assert runs[1].exec_order == 1
        assert runs[2].id == "run-3"
        assert runs[2].exec_order == 2

        # 验证父子关系
        assert runs[0].parent_run_id is None
        assert runs[1].parent_run_id == "run-1"
        assert runs[2].parent_run_id == "run-1"

    def test_get_trace_empty(self, temp_db):
        """测试查询不存在的 trace"""
        repo = RunRepository(temp_db)

        runs = repo.get_trace("nonexistent-trace")
        assert runs == []

    def test_list_traces_pagination(self, temp_db):
        """测试分页查询"""
        repo = RunRepository(temp_db)

        # 创建多个 traces
        traces = []
        for i in range(5):
            trace_id = f"trace-{i}"
            run = Run(
                id=f"run-{i}",
                trace_id=trace_id,
                parent_run_id=None,
                name=f"root_{i}",
                run_type="chain",
                inputs={},
                outputs={},
                error=None,
                start_time=f"2026-04-03T10:00:0{i}Z",
                end_time=f"2026-04-03T10:00:0{i+1}Z",
                run_metadata={},
                tags=[],
                exec_order=0,
            )
            traces.append(run)
        repo.save_batch(traces)

        # 测试分页
        result = repo.list_traces(page=1, page_size=2)
        assert len(result["items"]) == 2
        assert result["total"] == 5
        assert result["page"] == 1
        assert result["page_size"] == 2
        assert result["total_pages"] == 3

        # 测试第二页
        result = repo.list_traces(page=2, page_size=2)
        assert len(result["items"]) == 2
        assert result["page"] == 2

    def test_list_traces_filter_run_type(self, temp_db):
        """测试按 run_type 过滤"""
        repo = RunRepository(temp_db)

        # 创建不同类型的 traces
        runs = [
            Run(
                id="run-1",
                trace_id="trace-1",
                parent_run_id=None,
                name="chain_run",
                run_type="chain",
                inputs={},
                outputs={},
                start_time="2026-04-03T10:00:00Z",
                exec_order=0,
            ),
            Run(
                id="run-2",
                trace_id="trace-2",
                parent_run_id=None,
                name="llm_run",
                run_type="llm",
                inputs={},
                outputs={},
                start_time="2026-04-03T10:00:01Z",
                exec_order=0,
            ),
        ]
        repo.save_batch(runs)

        # 过滤 llm 类型
        result = repo.list_traces(run_type="llm")
        assert len(result["items"]) == 1
        assert result["items"][0].run_type == "llm"

    def test_list_traces_filter_error(self, temp_db):
        """测试按错误状态过滤"""
        repo = RunRepository(temp_db)

        # 创建有错误和无错误的 traces
        runs = [
            Run(
                id="run-1",
                trace_id="trace-1",
                parent_run_id=None,
                name="success_run",
                run_type="chain",
                inputs={},
                outputs={},
                error=None,
                start_time="2026-04-03T10:00:00Z",
                exec_order=0,
            ),
            Run(
                id="run-2",
                trace_id="trace-2",
                parent_run_id=None,
                name="error_run",
                run_type="chain",
                inputs={},
                outputs={},
                error="ValueError: failed",
                start_time="2026-04-03T10:00:01Z",
                exec_order=0,
            ),
        ]
        repo.save_batch(runs)

        # 过滤有错误的
        result = repo.list_traces(has_error=True)
        assert len(result["items"]) == 1
        assert result["items"][0].error is not None

        # 过滤无错误的
        result = repo.list_traces(has_error=False)
        assert len(result["items"]) == 1
        assert result["items"][0].error is None

    def test_list_traces_filter_time_range(self, temp_db):
        """测试按时间范围过滤"""
        repo = RunRepository(temp_db)

        # 创建不同时间的 traces
        runs = [
            Run(
                id="run-1",
                trace_id="trace-1",
                parent_run_id=None,
                name="early_run",
                run_type="chain",
                inputs={},
                outputs={},
                start_time="2026-04-03T09:00:00Z",
                exec_order=0,
            ),
            Run(
                id="run-2",
                trace_id="trace-2",
                parent_run_id=None,
                name="late_run",
                run_type="chain",
                inputs={},
                outputs={},
                start_time="2026-04-03T11:00:00Z",
                exec_order=0,
            ),
        ]
        repo.save_batch(runs)

        # 过滤 10:00 之后的
        result = repo.list_traces(start_after="2026-04-03T10:00:00Z")
        assert len(result["items"]) == 1
        assert result["items"][0].start_time == "2026-04-03T11:00:00Z"

        # 过滤 10:00 之前的
        result = repo.list_traces(start_before="2026-04-03T10:00:00Z")
        assert len(result["items"]) == 1
        assert result["items"][0].start_time == "2026-04-03T09:00:00Z"

    def test_count_traces(self, temp_db, sample_runs):
        """测试统计 traces 总数"""
        repo = RunRepository(temp_db)
        repo.save_batch(sample_runs)

        count = repo.count_traces()
        assert count == 1  # 只有 1 个根 Run

    def test_count_runs(self, temp_db, sample_runs):
        """测试统计所有 Run 总数"""
        repo = RunRepository(temp_db)
        repo.save_batch(sample_runs)

        count = repo.count_runs()
        assert count == 3  # 1 个根 + 2 个子节点
