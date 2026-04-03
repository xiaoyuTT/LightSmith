"""
schemas 包 — Pydantic 请求/响应模型

定义 API 的输入输出 schema，用于数据验证和序列化。
"""

from app.schemas.run import RunSchema, BatchRunsRequest, BatchRunsResponse

__all__ = [
    "RunSchema",
    "BatchRunsRequest",
    "BatchRunsResponse",
]

# TODO P1.4: 实现 TraceListResponse / TraceDetailResponse schema
