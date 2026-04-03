"""
trace.py — Trace 相关的 Pydantic schemas

定义 Trace 查询 API 的响应模型：
  - TraceListItem: 列表页的 trace 摘要
  - TraceTreeNode: 树形 JSON 节点（递归结构）
  - TracesListResponse: 分页列表响应
"""

from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict, computed_field
from datetime import datetime


class TraceListItem(BaseModel):
    """Trace 列表项（根 Run 摘要）

    用于 GET /api/traces 分页列表响应。
    仅包含必要的摘要信息，便于前端快速渲染列表。
    """

    # 身份字段
    id: str = Field(..., description="Run ID（trace 的根节点 ID）")
    trace_id: str = Field(..., description="Trace ID")

    # 描述字段
    name: str = Field(..., description="函数名或展示名")
    run_type: str = Field(..., description="Run 类型")

    # 状态字段
    status: str = Field(..., description="状态：success/error/running")
    error: Optional[str] = Field(None, description="错误信息（如果有）")

    # 时间字段
    start_time: str = Field(..., description="开始时间（UTC ISO 8601）")
    end_time: Optional[str] = Field(None, description="结束时间（UTC ISO 8601）")
    duration_ms: Optional[float] = Field(None, description="耗时（毫秒）")

    # 扩展字段
    tags: list[str] = Field(default_factory=list, description="标签列表")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "trace_id": "550e8400-e29b-41d4-a716-446655440001",
                "name": "process_order",
                "run_type": "chain",
                "status": "success",
                "error": None,
                "start_time": "2026-04-03T10:00:00Z",
                "end_time": "2026-04-03T10:00:02.5Z",
                "duration_ms": 2500.0,
                "tags": ["payment", "critical"],
            }
        },
    )


class TracesListResponse(BaseModel):
    """Trace 分页列表响应

    用于 GET /api/traces 响应体。
    """

    items: list[TraceListItem] = Field(..., description="当前页的 Trace 列表")
    total: int = Field(..., description="总记录数")
    page: int = Field(..., description="当前页码（从 1 开始）")
    page_size: int = Field(..., description="每页大小")
    total_pages: int = Field(..., description="总页数")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": "run-1",
                        "trace_id": "trace-1",
                        "name": "main_task",
                        "run_type": "chain",
                        "status": "success",
                        "error": None,
                        "start_time": "2026-04-03T10:00:00Z",
                        "end_time": "2026-04-03T10:00:02Z",
                        "duration_ms": 2000.0,
                        "tags": ["production"],
                    }
                ],
                "total": 100,
                "page": 1,
                "page_size": 50,
                "total_pages": 2,
            }
        },
    )


class TraceTreeNode(BaseModel):
    """Trace 树形节点（递归结构）

    用于 GET /api/traces/{trace_id} 响应体。
    这是前端 P2.2 TypeScript 类型的对齐基准。

    重要：这个 schema 定义了树形 JSON 的递归结构：
      - 每个节点包含完整的 Run 数据
      - children 字段包含子节点列表（递归同结构）
      - 叶子节点的 children 为空列表
    """

    # --- 身份字段 ---
    id: str = Field(..., description="Run 的全局唯一 ID")
    trace_id: str = Field(..., description="顶层调用链的 ID")
    parent_run_id: Optional[str] = Field(None, description="父 Run 的 ID")

    # --- 描述字段 ---
    name: str = Field(..., description="函数名或展示名")
    run_type: str = Field(..., description="Run 类型")

    # --- 数据字段 ---
    inputs: dict[str, Any] = Field(default_factory=dict, description="函数入参")
    outputs: Optional[dict[str, Any]] = Field(None, description="函数返回值")
    error: Optional[str] = Field(None, description="异常信息")

    # --- 时间字段 ---
    start_time: str = Field(..., description="开始时间（UTC ISO 8601）")
    end_time: Optional[str] = Field(None, description="结束时间（UTC ISO 8601）")

    # --- 扩展字段 ---
    metadata: dict[str, Any] = Field(default_factory=dict, description="用户自定义键值对")
    tags: list[str] = Field(default_factory=list, description="标签列表")

    # --- 排序字段 ---
    exec_order: int = Field(default=0, description="同一父节点下的创建顺序")

    # --- 计算字段 ---
    @computed_field
    @property
    def duration_ms(self) -> Optional[float]:
        """计算耗时（毫秒）"""
        if self.start_time and self.end_time:
            try:
                start = datetime.fromisoformat(self.start_time.replace('Z', '+00:00'))
                end = datetime.fromisoformat(self.end_time.replace('Z', '+00:00'))
                return (end - start).total_seconds() * 1000
            except (ValueError, AttributeError):
                return None
        return None

    @computed_field
    @property
    def status(self) -> str:
        """计算状态：success/error/running"""
        if self.error:
            return "error"
        elif self.end_time:
            return "success"
        else:
            return "running"

    # --- 树形结构：子节点列表（递归） ---
    children: list["TraceTreeNode"] = Field(
        default_factory=list,
        description="子节点列表（递归结构）",
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "run-root",
                "trace_id": "trace-1",
                "parent_run_id": None,
                "name": "main_task",
                "run_type": "chain",
                "inputs": {"arg": "value"},
                "outputs": {"result": "success"},
                "error": None,
                "start_time": "2026-04-03T10:00:00Z",
                "end_time": "2026-04-03T10:00:02Z",
                "metadata": {},
                "tags": ["production"],
                "exec_order": 0,
                "duration_ms": 2000.0,
                "status": "success",
                "children": [
                    {
                        "id": "run-child-1",
                        "trace_id": "trace-1",
                        "parent_run_id": "run-root",
                        "name": "sub_task_1",
                        "run_type": "tool",
                        "inputs": {},
                        "outputs": {},
                        "error": None,
                        "start_time": "2026-04-03T10:00:00.5Z",
                        "end_time": "2026-04-03T10:00:01Z",
                        "metadata": {},
                        "tags": [],
                        "exec_order": 0,
                        "duration_ms": 500.0,
                        "status": "success",
                        "children": [],
                    }
                ],
            }
        },
    )
