"""
run.py — Run ORM 模型

SQLAlchemy ORM 映射，与 P0.1 sdk/lightsmith/models.py 中的 Run dataclass 对齐。
支持 SQLite 和 PostgreSQL（JSON 类型在两者中都可用）。
"""

from sqlalchemy import Column, String, Integer, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy import JSON

from app.db.base import Base


class Run(Base):
    """Run ORM 模型 - 表示一次被追踪的函数调用记录

    字段命名和语义与 SDK 中的 Run dataclass 保持一致，支持无缝转换。

    Schema 设计：
    - JSON 字段使用 SQLAlchemy 的 JSON 类型（SQLite 和 PostgreSQL 都支持）
    - inputs/outputs/metadata 存储为 JSON 对象
    - tags 存储为 JSON 数组
    - 时间字段使用 ISO 8601 字符串（与 SDK 保持一致，便于序列化）

    索引策略：
    - trace_id: 高频查询（按 trace 查询整棵树）
    - parent_run_id: 用于树结构重建
    - start_time: 用于时间范围过滤和排序
    """

    __tablename__ = "runs"

    # --- 身份字段 ---
    id = Column(String(36), primary_key=True, comment="Run 的全局唯一 ID (UUID4)")
    trace_id = Column(String(36), nullable=False, index=True, comment="顶层调用链的 ID")
    parent_run_id = Column(String(36), nullable=True, index=True, comment="父 Run 的 ID，顶层为 NULL")

    # --- 描述字段 ---
    name = Column(String(255), nullable=False, comment="函数名或展示名")
    run_type = Column(String(20), nullable=False, comment="Run 类型：chain/llm/tool/agent/custom")

    # --- 数据字段（JSON 存储）---
    inputs = Column(JSON, nullable=False, default={}, comment="函数入参的 JSON 快照")
    outputs = Column(JSON, nullable=True, comment="函数返回值的 JSON 快照")

    # --- 错误信息 ---
    error = Column(Text, nullable=True, comment="异常信息：ExcType + message + traceback")

    # --- 时间字段（ISO 8601 字符串）---
    start_time = Column(String(32), nullable=False, index=True, comment="创建时间 (UTC ISO 8601)")
    end_time = Column(String(32), nullable=True, comment="结束时间 (UTC ISO 8601)")

    # --- 扩展字段（JSON 存储）---
    # 注意：metadata 是 SQLAlchemy 保留字，使用 run_metadata 作为列名
    run_metadata = Column("metadata", JSON, nullable=False, default={}, comment="用户自定义键值对")
    tags = Column(JSON, nullable=False, default=[], comment="字符串标签列表")

    # --- 排序字段 ---
    exec_order = Column(Integer, nullable=False, default=0, comment="同一父节点下的创建顺序")

    # 复合索引（可选优化）
    # __table_args__ = (
    #     Index('idx_runs_trace_order', 'trace_id', 'exec_order'),
    # )

    def __repr__(self) -> str:
        return f"<Run(id={self.id!r}, name={self.name!r}, run_type={self.run_type!r})>"
