"""
test_decorators.py — @traceable 装饰器单元测试

测试覆盖：
  TestSyncWrapper      — 同步函数基础行为（Run 创建、入参/出参、名称、run_type、metadata、tags）
  TestAsyncWrapper     — 异步函数基础行为（自动识别 async def）
  TestExceptionCapture — 异常被捕获到 run.error，同时正常向上传播
  TestNestedDecorators — 嵌套调用：parent_run_id / trace_id 对齐 / exec_order
  TestSerialization    — 不可序列化入参 fallback，process_inputs / process_outputs 钩子
  TestDecoratorSyntax  — 不带括号 vs 带括号两种用法
"""

from __future__ import annotations

import asyncio

import pytest

from lightsmith.context import _run_stack
from lightsmith.decorators import set_run_writer, traceable
from lightsmith.models import Run, RunType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_context():
    """每个测试前后重置 ContextVar 调用栈，防止状态污染。"""
    _run_stack.set(())
    yield
    _run_stack.set(())


@pytest.fixture
def captured() -> list[Run]:
    """注入捕获 writer，收集装饰器发出的 Run 对象。"""
    runs: list[Run] = []
    set_run_writer(runs.append)
    yield runs
    set_run_writer(None)


# ---------------------------------------------------------------------------
# TestSyncWrapper
# ---------------------------------------------------------------------------

class TestSyncWrapper:
    def test_run_is_emitted(self, captured):
        @traceable
        def add(x, y):
            return x + y

        result = add(1, 2)
        assert result == 3
        assert len(captured) == 1

    def test_default_name_is_func_name(self, captured):
        @traceable
        def my_function():
            return 0

        my_function()
        assert captured[0].name == "my_function"

    def test_custom_name(self, captured):
        @traceable(name="custom_name")
        def func():
            return 0

        func()
        assert captured[0].name == "custom_name"

    def test_default_run_type_is_custom(self, captured):
        @traceable
        def func():
            return 0

        func()
        assert captured[0].run_type == RunType.CUSTOM

    def test_custom_run_type(self, captured):
        @traceable(run_type=RunType.TOOL)
        def func():
            return 0

        func()
        assert captured[0].run_type == RunType.TOOL

    def test_metadata_merged(self, captured):
        @traceable(metadata={"model": "gpt-4", "temp": 0.7})
        def func():
            return 0

        func()
        assert captured[0].metadata == {"model": "gpt-4", "temp": 0.7}

    def test_tags_merged(self, captured):
        @traceable(tags=["prod", "v2"])
        def func():
            return 0

        func()
        assert captured[0].tags == ["prod", "v2"]

    def test_inputs_serialized(self, captured):
        @traceable
        def add(x, y):
            return x + y

        add(3, 4)
        assert captured[0].inputs == {"x": 3, "y": 4}

    def test_outputs_recorded(self, captured):
        @traceable
        def greet(name):
            return f"hello {name}"

        greet("world")
        assert captured[0].outputs == {"output": "hello world"}

    def test_none_return_recorded(self, captured):
        @traceable
        def noop():
            pass

        noop()
        assert captured[0].outputs == {"output": None}

    def test_end_time_set(self, captured):
        @traceable
        def func():
            return 0

        func()
        assert captured[0].end_time is not None

    def test_start_time_before_end_time(self, captured):
        @traceable
        def func():
            return 0

        func()
        run = captured[0]
        assert run.start_time <= run.end_time

    def test_root_run_has_no_parent(self, captured):
        @traceable
        def func():
            return 0

        func()
        assert captured[0].parent_run_id is None
        assert captured[0].is_root is True

    def test_functools_wraps_preserved(self):
        @traceable
        def my_func():
            """original docstring"""
            return 0

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "original docstring"

    def test_return_value_passes_through(self):
        @traceable
        def compute(x):
            return x * 10

        assert compute(5) == 50


# ---------------------------------------------------------------------------
# TestAsyncWrapper
# ---------------------------------------------------------------------------

class TestAsyncWrapper:
    def test_async_run_is_emitted(self, captured):
        @traceable
        async def async_add(x, y):
            return x + y

        result = asyncio.run(async_add(1, 2))
        assert result == 3
        assert len(captured) == 1

    def test_async_outputs_recorded(self, captured):
        @traceable
        async def fetch():
            return {"data": 42}

        asyncio.run(fetch())
        assert captured[0].outputs == {"output": {"data": 42}}

    def test_async_inputs_serialized(self, captured):
        @traceable
        async def process(text, limit):
            return text

        asyncio.run(process("hello", 100))
        assert captured[0].inputs == {"text": "hello", "limit": 100}

    def test_async_end_time_set(self, captured):
        @traceable
        async def func():
            return 0

        asyncio.run(func())
        assert captured[0].end_time is not None

    def test_async_return_value_passes_through(self):
        @traceable
        async def double(x):
            return x * 2

        assert asyncio.run(double(7)) == 14


# ---------------------------------------------------------------------------
# TestExceptionCapture
# ---------------------------------------------------------------------------

class TestExceptionCapture:
    def test_sync_exception_captured_in_error(self, captured):
        @traceable
        def boom():
            raise ValueError("something went wrong")

        with pytest.raises(ValueError):
            boom()

        assert captured[0].error is not None
        assert "ValueError" in captured[0].error
        assert "something went wrong" in captured[0].error

    def test_sync_exception_propagates(self, captured):
        @traceable
        def boom():
            raise RuntimeError("propagate me")

        with pytest.raises(RuntimeError, match="propagate me"):
            boom()

    def test_sync_exception_outputs_not_set(self, captured):
        @traceable
        def boom():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            boom()

        assert captured[0].outputs is None

    def test_sync_end_time_set_on_exception(self, captured):
        @traceable
        def boom():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            boom()

        assert captured[0].end_time is not None

    def test_async_exception_captured(self, captured):
        @traceable
        async def async_boom():
            raise TypeError("async error")

        with pytest.raises(TypeError):
            asyncio.run(async_boom())

        assert captured[0].error is not None
        assert "TypeError" in captured[0].error

    def test_async_exception_propagates(self, captured):
        @traceable
        async def async_boom():
            raise KeyError("missing key")

        with pytest.raises(KeyError):
            asyncio.run(async_boom())

    def test_traceback_included_in_error(self, captured):
        @traceable
        def deep():
            raise ZeroDivisionError("div by zero")

        with pytest.raises(ZeroDivisionError):
            deep()

        assert "Traceback" in captured[0].error


# ---------------------------------------------------------------------------
# TestNestedDecorators
# ---------------------------------------------------------------------------

class TestNestedDecorators:
    def test_parent_run_id_set_on_child(self, captured):
        @traceable
        def outer():
            inner()

        @traceable
        def inner():
            return 42

        outer()
        # captured 顺序：inner 先完成，outer 后完成
        inner_run = captured[0]
        outer_run = captured[1]

        assert outer_run.parent_run_id is None
        assert inner_run.parent_run_id == outer_run.id

    def test_trace_id_shared_across_tree(self, captured):
        @traceable
        def outer():
            inner()

        @traceable
        def inner():
            return 0

        outer()
        assert captured[0].trace_id == captured[1].trace_id

    def test_exec_order_siblings(self, captured):
        @traceable
        def outer():
            child_a()
            child_b()

        @traceable
        def child_a():
            return "a"

        @traceable
        def child_b():
            return "b"

        outer()
        # captured: child_a(0), child_b(1), outer(2)
        a_run = next(r for r in captured if r.name == "child_a")
        b_run = next(r for r in captured if r.name == "child_b")
        assert a_run.exec_order == 0
        assert b_run.exec_order == 1

    def test_three_level_nesting(self, captured):
        @traceable
        def level1():
            level2()

        @traceable
        def level2():
            level3()

        @traceable
        def level3():
            return "deep"

        level1()
        l1 = next(r for r in captured if r.name == "level1")
        l2 = next(r for r in captured if r.name == "level2")
        l3 = next(r for r in captured if r.name == "level3")

        assert l1.parent_run_id is None
        assert l2.parent_run_id == l1.id
        assert l3.parent_run_id == l2.id
        assert l1.trace_id == l2.trace_id == l3.trace_id

    def test_async_nested_parent_child(self, captured):
        @traceable
        async def outer():
            await inner()

        @traceable
        async def inner():
            return 99

        asyncio.run(outer())
        inner_run = next(r for r in captured if r.name == "inner")
        outer_run = next(r for r in captured if r.name == "outer")

        assert inner_run.parent_run_id == outer_run.id
        assert inner_run.trace_id == outer_run.trace_id

    def test_separate_calls_have_different_trace_ids(self, captured):
        @traceable
        def func():
            return 0

        func()
        func()
        assert captured[0].trace_id != captured[1].trace_id

    def test_context_clean_after_call(self):
        @traceable
        def func():
            return 0

        func()
        from lightsmith.context import get_current_run_id
        assert get_current_run_id() is None


# ---------------------------------------------------------------------------
# TestSerialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_non_serializable_input_fallback(self, captured):
        class Unserializable:
            def __repr__(self):
                return "<Unserializable>"

        @traceable
        def func(obj):
            return 0

        func(Unserializable())
        serialized = captured[0].inputs["obj"]
        assert isinstance(serialized, str)
        assert "Unserializable" in serialized

    def test_large_repr_truncated(self, captured):
        class Big:
            def __repr__(self):
                return "x" * 2000

        @traceable
        def func(obj):
            return 0

        func(Big())
        serialized = captured[0].inputs["obj"]
        assert len(serialized) <= 1100  # 1000 + "[truncated...]" 后缀
        assert "truncated" in serialized

    def test_nested_dict_serialized(self, captured):
        @traceable
        def func(data):
            return 0

        func({"a": {"b": [1, 2, 3]}})
        assert captured[0].inputs == {"data": {"a": {"b": [1, 2, 3]}}}

    def test_process_inputs_hook(self, captured):
        def redact(inputs):
            return {k: "***" if k == "secret" else v for k, v in inputs.items()}

        @traceable(process_inputs=redact)
        def func(user, secret):
            return 0

        func("alice", "my_password")
        assert captured[0].inputs["secret"] == "***"
        assert captured[0].inputs["user"] == "alice"

    def test_process_outputs_hook(self, captured):
        def add_meta(outputs):
            return {**outputs, "extra": "injected"}

        @traceable(process_outputs=add_meta)
        def func():
            return 42

        func()
        assert captured[0].outputs["output"] == 42
        assert captured[0].outputs["extra"] == "injected"

    def test_process_inputs_failure_silently_ignored(self, captured):
        def bad_hook(inputs):
            raise RuntimeError("hook crashed")

        @traceable(process_inputs=bad_hook)
        def func(x):
            return x

        # 不应抛出异常，inputs 保留原始值
        func(99)
        assert captured[0].inputs == {"x": 99}

    def test_process_outputs_failure_silently_ignored(self, captured):
        def bad_hook(outputs):
            raise RuntimeError("hook crashed")

        @traceable(process_outputs=bad_hook)
        def func():
            return 42

        func()
        assert captured[0].outputs == {"output": 42}

    def test_process_inputs_non_dict_return_ignored(self, captured):
        """钩子返回非 dict 时，保留原始序列化结果。"""
        @traceable(process_inputs=lambda d: "not a dict")
        def func(x):
            return x

        func(5)
        assert captured[0].inputs == {"x": 5}

    def test_kwargs_serialized(self, captured):
        @traceable
        def func(a, b=10):
            return a + b

        func(1, b=20)
        assert captured[0].inputs == {"a": 1, "b": 20}


# ---------------------------------------------------------------------------
# TestDecoratorSyntax
# ---------------------------------------------------------------------------

class TestDecoratorSyntax:
    def test_without_parentheses(self, captured):
        @traceable
        def func():
            return 42

        result = func()
        assert result == 42
        assert len(captured) == 1

    def test_with_empty_parentheses(self, captured):
        @traceable()
        def func():
            return 42

        result = func()
        assert result == 42
        assert len(captured) == 1

    def test_with_all_params(self, captured):
        @traceable(
            name="full_example",
            run_type=RunType.AGENT,
            metadata={"k": "v"},
            tags=["t1"],
        )
        def func():
            return 0

        func()
        r = captured[0]
        assert r.name == "full_example"
        assert r.run_type == RunType.AGENT
        assert r.metadata == {"k": "v"}
        assert r.tags == ["t1"]

    def test_writer_failure_does_not_crash_business_code(self):
        def bad_writer(run):
            raise RuntimeError("storage down")

        set_run_writer(bad_writer)
        try:
            @traceable
            def func():
                return 99

            result = func()
            assert result == 99  # 业务代码正常返回
        finally:
            set_run_writer(None)
