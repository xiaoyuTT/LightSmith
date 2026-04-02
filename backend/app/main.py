"""
main.py — FastAPI 应用入口

创建 FastAPI 实例，注册中间件和路由，提供健康检查端点。
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理（启动/关闭钩子）"""
    # 启动时执行
    settings = get_settings()
    print(f"🚀 {settings.app_name} v{settings.app_version} starting...")
    print(f"📊 Database: {settings.database_url.split('@')[-1] if '@' in settings.database_url else settings.database_url}")
    print(f"🌐 CORS origins: {settings.cors_origins}")

    yield

    # 关闭时执行
    print("👋 Shutting down...")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例"""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="LightSmith 后端服务 — 调用追踪数据摄入与查询",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )

    # CORS 中间件（允许前端跨域访问）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 健康检查端点
    @app.get("/health", tags=["Health"])
    async def health_check():
        """健康检查端点（用于 Docker 容器、负载均衡器探活）"""
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
        }

    # TODO P1.3: 注册 /api/runs 路由
    # TODO P1.4: 注册 /api/traces 路由

    return app


# 应用实例（供 uvicorn 使用）
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
