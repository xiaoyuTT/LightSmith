"""
base.py — SQLAlchemy 引擎和会话工厂

创建数据库引擎、会话工厂，提供 FastAPI 依赖注入函数。
"""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

from app.config import get_settings


settings = get_settings()

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    echo=settings.debug,  # SQL 日志输出（调试模式）
    # SQLite 特殊配置
    connect_args={"check_same_thread": False} if settings.is_sqlite else {},
    # PostgreSQL 连接池配置
    pool_size=10 if settings.is_postgresql else None,
    max_overflow=20 if settings.is_postgresql else None,
)

# 会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# ORM Base 类（所有模型继承此类）
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入函数：提供数据库会话

    使用方式：
        @app.get("/api/traces")
        def list_traces(db: Session = Depends(get_db)):
            ...

    会话在请求结束时自动关闭。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
