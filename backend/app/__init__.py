"""
LightSmith Backend — FastAPI 后端服务

提供以下功能：
  - Run 批量摄入 API (POST /api/runs/batch)
  - Trace 查询 API (GET /api/traces, GET /api/traces/{trace_id})
  - PostgreSQL 持久化存储
  - Alembic 数据库迁移
"""

__version__ = "0.1.0"
