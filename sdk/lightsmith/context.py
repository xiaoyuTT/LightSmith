"""
context.py — LightSmith 上下文管理器（调用树核心）

基于 contextvars.ContextVar 实现：
  - 线程安全 + asyncio 协程安全的 Run 调用栈
  - exec_order 原子计数器（同 parent_run_id 下自增）

设计要点
--------
调用栈使用不可变 tuple 存储，每次 push/pop 都 set 一个新 tuple。
ContextVar 的写时复制（copy-on-write）语义保证：
  - asyncio.create_task() 创建的子任务继承父任务上下文快照，
    子任务内的 push/pop 不影响父任务。
  - 不同线程各自拥有独立的 ContextVar 副本（Python 3.7.1+）。

exec_order 计数器需要跨协程共享（兄弟节点在不同协程中创建时仍需全局有序），
因此使用普通 dict + threading.Lock 实现，而非 ContextVar。
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import Optional


# ---------------------------------------------------------------------------
# 内部状态：调用栈
#
# 每个元素是 (run_id, trace_id) 二元组，组成 _run_stack 调用栈元组，例如
# ((_run_stack.get() + ((run_id, trace_id),))  # 使用不可变 tuple，以利用 ContextVar 的隔离语义。
# _lightsmith_run_stack 是上下文变量的名称，即实际存储在 ContextVar 中的变量名为 "_lightsmith_run_stack"；
# _run_stack 是我们在代码中使用的变量名，指向该 ContextVar 实例，其被初始化为默认值 ()（空调用栈）。
# ---------------------------------------------------------------------------

_run_stack: ContextVar[tuple[tuple[str, str], ...]] = ContextVar(
    "_lightsmith_run_stack", default=()
)


# ---------------------------------------------------------------------------
# 内部状态：exec_order 计数器
#
# key: (trace_id, parent_run_id)
# value: 下一个可分配的 exec_order 值（从 0 开始）
# ---------------------------------------------------------------------------

_exec_order_counters: dict[tuple[str, Optional[str]], int] = {}
_exec_order_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def push_run(run_id: str, trace_id: str) -> None:
    """将 run_id 压入当前上下文的调用栈。

    此操作仅影响当前线程/协程的上下文，不会跨越 asyncio 任务边界。
    """
    stack = _run_stack.get()
    _run_stack.set(stack + ((run_id, trace_id),))


def pop_run() -> None:
    """弹出调用栈顶部的 Run，恢复上一层调用的上下文。

    若栈已为空，此操作为空操作（不抛异常）。
    """
    stack = _run_stack.get()
    if stack:
        _run_stack.set(stack[:-1])


def get_current_run_id() -> Optional[str]:
    """返回当前调用栈顶部的 run_id。

    栈为空（当前代码不在任何被追踪函数内）时返回 None。
    """
    stack = _run_stack.get()
    return stack[-1][0] if stack else None


def get_current_trace_id() -> Optional[str]:
    """返回当前调用栈顶部的 trace_id。

    栈为空时返回 None。
    此函数供 P0.3 装饰器使用，用于将子 Run 的 trace_id 对齐到根 Run。
    """
    stack = _run_stack.get()
    return stack[-1][1] if stack else None


def next_exec_order(trace_id: str, parent_run_id: Optional[str]) -> int:
    """原子地分配下一个 exec_order 值，并将内部计数器加 1。

    同一 (trace_id, parent_run_id) 下的**兄弟节点**按调用此函数的顺序自增，
    从 0 开始。此操作线程安全，适用于多线程和多协程并发场景。

    Args:
        trace_id:      当前调用树的根 trace ID。
        parent_run_id: 父节点的 run_id；顶层 Run 传 None。

    Returns:
        分配给当前 Run 的 exec_order 整数值。
    """
    key = (trace_id, parent_run_id)
    with _exec_order_lock:
        order = _exec_order_counters.get(key, 0)
        _exec_order_counters[key] = order + 1
    return order


def clear_exec_order_counters(trace_id: str) -> None:
    """清理指定 trace 的所有 exec_order 计数器条目。

    应在整条 trace 的根 Run 结束时调用，防止长时间运行的进程中
    _exec_order_counters 字典无限增长。
    """
    with _exec_order_lock:
        keys_to_del = [k for k in _exec_order_counters if k[0] == trace_id]
        for k in keys_to_del:
            del _exec_order_counters[k]
