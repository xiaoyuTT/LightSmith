"""lightsmith SDK 公开接口。

外部代码只需 `from lightsmith import traceable, Run, RunType` 即可使用核心功能。
随着各子模块开发完成，在此处逐步补充 __all__。
"""

from __future__ import annotations

import os
from typing import Union
from lightsmith.models import Run, RunType
from lightsmith.context import (
    push_run,
    pop_run,
    get_current_run_id,
    get_current_trace_id,
    next_exec_order,
    clear_exec_order_counters,
)
from lightsmith.decorators import traceable, set_run_writer
from lightsmith.storage.sqlite import RunWriter, get_default_writer


def init_local_storage(db_path: str | None = None) -> RunWriter:
    """初始化本地 SQLite 存储并将其注册为全局 Run 写入器。

    调用后，所有被 @traceable 装饰的函数完成时，Run 会自动写入 SQLite。

    Args:
        db_path: 数据库文件路径；None 时使用 LIGHTSMITH_DB_PATH 环境变量
                 或默认路径 ~/.lightsmith/traces.db。

    Returns:
        已初始化的 RunWriter 实例（可用于直接调用 get_trace 等方法）。

    用法::

        import lightsmith as ls

        ls.init_local_storage()   # 使用默认路径

        @ls.traceable
        def my_func(x):
            return x * 2

        my_func(21)
        runs = ls.get_default_writer().get_trace(...)
    """
    from lightsmith.storage.sqlite import RunWriter as _RunWriter
    writer = _RunWriter(db_path=db_path)
    set_run_writer(writer.save)
    return writer


def init_http_transport(
    endpoint: str | None = None,
    api_key: str | None = None,
    max_batch_size: int = 100,
    flush_interval: float = 5.0,
) -> "HttpWriter":
    """初始化 HTTP transport 并将其注册为全局 Run 写入器。

    调用后，所有被 @traceable 装饰的函数完成时，Run 会自动批量上报到后端。

    Args:
        endpoint: 后端 API 地址（None 时从 LIGHTSMITH_ENDPOINT 环境变量读取，
                 默认 http://localhost:8000）。
        api_key: API 密钥（None 时从 LIGHTSMITH_API_KEY 环境变量读取，
                预留，P3.2 启用鉴权时使用）。
        max_batch_size: 批量大小，达到时立即 flush（默认 100）。
        flush_interval: 定时 flush 间隔，单位秒（默认 5.0）。

    Returns:
        已初始化的 HttpWriter 实例（可用于手动 flush）。

    用法::

        import lightsmith as ls

        # 使用默认配置（从环境变量读取）
        ls.init_http_transport()

        # 或显式指定配置
        ls.init_http_transport(endpoint="http://localhost:8000")

        @ls.traceable
        def my_func(x):
            return x * 2

        my_func(21)  # Run 会自动批量上报到后端
    """
    from lightsmith.storage.http import HttpWriter as _HttpWriter
    writer = _HttpWriter(
        endpoint=endpoint,
        api_key=api_key,
        max_batch_size=max_batch_size,
        flush_interval=flush_interval,
    )
    set_run_writer(writer.save)
    return writer


def init_auto() -> Union[RunWriter, "HttpWriter"]:
    """自动选择存储后端并初始化。

    根据环境变量 LIGHTSMITH_LOCAL 决定使用本地 SQLite 或 HTTP transport：
      - LIGHTSMITH_LOCAL=true: 使用本地 SQLite（离线模式）
      - 否则：使用 HTTP transport（默认）

    Returns:
        已初始化的 writer 实例（RunWriter 或 HttpWriter）。

    用法::

        import lightsmith as ls

        # 自动根据环境变量选择后端
        ls.init_auto()

        @ls.traceable
        def my_func(x):
            return x * 2

        my_func(21)
    """
    use_local = os.environ.get("LIGHTSMITH_LOCAL", "").lower() in ("true", "1", "yes")
    if use_local:
        return init_local_storage()
    else:
        return init_http_transport()


__all__ = [
    "Run",
    "RunType",
    "push_run",
    "pop_run",
    "get_current_run_id",
    "get_current_trace_id",
    "next_exec_order",
    "clear_exec_order_counters",
    "traceable",
    "set_run_writer",
    "RunWriter",
    "get_default_writer",
    "init_local_storage",
    "init_http_transport",
    "init_auto",
]

__version__ = "0.1.0"
