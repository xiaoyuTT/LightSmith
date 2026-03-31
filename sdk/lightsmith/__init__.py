"""lightsmith SDK 公开接口。

外部代码只需 `from lightsmith import traceable, Run, RunType` 即可使用核心功能。
随着各子模块开发完成，在此处逐步补充 __all__。
"""

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
]

__version__ = "0.1.0"
