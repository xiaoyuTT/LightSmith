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
]

__version__ = "0.1.0"
