"""
models.py — LightSmith 核心数据模型

定义追踪系统的基础数据结构：
  - RunType: 枚举，标识一次调用的类型（LLM / 工具 / 链等）
  - Run: dataclass，表示一次函数调用的完整生命周期记录
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# RunType 枚举
# ---------------------------------------------------------------------------

class RunType(str, Enum):
    """一次 Run 的类型，决定 UI 展示的图标和分类过滤行为。

    继承 str 使枚举值可直接作为字符串比较和 JSON 序列化。
    """
    CHAIN = "chain"    # 多步骤业务逻辑链
    LLM = "llm"        # 大模型调用（OpenAI、Anthropic 等）
    TOOL = "tool"      # 工具 / 函数调用
    AGENT = "agent"    # 自主决策的 Agent 入口
    CUSTOM = "custom"  # 用户自定义类型


# ---------------------------------------------------------------------------
# Run dataclass
# ---------------------------------------------------------------------------

@dataclass
class Run:
    """表示一次被追踪函数调用的完整记录。

    字段命名和语义与 LangSmith 保持兼容，方便后续对齐。

    Attributes:
        id:            Run 的全局唯一 ID（UUID4 字符串）。
        trace_id:      本次顶层调用链的 ID，同一调用树内所有 Run 共享。
        parent_run_id: 父 Run 的 ID；顶层 Run 为 None。
        name:          函数名或用户指定的展示名。
        run_type:      Run 类型，见 RunType 枚举。
        inputs:        函数入参的可序列化快照，dict 形式。
        outputs:       函数返回值的可序列化快照，dict 形式；未完成时为 None。
        error:         若执行抛出异常，此处存储 "ExcType: message\nTraceback..." 字符串。
        start_time:    创建 Run 时的 UTC 时间戳（ISO 8601）。
        end_time:      函数退出时的 UTC 时间戳；未完成时为 None。
        metadata:      用户自定义键值对，用于扩展信息（如 model、temperature）。
        tags:          字符串标签列表，用于过滤和分组。
        exec_order:    同一 parent 下子节点的创建顺序（从 0 开始），决定 UI 中的排列顺序。
    """

    # --- 身份字段 ---
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_run_id: str | None = None

    # --- 描述字段 ---
    name: str = "unnamed"
    run_type: RunType = RunType.CUSTOM

    # --- 数据字段 ---
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] | None = None
    error: str | None = None

    # --- 时间字段（ISO 8601 UTC 字符串，序列化友好） ---
    start_time: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    end_time: str | None = None

    # --- 扩展字段 ---
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    # exec_order 由 context 层赋值，初始为 0
    exec_order: int = 0

    # ---------------------------------------------------------------------------
    # 序列化 / 反序列化
    # ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """将 Run 序列化为纯 Python dict（可直接 JSON 序列化）。

        run_type 以字符串形式输出，与数据库存储和 HTTP 传输格式保持一致。
        """
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_run_id": self.parent_run_id,
            "name": self.name,
            "run_type": self.run_type.value,  # 枚举 → 字符串
            "inputs": self.inputs,
            "outputs": self.outputs,
            "error": self.error,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "metadata": self.metadata,
            "tags": self.tags,
            "exec_order": self.exec_order,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Run":
        """从 dict（通常来自 JSON 反序列化）还原 Run 实例。

        run_type 字段接受字符串或 RunType 枚举，兼容不同来源的输入。
        """
        # 防御性拷贝，避免修改调用方传入的原始 dict
        d = dict(data)

        # 将字符串形式的 run_type 转回枚举
        raw_type = d.get("run_type", RunType.CUSTOM)
        if isinstance(raw_type, str):
            d["run_type"] = RunType(raw_type)

        return cls(**d)

    # ---------------------------------------------------------------------------
    # 便利属性
    # ---------------------------------------------------------------------------

    @property
    def duration_ms(self) -> float | None:
        """返回执行耗时（毫秒）；Run 尚未结束时返回 None。"""
        if self.start_time is None or self.end_time is None:
            return None
        start = datetime.fromisoformat(self.start_time)
        end = datetime.fromisoformat(self.end_time)
        return (end - start).total_seconds() * 1000

    @property
    def is_root(self) -> bool:
        """该 Run 是否为调用树的根节点（无父节点）。"""
        return self.parent_run_id is None

    @property
    def has_error(self) -> bool:
        """该 Run 是否以异常结束。"""
        return self.error is not None

    def __repr__(self) -> str:
        status = "ERROR" if self.has_error else ("running" if self.end_time is None else "ok")
        dur = f"{self.duration_ms:.1f}ms" if self.duration_ms is not None else "..."
        return f"<Run [{self.run_type.value}] {self.name!r} {dur} {status}>"
