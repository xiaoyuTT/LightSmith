"""
config.py — 配置管理（基于 pydantic-settings）

从环境变量读取配置，提供默认值和验证。
"""

from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置（从环境变量加载）"""

    # 服务配置
    app_name: str = Field(default="LightSmith Backend", description="应用名称")
    app_version: str = Field(default="0.1.0", description="应用版本")
    debug: bool = Field(default=False, description="调试模式")
    host: str = Field(default="0.0.0.0", description="绑定地址")
    port: int = Field(default=8000, description="监听端口")

    # 数据库配置
    database_url: str = Field(
        default="postgresql://lightsmith:lightsmith@localhost:5432/lightsmith",
        description="数据库连接 URL（支持 SQLite/PostgreSQL）",
    )

    # API 配置
    api_prefix: str = Field(default="/api", description="API 路由前缀")
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        description="允许的 CORS 源",
    )

    # 分页默认值
    default_page_size: int = Field(default=50, description="默认分页大小", ge=1, le=1000)
    max_page_size: int = Field(default=1000, description="最大分页大小", ge=1, le=10000)

    # 批量摄入限制
    max_batch_size: int = Field(default=1000, description="单次批量摄入最大 Run 数量", ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # 环境变量前缀（LIGHTSMITH_DATABASE_URL 映射到 database_url）
        env_prefix="LIGHTSMITH_",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """验证数据库 URL 格式"""
        if not (v.startswith("postgresql://") or v.startswith("sqlite://")):
            raise ValueError(
                "database_url 必须以 postgresql:// 或 sqlite:// 开头"
            )
        return v

    @property
    def is_sqlite(self) -> bool:
        """判断是否使用 SQLite"""
        return self.database_url.startswith("sqlite://")

    @property
    def is_postgresql(self) -> bool:
        """判断是否使用 PostgreSQL"""
        return self.database_url.startswith("postgresql://")


# 全局配置实例（延迟初始化，避免导入时读取环境变量）
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取配置实例（单例模式）"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
