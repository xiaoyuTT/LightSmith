"""
test_tree_printer.py — CLI 树打印工具的单元测试

测试范围：
  - 树构建逻辑（build_tree）
  - 节点格式化（format_node_line, format_duration）
  - CLI 入口（main 函数，通过 subprocess 调用）
  - 边界情况（空 trace、错误节点、深层嵌套）
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from lightsmith.models import Run, RunType
from lightsmith.storage.sqlite import RunWriter
from cli.tree_printer import (
    TreeNode,
    build_tree,
    format_node_line,
    format_duration,
    get_last_trace_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_writer():
    """为每个测试创建临时数据库中的 RunWriter。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    writer = RunWriter(db_path=db_path)
    yield writer
    writer.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def simple_trace_runs():
    """创建一个简单的 3 层嵌套 trace。"""
    trace_id = "trace-simple"

    root = Run(
        id="run-root",
        trace_id=trace_id,
        parent_run_id=None,
        name="main",
        run_type=RunType.CHAIN,
        exec_order=0,
        start_time="2026-04-01T10:00:00.000000+00:00",
        end_time="2026-04-01T10:00:00.100000+00:00",
    )

    child1 = Run(
        id="run-child1",
        trace_id=trace_id,
        parent_run_id="run-root",
        name="fetch_data",
        run_type=RunType.TOOL,
        exec_order=0,
        start_time="2026-04-01T10:00:00.010000+00:00",
        end_time="2026-04-01T10:00:00.030000+00:00",
    )

    child2 = Run(
        id="run-child2",
        trace_id=trace_id,
        parent_run_id="run-root",
        name="process_result",
        run_type=RunType.LLM,
        exec_order=1,
        start_time="2026-04-01T10:00:00.040000+00:00",
        end_time="2026-04-01T10:00:00.090000+00:00",
    )

    grandchild = Run(
        id="run-grandchild",
        trace_id=trace_id,
        parent_run_id="run-child2",
        name="validate",
        run_type=RunType.TOOL,
        exec_order=0,
        start_time="2026-04-01T10:00:00.050000+00:00",
        end_time="2026-04-01T10:00:00.060000+00:00",
    )

    return [root, child1, child2, grandchild]


@pytest.fixture
def error_trace_runs():
    """创建包含错误节点的 trace。"""
    trace_id = "trace-error"

    root = Run(
        id="run-root-err",
        trace_id=trace_id,
        parent_run_id=None,
        name="failing_task",
        run_type=RunType.AGENT,
        exec_order=0,
        start_time="2026-04-01T10:00:00.000000+00:00",
        end_time="2026-04-01T10:00:00.100000+00:00",
        error="ValueError: Something went wrong\nTraceback...",
    )

    return [root]


# ---------------------------------------------------------------------------
# 测试：树构建
# ---------------------------------------------------------------------------

class TestBuildTree:
    """测试 build_tree 函数。"""

    def test_empty_list_returns_none(self):
        """空列表返回 None。"""
        assert build_tree([]) is None

    def test_single_root_node(self, simple_trace_runs):
        """单根节点构建成功。"""
        root_run = simple_trace_runs[0]
        root_node = build_tree([root_run])

        assert root_node is not None
        assert root_node.run.id == "run-root"
        assert len(root_node.children) == 0

    def test_parent_child_relationship(self, simple_trace_runs):
        """父子关系正确建立。"""
        root_node = build_tree(simple_trace_runs)

        assert root_node is not None
        assert root_node.run.name == "main"
        assert len(root_node.children) == 2

        # 子节点按 exec_order 排序
        child1 = root_node.children[0]
        child2 = root_node.children[1]

        assert child1.run.name == "fetch_data"
        assert child2.run.name == "process_result"
        assert len(child1.children) == 0
        assert len(child2.children) == 1

        # 孙节点
        grandchild = child2.children[0]
        assert grandchild.run.name == "validate"

    def test_three_level_nesting(self, simple_trace_runs):
        """验证 3 层嵌套深度。"""
        root_node = build_tree(simple_trace_runs)

        # 根节点
        assert root_node.run.parent_run_id is None

        # 第 2 层
        child2 = root_node.children[1]
        assert child2.run.parent_run_id == "run-root"

        # 第 3 层
        grandchild = child2.children[0]
        assert grandchild.run.parent_run_id == "run-child2"


# ---------------------------------------------------------------------------
# 测试：节点格式化
# ---------------------------------------------------------------------------

class TestFormatting:
    """测试节点格式化函数。"""

    def test_format_duration_with_end_time(self):
        """有结束时间时格式化耗时。"""
        run = Run(
            name="test",
            start_time="2026-04-01T10:00:00.000000+00:00",
            end_time="2026-04-01T10:00:00.123456+00:00",
        )
        result = format_duration(run)
        assert "123.5ms" in result

    def test_format_duration_without_end_time(self):
        """无结束时间时显示 ...。"""
        run = Run(
            name="test",
            start_time="2026-04-01T10:00:00.000000+00:00",
            end_time=None,
        )
        result = format_duration(run)
        assert "..." in result

    def test_format_node_line_normal(self):
        """正常节点格式化。"""
        run = Run(
            name="my_function",
            run_type=RunType.TOOL,
            start_time="2026-04-01T10:00:00.000000+00:00",
            end_time="2026-04-01T10:00:00.050000+00:00",
        )
        result = format_node_line(run)

        assert "🔧" in result  # TOOL 图标
        assert "my_function" in result
        assert "50.0ms" in result
        assert "ERROR" not in result

    def test_format_node_line_with_error(self):
        """错误节点格式化（包含红色 ANSI 码和 [ERROR] 标签）。"""
        run = Run(
            name="failing_func",
            run_type=RunType.LLM,
            start_time="2026-04-01T10:00:00.000000+00:00",
            end_time="2026-04-01T10:00:00.100000+00:00",
            error="ValueError: test error",
        )
        result = format_node_line(run)

        assert "🤖" in result  # LLM 图标
        assert "failing_func" in result
        assert "ERROR" in result
        assert "\033[91m" in result  # 红色 ANSI

    def test_all_run_type_icons(self):
        """验证所有 RunType 都有对应图标。"""
        for run_type in RunType:
            run = Run(
                name="test",
                run_type=run_type,
                start_time="2026-04-01T10:00:00.000000+00:00",
                end_time="2026-04-01T10:00:00.100000+00:00",
            )
            result = format_node_line(run)
            # 结果应包含某个 emoji 图标
            assert any(icon in result for icon in ["🔗", "🤖", "🔧", "🧠", "⚙️"])


# ---------------------------------------------------------------------------
# 测试：数据库集成
# ---------------------------------------------------------------------------

class TestDatabaseIntegration:
    """测试与 RunWriter 的集成。"""

    def test_get_last_trace_id_empty_db(self, tmp_writer):
        """空数据库返回 None。"""
        trace_id = get_last_trace_id(tmp_writer)
        assert trace_id is None

    def test_get_last_trace_id_single_trace(self, tmp_writer, simple_trace_runs):
        """单个 trace 返回正确的 trace_id。"""
        for run in simple_trace_runs:
            tmp_writer.save(run)

        trace_id = get_last_trace_id(tmp_writer)
        assert trace_id == "trace-simple"

    def test_get_last_trace_id_multiple_traces(self, tmp_writer):
        """多个 trace 返回最近的一个（按 start_time DESC）。"""
        trace1 = Run(
            id="run1",
            trace_id="trace-old",
            parent_run_id=None,
            name="old",
            start_time="2026-04-01T09:00:00.000000+00:00",
            end_time="2026-04-01T09:00:01.000000+00:00",
        )
        trace2 = Run(
            id="run2",
            trace_id="trace-new",
            parent_run_id=None,
            name="new",
            start_time="2026-04-01T10:00:00.000000+00:00",
            end_time="2026-04-01T10:00:01.000000+00:00",
        )

        tmp_writer.save(trace1)
        tmp_writer.save(trace2)

        trace_id = get_last_trace_id(tmp_writer)
        assert trace_id == "trace-new"

    def test_build_tree_from_database(self, tmp_writer, simple_trace_runs):
        """从数据库读取后构建树。"""
        for run in simple_trace_runs:
            tmp_writer.save(run)

        runs = tmp_writer.get_trace("trace-simple")
        root = build_tree(runs)

        assert root is not None
        assert root.run.name == "main"
        assert len(root.children) == 2


# ---------------------------------------------------------------------------
# 测试：CLI 入口（通过 subprocess）
# ---------------------------------------------------------------------------

class TestCLI:
    """测试 CLI 入口（main 函数）。"""

    def test_cli_last_flag(self, tmp_writer, simple_trace_runs, monkeypatch):
        """--last 参数正确工作。"""
        # 写入测试数据
        for run in simple_trace_runs:
            tmp_writer.save(run)

        # 设置环境变量指向临时数据库
        monkeypatch.setenv("LIGHTSMITH_DB_PATH", tmp_writer._db_path)

        # 调用 CLI
        result = subprocess.run(
            [sys.executable, "-m", "cli.tree_printer", "--last"],
            cwd=Path(__file__).parent.parent,  # sdk/
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = result.stdout

        # 验证输出包含节点名称
        assert "main" in output
        assert "fetch_data" in output
        assert "process_result" in output
        assert "validate" in output

        # 验证包含图标（emoji 在 Windows 下可能被替换为 ?）
        assert "🔗" in output or "?" in output  # emoji 或回退字符

    def test_cli_trace_id_flag(self, tmp_writer, simple_trace_runs, monkeypatch):
        """--trace-id 参数正确工作。"""
        for run in simple_trace_runs:
            tmp_writer.save(run)

        monkeypatch.setenv("LIGHTSMITH_DB_PATH", tmp_writer._db_path)

        result = subprocess.run(
            [sys.executable, "-m", "cli.tree_printer", "--trace-id", "trace-simple"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "main" in result.stdout

    def test_cli_nonexistent_trace(self, tmp_writer, monkeypatch):
        """不存在的 trace_id 返回错误。"""
        monkeypatch.setenv("LIGHTSMITH_DB_PATH", tmp_writer._db_path)

        result = subprocess.run(
            [sys.executable, "-m", "cli.tree_printer", "--trace-id", "nonexistent"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "不存在" in result.stderr or "not" in result.stderr.lower()

    def test_cli_empty_database(self, tmp_writer, monkeypatch):
        """空数据库 --last 返回错误。"""
        monkeypatch.setenv("LIGHTSMITH_DB_PATH", tmp_writer._db_path)

        result = subprocess.run(
            [sys.executable, "-m", "cli.tree_printer", "--last"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "没有" in result.stderr or "no" in result.stderr.lower()


# ---------------------------------------------------------------------------
# 测试：边界情况
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """测试边界情况和错误处理。"""

    def test_error_node_in_tree(self, tmp_writer, error_trace_runs):
        """包含错误节点的 trace 能正确打印。"""
        for run in error_trace_runs:
            tmp_writer.save(run)

        runs = tmp_writer.get_trace("trace-error")
        root = build_tree(runs)

        assert root is not None
        assert root.run.has_error

        # 格式化应包含 ERROR 标签
        line = format_node_line(root.run)
        assert "ERROR" in line

    def test_very_deep_nesting(self, tmp_writer):
        """测试深层嵌套（10 层）。"""
        trace_id = "trace-deep"
        runs = []

        for i in range(10):
            run = Run(
                id=f"run-{i}",
                trace_id=trace_id,
                parent_run_id=None if i == 0 else f"run-{i-1}",
                name=f"level_{i}",
                run_type=RunType.CHAIN,
                exec_order=0,
                start_time=f"2026-04-01T10:00:0{i}.000000+00:00",
                end_time=f"2026-04-01T10:00:0{i}.100000+00:00",
            )
            runs.append(run)
            tmp_writer.save(run)

        retrieved_runs = tmp_writer.get_trace(trace_id)
        root = build_tree(retrieved_runs)

        assert root is not None

        # 验证深度
        node = root
        depth = 0
        while node.children:
            depth += 1
            node = node.children[0]

        assert depth == 9  # 10 个节点，9 层父子关系

    def test_multiple_siblings(self, tmp_writer):
        """测试多个兄弟节点（5 个）。"""
        trace_id = "trace-siblings"

        root = Run(
            id="root",
            trace_id=trace_id,
            parent_run_id=None,
            name="parent",
            run_type=RunType.CHAIN,
            exec_order=0,
            start_time="2026-04-01T10:00:00.000000+00:00",
            end_time="2026-04-01T10:00:01.000000+00:00",
        )
        tmp_writer.save(root)

        for i in range(5):
            child = Run(
                id=f"child-{i}",
                trace_id=trace_id,
                parent_run_id="root",
                name=f"sibling_{i}",
                run_type=RunType.TOOL,
                exec_order=i,
                start_time=f"2026-04-01T10:00:00.{100+i*100:06d}+00:00",
                end_time=f"2026-04-01T10:00:00.{150+i*100:06d}+00:00",
            )
            tmp_writer.save(child)

        runs = tmp_writer.get_trace(trace_id)
        root_node = build_tree(runs)

        assert root_node is not None
        assert len(root_node.children) == 5

        # 验证 exec_order 排序
        for i, child in enumerate(root_node.children):
            assert child.run.name == f"sibling_{i}"
