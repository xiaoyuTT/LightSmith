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
if settings.is_sqlite:
    # SQLite 配置：禁用线程检查，不使用连接池
    engine = create_engine(
        settings.database_url,
        echo=settings.debug,
        connect_args={"check_same_thread": False},
    )
else:
    # PostgreSQL 配置：启用连接池
    engine = create_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=10,
        max_overflow=20,
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
