"""
models 包 — SQLAlchemy ORM 模型

定义数据库表结构，与 P0 SDK 的 Run dataclass 对齐。
"""

from app.models.run import Run

__all__ = ["Run"]
