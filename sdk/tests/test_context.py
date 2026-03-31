"""
test_context.py — P0.2 上下文管理器单元测试

覆盖场景：
  1. 基础 push / pop / get 操作
  2. exec_order 原子计数器
  3. asyncio 并发协程隔离
  4. 多线程隔离
  5. 混合并发（线程池 + asyncio）
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from lightsmith.context import (
    _exec_order_counters,
    _run_stack,
    clear_exec_order_counters,
    get_current_run_id,
    get_current_trace_id,
    next_exec_order,
    pop_run,
    push_run,
)


# ---------------------------------------------------------------------------
# Fixture：每个测试前后清空调用栈和计数器，防止测试间污染
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_context():
    _run_stack.set(())
    yield
    _run_stack.set(())


@pytest.fixture(autouse=True)
def clean_counters():
    with threading.Lock():
        _exec_order_counters.clear()
    yield
    with threading.Lock():
        _exec_order_counters.clear()


# ===========================================================================
# 1. 基础调用栈操作
# ===========================================================================

class TestBasicStack:

    def test_empty_stack_returns_none(self):
        assert get_current_run_id() is None
        assert get_current_trace_id() is None

    def test_push_then_get_run_id(self):
        push_run("run-1", "trace-1")
        assert get_current_run_id() == "run-1"
        pop_run()

    def test_push_then_get_trace_id(self):
        push_run("run-1", "trace-1")
        assert get_current_trace_id() == "trace-1"
        pop_run()

    def test_pop_restores_none(self):
        push_run("run-1", "trace-1")
        pop_run()
        assert get_current_run_id() is None
        assert get_current_trace_id() is None

    def test_pop_empty_stack_is_noop(self):
        pop_run()  # 不应抛异常
        assert get_current_run_id() is None

    def test_pop_twice_on_empty_is_noop(self):
        pop_run()
        pop_run()
        assert get_current_run_id() is None

    def test_nested_push_pop_lifo(self):
        push_run("root", "trace-1")
        push_run("child", "trace-1")
        push_run("grandchild", "trace-1")

        assert get_current_run_id() == "grandchild"
        pop_run()
        assert get_current_run_id() == "child"
        pop_run()
        assert get_current_run_id() == "root"
        pop_run()
        assert get_current_run_id() is None

    def test_multiple_independent_push_pop_cycles(self):
        for i in range(5):
            push_run(f"run-{i}", f"trace-{i}")
            assert get_current_run_id() == f"run-{i}"
            pop_run()
        assert get_current_run_id() is None

    def test_trace_id_follows_nested_stack(self):
        """不同层级可以有不同 trace_id（虽然通常相同，API 不做限制）。"""
        push_run("run-a", "trace-A")
        push_run("run-b", "trace-B")
        assert get_current_trace_id() == "trace-B"
        pop_run()
        assert get_current_trace_id() == "trace-A"
        pop_run()


# ===========================================================================
# 2. exec_order 计数器
# ===========================================================================

class TestExecOrder:

    def test_first_call_returns_zero(self):
        assert next_exec_order("t1", None) == 0

    def test_subsequent_calls_increment(self):
        orders = [next_exec_order("t1", None) for _ in range(4)]
        assert orders == [0, 1, 2, 3]

    def test_different_parent_independent_counters(self):
        o_a = next_exec_order("t1", "parent-A")
        o_b = next_exec_order("t1", "parent-B")
        o_a2 = next_exec_order("t1", "parent-A")
        assert o_a == 0
        assert o_b == 0  # 不同 parent，从 0 重新开始
        assert o_a2 == 1  # parent-A 的第二个子节点

    def test_different_traces_independent(self):
        o1 = next_exec_order("trace-X", "parent-1")
        o2 = next_exec_order("trace-Y", "parent-1")
        assert o1 == 0
        assert o2 == 0  # 不同 trace，计数器独立

    def test_clear_resets_counters(self):
        next_exec_order("t-clear", "p")
        next_exec_order("t-clear", "p")
        clear_exec_order_counters("t-clear")
        assert next_exec_order("t-clear", "p") == 0

    def test_clear_only_removes_target_trace(self):
        next_exec_order("t-keep", "p")
        next_exec_order("t-del", "p")
        clear_exec_order_counters("t-del")
        # t-keep 的计数器不受影响
        assert next_exec_order("t-keep", "p") == 1

    def test_concurrent_threads_no_duplicate_exec_order(self):
        """20 个线程并发争抢同一 parent 的 exec_order，结果应无重复且连续。"""
        results: list[int] = []
        lock = threading.Lock()

        def worker():
            o = next_exec_order("concurrent-trace", "shared-parent")
            with lock:
                results.append(o)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == list(range(20))


# ===========================================================================
# 3. asyncio 协程隔离
# ===========================================================================

class TestAsyncIsolation:

    def test_concurrent_tasks_do_not_pollute_each_other(self):
        """两个并发协程各自 push 不同 run_id，互不影响。"""

        async def task(run_id: str, trace_id: str) -> str:
            push_run(run_id, trace_id)
            await asyncio.sleep(0)  # 主动让出，允许另一协程运行
            seen = get_current_run_id()
            pop_run()
            return seen  # type: ignore[return-value]

        async def main():
            return await asyncio.gather(
                task("run-A", "trace-A"),
                task("run-B", "trace-B"),
            )

        results = asyncio.run(main())
        assert results[0] == "run-A"
        assert results[1] == "run-B"

    def test_child_task_inherits_parent_context_snapshot(self):
        """asyncio.create_task 的子任务应继承父任务创建时的上下文快照。"""

        async def main():
            push_run("parent-run", "trace-1")

            async def child():
                return get_current_run_id()

            result = await asyncio.create_task(child())
            pop_run()
            return result

        assert asyncio.run(main()) == "parent-run"

    def test_child_task_push_does_not_affect_parent(self):
        """子任务内的 push 不影响父任务的调用栈。"""

        async def main():
            push_run("parent-run", "trace-1")

            async def child():
                push_run("child-run", "trace-1")
                await asyncio.sleep(0)
                pop_run()

            child_task = asyncio.create_task(child())
            await asyncio.sleep(0)  # 让子任务有机会执行 push
            parent_view = get_current_run_id()  # 父任务看到的仍是自己的栈顶
            await child_task
            pop_run()
            return parent_view

        assert asyncio.run(main()) == "parent-run"

    def test_100_concurrent_coroutines_isolated(self):
        """100 个并发协程各自管理自己的调用栈，全部隔离正确。"""

        async def worker(i: int) -> bool:
            run_id = f"run-{i}"
            push_run(run_id, f"trace-{i}")
            await asyncio.sleep(0)
            ok = get_current_run_id() == run_id
            pop_run()
            return ok

        async def main():
            return await asyncio.gather(*[worker(i) for i in range(100)])

        results = asyncio.run(main())
        assert all(results)

    def test_deeply_nested_async_stack(self):
        """深度嵌套（5 层）异步调用栈行为正确。"""

        async def level(depth: int, trace_id: str) -> list[str]:
            run_id = f"run-depth-{depth}"
            push_run(run_id, trace_id)
            if depth < 4:
                inner = await level(depth + 1, trace_id)
            else:
                inner = []
            top = get_current_run_id()
            pop_run()
            return [top] + inner

        result = asyncio.run(level(0, "deep-trace"))
        expected = [f"run-depth-{i}" for i in range(5)]
        assert result == expected


# ===========================================================================
# 4. 多线程隔离
# ===========================================================================

class TestThreadIsolation:

    def test_threads_have_independent_stacks(self):
        """10 个线程各自 push 自己的 run_id，互不影响。"""
        results: dict[int, str | None] = {}

        def thread_fn(idx: int) -> None:
            push_run(f"run-{idx}", f"trace-{idx}")
            time.sleep(0.01)  # 故意与其他线程重叠
            results[idx] = get_current_run_id()
            pop_run()

        threads = [threading.Thread(target=thread_fn, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(10):
            assert results[i] == f"run-{i}"

    def test_main_thread_unaffected_by_child_threads(self):
        """子线程的 push/pop 不影响主线程的调用栈。"""
        push_run("main-run", "main-trace")

        def child_fn():
            push_run("child-run", "child-trace")
            time.sleep(0.02)
            pop_run()

        t = threading.Thread(target=child_fn)
        t.start()
        time.sleep(0.01)  # 子线程已执行 push
        main_view = get_current_run_id()
        t.join()
        pop_run()

        assert main_view == "main-run"


# ===========================================================================
# 5. asyncio + ThreadPoolExecutor 混用
# ===========================================================================

class TestAsyncThreadMix:

    def test_executor_thread_has_independent_context(self):
        """
        在 Python 3.11 中，loop.run_in_executor 启动的线程不会继承
        调用方协程的 ContextVar 状态——线程以默认值（空栈）启动。

        这意味着：若需要在线程池任务中传递 run_id，必须通过函数参数
        显式传递，而不能依赖上下文自动传播。

        同时验证：线程内的 push/pop 不影响协程侧的调用栈。
        """
        import concurrent.futures

        async def main():
            push_run("async-run", "async-trace")

            executor_result: dict = {}

            def sync_task():
                # 线程不继承协程的上下文，_run_stack 为空
                executor_result["seen"] = get_current_run_id()
                # 线程内 push 只影响线程自己的上下文
                push_run("thread-run", "async-trace")
                executor_result["after_push"] = get_current_run_id()
                pop_run()

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                await loop.run_in_executor(pool, sync_task)

            # 协程的栈不受线程内 push/pop 影响
            async_view = get_current_run_id()
            pop_run()
            return executor_result, async_view

        executor_result, async_view = asyncio.run(main())
        # Python 3.11: 线程以默认值（None）启动，不继承协程上下文
        assert executor_result["seen"] is None
        assert executor_result["after_push"] == "thread-run"
        assert async_view == "async-run"  # 协程侧完全不受影响
