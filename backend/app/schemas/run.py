"""
run.py — Run 相关的 Pydantic schemas

定义 API 的请求/响应模型，用于数据验证和序列化。
与 SDK 的 Run dataclass 和 ORM 的 Run 模型保持字段一致。
"""

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class RunSchema(BaseModel):
    """Run 的 Pydantic 模型（API 层）

    字段与 SDK Run dataclass 完全对齐，用于请求体验证和响应序列化。
    注意：metadata 字段在 API 层使用 metadata，在 ORM 层映射为 run_metadata。
    """

    # --- 身份字段 ---
    id: str = Field(..., description="Run 的全局唯一 ID (UUID4)")
    trace_id: str = Field(..., description="顶层调用链的 ID")
    parent_run_id: Optional[str] = Field(None, description="父 Run 的 ID，顶层为 null")

    # --- 描述字段 ---
    name: str = Field(..., description="函数名或展示名")
    run_type: str = Field(..., description="Run 类型：chain/llm/tool/agent/custom")

    # --- 数据字段 ---
    inputs: dict[str, Any] = Field(default_factory=dict, description="函数入参的 JSON 快照")
    outputs: Optional[dict[str, Any]] = Field(None, description="函数返回值的 JSON 快照")
    error: Optional[str] = Field(None, description="异常信息")

    # --- 时间字段（ISO 8601 字符串）---
    start_time: str = Field(..., description="创建时间 (UTC ISO 8601)")
    end_time: Optional[str] = Field(None, description="结束时间 (UTC ISO 8601)")

    # --- 扩展字段 ---
    metadata: dict[str, Any] = Field(default_factory=dict, description="用户自定义键值对")
    tags: list[str] = Field(default_factory=list, description="字符串标签列表")

    # --- 排序字段 ---
    exec_order: int = Field(default=0, description="同一父节点下的创建顺序")

    @field_validator("run_type")
    @classmethod
    def validate_run_type(cls, v: str) -> str:
        """验证 run_type 是否为合法值"""
        valid_types = {"chain", "llm", "tool", "agent", "custom"}
        if v not in valid_types:
            raise ValueError(f"run_type 必须是 {valid_types} 之一，收到: {v}")
        return v

    model_config = ConfigDict(
        # 允许从 ORM 模型创建（用于响应序列化）
        from_attributes=True,
        # JSON schema 示例（用于 API 文档）
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "trace_id": "550e8400-e29b-41d4-a716-446655440001",
                "parent_run_id": None,
                "name": "process_order",
                "run_type": "chain",
                "inputs": {"order_id": "12345", "user_id": "67890"},
                "outputs": {"status": "success", "order_total": 99.99},
                "error": None,
                "start_time": "2026-04-03T10:00:00.000000Z",
                "end_time": "2026-04-03T10:00:02.500000Z",
                "metadata": {"version": "1.0", "env": "production"},
                "tags": ["payment", "critical"],
                "exec_order": 0,
            }
        },
    )


class BatchRunsRequest(BaseModel):
    """批量摄入请求体"""

    runs: list[RunSchema] = Field(
        ...,
        description="Run 列表",
        min_length=1,
    )

    @field_validator("runs")
    @classmethod
    def validate_batch_size(cls, v: list[RunSchema]) -> list[RunSchema]:
        """验证批量大小不超过限制"""
        # 注意：这里硬编码 1000，实际应从配置读取，但 Pydantic validator 中访问配置较复杂
        # 在路由层也会做检查，这里作为第一层防护
        max_size = 1000
        if len(v) > max_size:
            raise ValueError(f"批量大小不能超过 {max_size}，收到: {len(v)}")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "runs": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "trace_id": "550e8400-e29b-41d4-a716-446655440001",
                        "parent_run_id": None,
                        "name": "main_task",
                        "run_type": "chain",
                        "inputs": {"task": "process"},
                        "outputs": {"result": "done"},
                        "error": None,
                        "start_time": "2026-04-03T10:00:00Z",
                        "end_time": "2026-04-03T10:00:01Z",
                        "metadata": {},
                        "tags": ["production"],
                        "exec_order": 0,
                    }
                ]
            }
        },
    )


class BatchRunsResponse(BaseModel):
    """批量摄入响应体"""

    accepted: int = Field(..., description="实际插入的新记录数")
    duplicates: int = Field(default=0, description="因 ID 冲突而忽略的记录数")
    total: int = Field(..., description="请求中的 Run 总数")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "accepted": 98,
                "duplicates": 2,
                "total": 100,
            }
        },
    )
