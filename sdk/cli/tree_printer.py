#!/usr/bin/env python3
"""
tree_printer.py — LightSmith CLI 树打印工具

从 SQLite 读取 trace 并以树状格式打印调用链，便于终端快速查看追踪结果。

用法：
    python -m cli.tree_printer --trace-id <trace_id>    # 查看指定 trace
    python -m cli.tree_printer --last                   # 查看最近一条 trace

节点格式：
    [图标] 函数名  耗时ms  [ERROR]

    图标映射：
      🔗 CHAIN   — 业务逻辑链
      🤖 LLM     — 大模型调用
      🔧 TOOL    — 工具/函数调用
      🧠 AGENT   — 自主决策 Agent
      ⚙️  CUSTOM  — 自定义类型
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from lightsmith.models import Run, RunType
from lightsmith.storage.sqlite import RunWriter


# ---------------------------------------------------------------------------
# 跨平台 UTF-8 输出
# ---------------------------------------------------------------------------

def safe_print(text: str, file=None) -> None:
    """安全地打印包含 emoji 的文本（兼容 Windows GBK）。

    在 Windows 下，如果终端不支持 UTF-8，emoji 会被替换为 ASCII 回退字符。
    """
    if file is None:
        file = sys.stdout

    try:
        print(text, file=file)
    except UnicodeEncodeError:
        # 回退：移除无法编码的字符
        safe_text = text.encode(file.encoding, errors="replace").decode(file.encoding)
        print(safe_text, file=file)


# ---------------------------------------------------------------------------
# 图标映射
# ---------------------------------------------------------------------------

_RUN_TYPE_ICONS = {
    RunType.CHAIN: "🔗",
    RunType.LLM: "🤖",
    RunType.TOOL: "🔧",
    RunType.AGENT: "🧠",
    RunType.CUSTOM: "⚙️",
}

# ANSI 颜色代码
_COLOR_RED = "\033[91m"
_COLOR_RESET = "\033[0m"
_COLOR_GRAY = "\033[90m"


# ---------------------------------------------------------------------------
# 树节点类
# ---------------------------------------------------------------------------

class TreeNode:
    """树节点，用于递归构建和打印调用树。"""

    def __init__(self, run: Run) -> None:
        self.run = run
        self.children: list[TreeNode] = []

    def add_child(self, child: TreeNode) -> None:
        """添加子节点（已按 exec_order 排序，无需重新排序）。"""
        self.children.append(child)


# ---------------------------------------------------------------------------
# 树构建
# ---------------------------------------------------------------------------

def build_tree(runs: list[Run]) -> Optional[TreeNode]:
    """从 Run 列表构建调用树。

    Args:
        runs: 已按 exec_order 排序的 Run 列表（来自 RunWriter.get_trace）。

    Returns:
        根节点（parent_run_id 为 None 的节点）；若无根节点返回 None。
    """
    if not runs:
        return None

    # id → TreeNode 映射表
    node_map: dict[str, TreeNode] = {}
    root: Optional[TreeNode] = None

    # 第一遍：创建所有节点
    for run in runs:
        node = TreeNode(run)
        node_map[run.id] = node

    # 第二遍：建立父子关系
    for run in runs:
        node = node_map[run.id]
        if run.parent_run_id is None:
            # 根节点
            root = node
        else:
            # 子节点：挂到父节点下
            parent = node_map.get(run.parent_run_id)
            if parent is not None:
                parent.add_child(node)

    return root


# ---------------------------------------------------------------------------
# 树打印
# ---------------------------------------------------------------------------

def format_duration(run: Run) -> str:
    """格式化耗时，保留 1 位小数。"""
    duration = run.duration_ms
    if duration is None:
        return _COLOR_GRAY + "..." + _COLOR_RESET
    return f"{duration:.1f}ms"


def format_node_line(run: Run) -> str:
    """格式化单个节点行：[图标] 名称  耗时  [ERROR]"""
    icon = _RUN_TYPE_ICONS.get(run.run_type, "❓")
    name = run.name
    duration = format_duration(run)
    error_tag = ""

    if run.has_error:
        # 错误节点：整行红色 + [ERROR] 标签
        error_tag = f" {_COLOR_RED}[ERROR]{_COLOR_RESET}"
        return f"{_COLOR_RED}{icon} {name}{_COLOR_RESET}  {duration}{error_tag}"
    else:
        return f"{icon} {name}  {duration}"


def print_tree(node: TreeNode, prefix: str = "", is_last: bool = True) -> None:
    """递归打印树节点（带树形连接线）。

    Args:
        node: 当前节点。
        prefix: 当前行的前缀（由上层节点的树枝字符组成）。
        is_last: 当前节点是否为父节点的最后一个子节点。
    """
    # 当前节点的树枝符号
    connector = "└── " if is_last else "├── "

    # 打印当前节点
    if prefix == "":
        # 根节点不加前缀
        safe_print(format_node_line(node.run))
    else:
        safe_print(prefix + connector + format_node_line(node.run))

    # 递归打印子节点
    child_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(node.children):
        is_last_child = (i == len(node.children) - 1)
        print_tree(child, child_prefix, is_last_child)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def get_last_trace_id(writer: RunWriter) -> Optional[str]:
    """查询最近一条 trace 的 trace_id（按 start_time 降序）。

    直接操作 RunWriter 的内部连接，执行自定义查询。
    """
    with writer._lock:
        cursor = writer._conn.execute("""
            SELECT trace_id
            FROM   runs
            WHERE  parent_run_id IS NULL
            ORDER  BY start_time DESC
            LIMIT  1
        """)
        row = cursor.fetchone()
        return row["trace_id"] if row else None


def main() -> None:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        description="LightSmith 追踪树打印工具 — 从 SQLite 读取并以树形格式展示调用链",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s --trace-id abc123                # 查看指定 trace
  %(prog)s --last                           # 查看最近一条 trace
  LIGHTSMITH_DB_PATH=/tmp/test.db %(prog)s --last   # 指定数据库路径
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--trace-id",
        type=str,
        help="要查看的 trace ID（UUID 字符串）",
    )
    group.add_argument(
        "--last",
        action="store_true",
        help="查看最近一条 trace（按 start_time 降序）",
    )

    args = parser.parse_args()

    # 初始化 RunWriter（使用环境变量或默认路径）
    try:
        writer = RunWriter()
    except Exception as e:
        safe_print(f"❌ 无法打开数据库：{e}", file=sys.stderr)
        sys.exit(1)

    # 获取 trace_id
    trace_id: Optional[str] = None
    if args.last:
        trace_id = get_last_trace_id(writer)
        if trace_id is None:
            safe_print("❌ 数据库中没有任何 trace", file=sys.stderr)
            sys.exit(1)
        safe_print(f"{_COLOR_GRAY}最近一条 trace: {trace_id}{_COLOR_RESET}\n")
    else:
        trace_id = args.trace_id

    # 查询 trace
    try:
        runs = writer.get_trace(trace_id)
    except Exception as e:
        safe_print(f"❌ 查询失败：{e}", file=sys.stderr)
        sys.exit(1)

    if not runs:
        safe_print(f"❌ trace_id={trace_id} 不存在", file=sys.stderr)
        sys.exit(1)

    # 构建树
    root = build_tree(runs)
    if root is None:
        safe_print("❌ trace 数据损坏：找不到根节点", file=sys.stderr)
        sys.exit(1)

    # 打印树
    print_tree(root)

    # 打印摘要
    error_count = sum(1 for run in runs if run.has_error)
    total_duration = root.run.duration_ms
    safe_print("")
    safe_print(f"{_COLOR_GRAY}───────────────────────────────────────{_COLOR_RESET}")
    safe_print(f"{_COLOR_GRAY}节点数: {len(runs)}  |  错误: {error_count}  |  总耗时: {total_duration:.1f}ms{_COLOR_RESET}" if total_duration else f"{_COLOR_GRAY}节点数: {len(runs)}  |  错误: {error_count}{_COLOR_RESET}")


if __name__ == "__main__":
    main()
