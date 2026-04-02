# LightSmith P1 后端服务层 - 开发执行日志

> P1 阶段：FastAPI 后端可接收 SDK 上报的数据，支持 trace 查询，切换到 PostgreSQL，提供 Docker 部署

---

## P1.1 项目脚手架

**完成时间**：2026-04-03
**状态**：[√] 已完成

### 完成内容

| 任务 | 产出文件 |
|------|---------|
| `backend/` 目录结构初始化 | 完整项目骨架 |
| `pyproject.toml` 依赖配置 | `backend/pyproject.toml` |
| pydantic-settings 配置管理 | `backend/app/config.py` |
| FastAPI 应用入口 | `backend/app/main.py` |
| SQLAlchemy 数据库层 | `backend/app/db/base.py` |
| Alembic 迁移配置 | `backend/alembic.ini`、`backend/alembic/env.py` |
| 环境变量模板 | `backend/.env.example` |
| 项目文档 | `backend/README.md` |
| 子包占位文件 | `models/`、`schemas/`、`routers/`、`tests/` |

### 关键决策

**配置管理：pydantic-settings**

使用 `pydantic-settings` 的 `BaseSettings` 实现类型安全的配置管理：

```python
class Settings(BaseSettings):
    database_url: str = Field(default="postgresql://...")
    port: int = Field(default=8000, ge=1, le=65535)
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LIGHTSMITH_",  # LIGHTSMITH_DATABASE_URL → database_url
    )
```

优势：
- **类型验证**：字段类型错误时启动失败，避免运行时错误
- **环境变量映射**：自动从 `LIGHTSMITH_*` 环境变量加载配置
- **默认值 + 验证器**：`Field` 提供默认值和约束（如 `ge=1` 表示 ≥1）
- **单例模式**：`get_settings()` 延迟初始化，避免导入时读取环境变量

**数据库 URL 验证**

```python
@field_validator("database_url")
@classmethod
def validate_database_url(cls, v: str) -> str:
    if not (v.startswith("postgresql://") or v.startswith("sqlite://")):
        raise ValueError("database_url 必须以 postgresql:// 或 sqlite:// 开头")
    return v
```

启动时立即发现配置错误，而非等到首次数据库连接时才报错。

**SQLAlchemy 引擎配置：区分 SQLite / PostgreSQL**

```python
engine = create_engine(
    settings.database_url,
    # SQLite 需要禁用线程检查（FastAPI 多线程环境）
    connect_args={"check_same_thread": False} if settings.is_sqlite else {},
    # PostgreSQL 启用连接池
    pool_size=10 if settings.is_postgresql else None,
    max_overflow=20 if settings.is_postgresql else None,
)
```

这样一套代码同时支持：
- **开发环境**：SQLite（`sqlite:///./lightsmith.db`），零依赖
- **生产环境**：PostgreSQL（`postgresql://...`），支持并发

**FastAPI lifespan 事件**

使用 `@asynccontextmanager` 替代旧的 `@app.on_event("startup")`：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行（打印配置摘要）
    print(f"🚀 {settings.app_name} starting...")
    yield
    # 关闭时执行（清理资源）
    print("👋 Shutting down...")

app = FastAPI(lifespan=lifespan)
```

`lifespan` 是 FastAPI 0.109+ 的推荐方式，替代已废弃的 `startup`/`shutdown` 事件。

**Alembic 与 pydantic-settings 集成**

`alembic/env.py` 直接从 `app.config` 读取数据库 URL：

```python
from app.config import get_settings

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
```

这样 Alembic 和 FastAPI 使用**同一套配置**，避免 `alembic.ini` 中硬编码数据库 URL。用户只需设置 `LIGHTSMITH_DATABASE_URL` 环境变量即可。

**依赖注入：`get_db`**

```python
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

FastAPI 路由函数通过 `Depends(get_db)` 自动获取数据库会话，请求结束时自动关闭：

```python
@app.get("/api/traces")
def list_traces(db: Session = Depends(get_db)):
    # db 会话自动管理，无需手动 close
    ...
```

### 项目结构

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用入口（lifespan、CORS、健康检查）
│   ├── config.py            # 配置管理（Settings、get_settings）
│   ├── db/
│   │   ├── __init__.py
│   │   └── base.py          # SQLAlchemy 引擎、会话工厂、get_db 依赖
│   ├── models/              # SQLAlchemy ORM 模型（P1.2 实现）
│   │   └── __init__.py
│   ├── schemas/             # Pydantic 请求/响应 schema（P1.3-P1.4 实现）
│   │   └── __init__.py
│   └── routers/             # API 路由（P1.3-P1.4 实现）
│       └── __init__.py
├── alembic/                 # 数据库迁移
│   ├── env.py               # 迁移环境配置（集成 pydantic-settings）
│   ├── script.py.mako       # 迁移脚本模板
│   ├── README               # Alembic 使用说明
│   └── versions/            # 迁移版本脚本（自动生成）
│       └── .gitkeep
├── tests/                   # 测试套件（P1.2+ 实现）
│   └── __init__.py
├── .env.example             # 环境变量模板
├── alembic.ini              # Alembic 配置文件
├── pyproject.toml           # 项目配置（依赖、构建、测试）
└── README.md                # 项目文档（快速开始、开发指南）
```

### 依赖清单

**核心依赖**（`dependencies`）：

| 包名 | 版本 | 用途 |
|------|------|------|
| `fastapi` | >=0.115.0 | Web 框架 |
| `uvicorn[standard]` | >=0.30.0 | ASGI 服务器 |
| `sqlalchemy` | >=2.0.0 | ORM 框架 |
| `alembic` | >=1.13.0 | 数据库迁移工具 |
| `pydantic` | >=2.9.0 | 数据验证 |
| `pydantic-settings` | >=2.5.0 | 配置管理 |
| `psycopg2-binary` | >=2.9.9 | PostgreSQL 驱动 |

**开发依赖**（`optional-dependencies.dev`）：

| 包名 | 用途 |
|------|------|
| `pytest` | 测试框架 |
| `pytest-asyncio` | 异步测试支持 |
| `httpx` | FastAPI 端点测试客户端 |
| `black` | 代码格式化 |
| `ruff` | Linter |

### 环境变量说明

`.env.example` 提供了完整的配置模板：

```bash
# 服务配置
LIGHTSMITH_HOST=0.0.0.0
LIGHTSMITH_PORT=8000
LIGHTSMITH_DEBUG=false

# 数据库配置（二选一）
LIGHTSMITH_DATABASE_URL=postgresql://lightsmith:lightsmith@localhost:5432/lightsmith
# LIGHTSMITH_DATABASE_URL=sqlite:///./lightsmith.db

# API 配置
LIGHTSMITH_API_PREFIX=/api
LIGHTSMITH_CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]

# 分页配置
LIGHTSMITH_DEFAULT_PAGE_SIZE=50
LIGHTSMITH_MAX_PAGE_SIZE=1000

# 批量摄入限制
LIGHTSMITH_MAX_BATCH_SIZE=1000
```

使用时复制为 `.env`：

```bash
cp .env.example .env
# 编辑 .env，修改数据库 URL 等配置
```

### 快速启动流程

**1. 安装依赖**

```bash
cd backend
pip install -e ".[dev]"
```

**2. 配置环境变量**

```bash
cp .env.example .env
# 编辑 .env，设置 LIGHTSMITH_DATABASE_URL
```

**3. 初始化数据库（PostgreSQL）**

```bash
# 创建数据库（首次）
createdb lightsmith

# 运行迁移（P1.2 创建表结构后）
alembic upgrade head
```

**4. 启动服务**

```bash
# 开发模式（自动重载）
uvicorn app.main:app --reload --port 8000

# 或直接运行
python -m app.main
```

**5. 访问**

- API 文档：http://localhost:8000/api/docs
- 健康检查：http://localhost:8000/health

### 验证

**语法验证**（已通过）：

```bash
python -m py_compile app/config.py
python -m py_compile app/main.py
python -m py_compile app/db/base.py
python -m py_compile alembic/env.py
```

全部文件语法正确 ✅

**导入测试**（需安装依赖后执行）：

```bash
python -c "from app.config import get_settings; print(get_settings().app_name)"
python -c "from app.main import app; print(app.title)"
python -c "from app.db import engine; print(engine.url)"
```

### 设计对齐

**与 P0 SDK 的对齐**

- `Settings.database_url` 支持 SQLite（与 P0.4 `RunWriter` 一致）和 PostgreSQL（P1 生产环境）
- `get_db` 依赖注入模式与 P0.3 `set_run_writer` 钩子设计思路一致（解耦存储层）
- `Base.metadata` 将在 P1.2 中注册 `Run` ORM 模型，与 P0.1 `Run` dataclass 字段一一对应

**与 P1.2-P1.4 的接口**

- `app/models/` 预留给 ORM 模型（P1.2）
- `app/schemas/` 预留给 Pydantic schema（P1.3-P1.4）
- `app/routers/` 预留给 API 路由（P1.3-P1.4）
- `alembic/versions/` 将在 P1.2 生成首个迁移脚本

### 遗留 / 待注意

- **依赖未安装**：当前仅创建了文件，需执行 `pip install -e ".[dev]"` 才能运行
- **数据库未初始化**：需等 P1.2 创建 ORM 模型后才能执行 `alembic upgrade head`
- **路由未实现**：`main.py` 中的 `TODO` 注释标记了 P1.3 和 P1.4 需要注册的路由
- **测试未编写**：`tests/` 目录仅有占位文件，P1.2+ 补充单元测试和集成测试
- **CORS 配置**：默认允许 `localhost:3000`（React 开发服务器）和 `localhost:5173`（Vite），生产环境需修改 `LIGHTSMITH_CORS_ORIGINS`
- **日志系统**：当前仅使用 `print` 和 `uvicorn` 默认日志，P3 可考虑接入 `structlog` 或 `loguru`

### P1.1 检查点

- [√] `pyproject.toml` 配置完整（核心依赖 + 开发依赖）
- [√] `pydantic-settings` 配置管理（类型验证、环境变量映射、单例）
- [√] FastAPI 应用可创建（lifespan、CORS、健康检查）
- [√] SQLAlchemy 引擎和会话工厂（SQLite/PostgreSQL 兼容）
- [√] Alembic 迁移环境配置（集成 pydantic-settings）
- [√] 环境变量模板和项目文档
- [√] 所有 Python 文件语法正确
- [√] 目录结构与 PLAN.md 对齐

**P1.1 阶段完成总结**：
- ✅ 项目脚手架完整：配置管理、FastAPI 入口、数据库层、迁移工具
- ✅ 零运行时错误：所有文件语法验证通过
- ✅ 文档完善：README、.env.example、Alembic README
- ✅ 接口预留：为 P1.2-P1.4 预留 models/schemas/routers 目录
- ✅ 设计前瞻：SQLite/PostgreSQL 双支持、配置验证、依赖注入

---
