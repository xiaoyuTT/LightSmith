"""
decorators.py — LightSmith @traceable 装饰器

将同步或异步函数标记为可追踪，自动创建 Run 并建立调用树。

用法示例
--------
    @traceable
    def my_func(x, y):
        return x + y

    @traceable(name="my_tool", run_type=RunType.TOOL, metadata={"version": "1"}, tags=["prod"])
    async def my_async_func(x):
        return await some_api_call(x)

    @traceable(
        process_inputs=lambda d: {k: v for k, v in d.items() if k != "secret"},
        process_outputs=lambda d: d,
    )
    def my_func(secret, data):
        return process(data)
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from lightsmith.context import (
    clear_exec_order_counters,
    get_current_run_id,
    get_current_trace_id,
    next_exec_order,
    pop_run,
    push_run,
)
from lightsmith.models import Run, RunType


# ---------------------------------------------------------------------------
# 全局 Run 写入钩子
#
# 默认为 None（P0.3 无存储）。P0.4 中注入 SQLite writer：
#   from lightsmith.decorators import set_run_writer
#   set_run_writer(sqlite_writer.save)
#
# 测试时注入捕获列表：
#   set_run_writer(captured_runs.append)
# ---------------------------------------------------------------------------

_run_writer: Optional[Callable[[Run], None]] = None


def set_run_writer(writer: Optional[Callable[[Run], None]]) -> None:
    """设置全局 Run 写入函数。设为 None 即清除，恢复为无存储模式。"""
    global _run_writer
    _run_writer = writer


def _emit_run(run: Run) -> None:
    """将已完成的 Run 发送给 writer。写入失败时静默忽略，不影响业务代码。"""
    if _run_writer is not None:
        try:
            _run_writer(run)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 入参 / 出参序列化
# ---------------------------------------------------------------------------

_MAX_REPR_LEN = 1000  # fallback repr 截断阈值


def _safe_serialize(v: Any) -> Any:
    """将单个值递归转换为 JSON 兼容类型。

    处理顺序：
    1. 基础类型（str / int / float / bool / None）直接返回
    2. dict 递归处理每个 key-value（key 强制转为 str）
    3. list / tuple 递归处理每个元素
    4. 其他类型尝试 json.dumps 验证；失败则 fallback 为截断的 repr 字符串
    """
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {str(k): _safe_serialize(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_safe_serialize(item) for item in v]
    # 其他类型尝试 JSON 序列化
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        s = repr(v)
        if len(s) > _MAX_REPR_LEN:
            s = s[:_MAX_REPR_LEN] + f"...[truncated, type={type(v).__name__}]"
        return s


def _serialize_inputs(func: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    """通过函数签名将位置/关键字参数绑定为命名 dict 并序列化。

    绑定失败（如 *args 函数）时降级为 __args / __kwargs 格式。
    """
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return {k: _safe_serialize(v) for k, v in bound.arguments.items()}
    except Exception:
        return {
            "__args": [_safe_serialize(a) for a in args],
            "__kwargs": {k: _safe_serialize(v) for k, v in kwargs.items()},
        }


def _serialize_output(output: Any) -> dict[str, Any]:
    """将返回值包装为统一的 {"output": ...} 格式并序列化。"""
    return {"output": _safe_serialize(output)}


# ---------------------------------------------------------------------------
# Run 生命周期管理
# ---------------------------------------------------------------------------

def _build_run(
    func: Callable,
    args: tuple,
    kwargs: dict,
    name: Optional[str],
    run_type: RunType,
    metadata: dict[str, Any],
    tags: list[str],
    process_inputs: Optional[Callable[[dict], dict]],
) -> Run:
    """创建 Run，建立父子关系，分配 exec_order，序列化入参。"""
    parent_run_id = get_current_run_id()
    parent_trace_id = get_current_trace_id()

    run = Run(
        name=name or func.__name__,
        run_type=run_type,
        parent_run_id=parent_run_id,
        metadata=dict(metadata),
        tags=list(tags),
    )

    # 子 Run 对齐到根 Run 的 trace_id，确保整棵树共享同一 trace_id
    if parent_trace_id is not None:
        run.trace_id = parent_trace_id

    # 在正确的 (trace_id, parent_run_id) 键下分配 exec_order
    run.exec_order = next_exec_order(run.trace_id, parent_run_id)

    # 序列化入参，并执行用户钩子
    raw_inputs = _serialize_inputs(func, args, kwargs)
    if process_inputs is not None:
        try:
            processed = process_inputs(raw_inputs)
            if isinstance(processed, dict):
                raw_inputs = processed
        except Exception:
            pass  # 钩子失败，保留原始序列化结果

    run.inputs = raw_inputs
    return run


def _finalize_run(
    run: Run,
    output: Any,
    exc: Optional[BaseException],
    process_outputs: Optional[Callable[[dict], dict]],
) -> None:
    """记录 Run 完成时间，写入 outputs 或 error。"""
    run.end_time = datetime.now(timezone.utc).isoformat()

    if exc is not None:
        run.error = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
    else:
        out_dict = _serialize_output(output)
        if process_outputs is not None:
            try:
                processed = process_outputs(out_dict)
                if isinstance(processed, dict):
                    out_dict = processed
            except Exception:
                pass  # 钩子失败，保留原始序列化结果
        run.outputs = out_dict


# ---------------------------------------------------------------------------
# 公开装饰器
# ---------------------------------------------------------------------------

def traceable(
    func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    run_type: RunType = RunType.CUSTOM,
    metadata: Optional[dict[str, Any]] = None,
    tags: Optional[list[str]] = None,
    process_inputs: Optional[Callable[[dict], dict]] = None,
    process_outputs: Optional[Callable[[dict], dict]] = None,
) -> Any:
    """将同步或异步函数标记为可追踪，自动创建 Run 并建立调用树。

    支持两种用法：

        @traceable                             # 不带参数（直接包装）
        def my_func(): ...

        @traceable(                            # 带参数
            name="my_name",
            run_type=RunType.TOOL,
            metadata={"key": "val"},
            tags=["prod"],
            process_inputs=lambda d: d,
            process_outputs=lambda d: d,
        )
        async def my_async_func(): ...

    async def 函数自动识别，无需用户区分；嵌套调用自动建立父子关系。

    Args:
        name:            展示名，默认使用函数名。
        run_type:        Run 类型（RunType 枚举），默认 CUSTOM。
        metadata:        额外键值对，合并到 Run.metadata。
        tags:            字符串标签列表，合并到 Run.tags。
        process_inputs:  入参后处理钩子：接收序列化后的 dict，返回新 dict。
                         失败时静默忽略，保留原始序列化结果。
        process_outputs: 返回值后处理钩子：接收序列化后的 dict，返回新 dict。
                         失败时静默忽略，保留原始序列化结果。
    """
    _metadata: dict[str, Any] = metadata or {}
    _tags: list[str] = tags or []

    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                run = _build_run(
                    fn, args, kwargs, name, run_type, _metadata, _tags, process_inputs
                )
                is_root = run.is_root
                push_run(run.id, run.trace_id)
                caught_exc: Optional[BaseException] = None
                output: Any = None
                try:
                    # 异步函数，需要通过 await 来执行，才能正确捕获异常和结果
                    output = await fn(*args, **kwargs)
                    return output
                except BaseException as exc:
                    caught_exc = exc
                    raise
                finally:
                    pop_run()
                    _finalize_run(run, output, caught_exc, process_outputs)
                    _emit_run(run)
                    if is_root:
                        clear_exec_order_counters(run.trace_id)

            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                run = _build_run(
                    fn, args, kwargs, name, run_type, _metadata, _tags, process_inputs
                )
                is_root = run.is_root
                push_run(run.id, run.trace_id)
                caught_exc: Optional[BaseException] = None
                output: Any = None
                try:
                    output = fn(*args, **kwargs)
                    return output
                except BaseException as exc:
                    caught_exc = exc
                    raise
                finally:
                    pop_run()
                    _finalize_run(run, output, caught_exc, process_outputs)
                    _emit_run(run)
                    if is_root:
                        clear_exec_order_counters(run.trace_id)

            return sync_wrapper

    # 允许 @traceable（不带括号）直接作为装饰器使用
    if func is not None:
        return decorator(func)
    return decorator
