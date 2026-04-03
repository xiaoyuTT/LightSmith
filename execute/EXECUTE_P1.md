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

### 关键决策

**配置管理：pydantic-settings**

```python
class Settings(BaseSettings):
    database_url: str = Field(default="postgresql://...")
    port: int = Field(default=8000, ge=1, le=65535)
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LIGHTSMITH_",  # 自动映射环境变量
    )
    
    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not (v.startswith("postgresql://") or v.startswith("sqlite://")):
            raise ValueError("database_url 必须以 postgresql:// 或 sqlite:// 开头")
        return v
```

优势：类型验证、环境变量自动映射、启动时配置校验、单例模式。

**SQLAlchemy 引擎和会话工厂**

核心概念：

- **Engine（引擎）**：管理数据库连接池，复用连接而非每次新建（性能优化：300ms → 10ms）
- **SessionLocal（会话工厂）**：生产独立会话（Session），每个请求一个会话，避免数据混乱
- **Session（会话）**：类似"工作台"，操作先在内存中进行，`commit()` 统一提交

```python
# SQLite / PostgreSQL 分支配置
if settings.is_sqlite:
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_size=10,
        max_overflow=20,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
```

**FastAPI 依赖注入：get_db**

```python
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db  # 暂停并返回 db，函数还活着
    finally:
        db.close()  # 路由函数返回后，继续执行这里

@app.get("/api/traces")
def list_traces(db: Session = Depends(get_db)):
    # FastAPI 自动调用 get_db()，请求结束后自动 close
    ...
```

**关键**：`yield` 让函数成为生成器，可"暂停-恢复"，确保 `finally` 块一定执行（异常安全）。

依赖注入优势：自动资源管理（防止连接泄漏）、异常安全、代码简洁、可测试性（`app.dependency_overrides` 替换依赖）。

**models 和 db 的分层架构**

```
【db/base.py】基础设施层
    ├─ Base（ORM 基类，元数据注册表）
    ├─ engine（连接池）
    ├─ SessionLocal（会话工厂）
    └─ get_db()（依赖注入）
        ↓
【models/run.py】模型层
    └─ class Run(Base)（继承 Base，数据结构定义）
        ↓
【db/repository.py】数据访问层
    └─ RunRepository（CRUD 封装、业务逻辑）
        ↓
【routers/*.py】路由层
    └─ API 端点（调用 Repository）
```

职责分离：
- `db/base.py` - "怎么连"：连接管理、会话生命周期
- `models/run.py` - "是什么"：数据结构、字段约束
- `db/repository.py` - "怎么用"：CRUD 操作、复杂查询

**Base.metadata 的作用**：
- 记录所有继承 Base 的模型类及表结构
- Alembic 通过对比 `Base.metadata` 和数据库实际结构生成迁移脚本
- 导入顺序重要：先创建 Base，再定义模型（`class Run(Base)`）

**对象生命周期**：

| 对象 | 作用域 | 何时创建 |
|------|-------|---------|
| **Base, engine, SessionLocal** | 全局单例 | 模块导入时（应用启动） |
| **Session** | 请求作用域 | 请求开始（`SessionLocal()`） |
| **Run 对象** | 查询结果 | 执行查询时（`db.query(Run).all()`） |

**Alembic 配置集成**

```python
# alembic/env.py
from app.config import get_settings
from app.models import Run  # 必须导入，触发模型注册

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata  # Alembic 读取这个生成迁移
```

### 项目结构

```
backend/
├── app/
│   ├── config.py            # pydantic-settings 配置
│   ├── main.py              # FastAPI 入口（lifespan、CORS）
│   ├── db/
│   │   ├── base.py          # Engine、SessionLocal、Base、get_db
│   │   └── repository.py    # RunRepository（P1.2）
│   ├── models/
│   │   └── run.py           # Run ORM 模型（P1.2）
│   ├── schemas/             # Pydantic schema（P1.3-P1.4）
│   └── routers/             # API 路由（P1.3-P1.4）
├── alembic/
│   ├── env.py               # 迁移配置（集成 pydantic-settings）
│   └── versions/            # 迁移脚本
├── tests/
├── .env.example
├── alembic.ini
└── pyproject.toml
```

### 依赖清单

**核心**：`fastapi` (>=0.115.0), `uvicorn[standard]` (>=0.30.0), `sqlalchemy` (>=2.0.0), `alembic` (>=1.13.0), `pydantic-settings` (>=2.5.0), `psycopg2-binary` (>=2.9.9)

**开发**：`pytest`, `pytest-asyncio`, `httpx`, `black`, `ruff`

### 快速启动

```bash
# 1. 安装依赖
cd backend && pip install -e ".[dev]"

# 2. 配置环境
cp .env.example .env  # 编辑 LIGHTSMITH_DATABASE_URL

# 3. 初始化数据库
createdb lightsmith  # PostgreSQL
alembic upgrade head

# 4. 启动服务
uvicorn app.main:app --reload --port 8000
```

访问：http://localhost:8000/api/docs

### 遗留 / 待注意

- **SQLite 引擎配置 bug**：P1.1 中 `pool_size=None` 导致 TypeError，已在 P1.2 修复
- **CORS 配置**：默认允许 `localhost:3000`（React）和 `localhost:5173`（Vite），生产环境需修改
- **日志系统**：当前使用 `print`，P3 可考虑 `structlog` 或 `loguru`

### P1.1 检查点

- [√] pydantic-settings 配置管理（类型验证、环境变量映射）
- [√] FastAPI 应用（lifespan、CORS、健康检查）
- [√] SQLAlchemy 引擎和会话工厂（SQLite/PostgreSQL 双支持）
- [√] Alembic 迁移环境配置
- [√] 依赖注入模式（`get_db`）
- [√] 分层架构设计（db/models/repository 职责分离）

---

## P1.2 数据库层（SQLAlchemy）

**完成时间**：2026-04-03
**状态**：[√] 已完成

### 完成内容

| 任务 | 产出文件 |
|------|---------|
| SQLAlchemy ORM Run 模型 | `backend/app/models/run.py` |
| RunRepository 数据访问层 | `backend/app/db/repository.py` |
| Alembic 初始迁移脚本 | `backend/alembic/versions/cdb5bf900e44_*.py` |
| 单元测试（11 个通过） | `backend/tests/test_repository.py` |

### 关键决策

**ORM 模型设计**

与 P0.1 SDK Run dataclass 字段一一对应：

```python
class Run(Base):
    __tablename__ = "runs"
    
    # 身份字段
    id = Column(String(36), primary_key=True)
    trace_id = Column(String(36), nullable=False, index=True)
    parent_run_id = Column(String(36), nullable=True, index=True)
    
    # 描述字段
    name = Column(String(255), nullable=False)
    run_type = Column(String(20), nullable=False)
    
    # 数据字段（JSON 存储）
    inputs = Column(JSON, nullable=False, default={})
    outputs = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    
    # 时间字段（ISO 8601 字符串）
    start_time = Column(String(32), nullable=False, index=True)
    end_time = Column(String(32), nullable=True)
    
    # 扩展字段（JSON 存储）
    run_metadata = Column("metadata", JSON, nullable=False, default={})  # ← 避免 SQLAlchemy 保留字冲突
    tags = Column(JSON, nullable=False, default=[])
    
    # 排序字段
    exec_order = Column(Integer, nullable=False, default=0)
```

关键点：
- **JSON 类型**：SQLite 和 PostgreSQL 都支持
- **时间存储**：ISO 8601 字符串（与 SDK 一致），避免时区问题
- **索引**：trace_id（高频查询）、parent_run_id（树重建）、start_time（时间过滤）
- **metadata 字段**：Python 中命名为 `run_metadata`，数据库列名为 `metadata`

**Repository 设计**

```python
class RunRepository:
    def __init__(self, db: Session):
        self.db = db
    
    # 批量保存（幂等性）
    def save_batch(self, runs: list[Run]) -> dict[str, int]:
        # SQLite: INSERT OR IGNORE
        # PostgreSQL: ON CONFLICT DO NOTHING
        ...
    
    # 查询
    def get_run_by_id(self, run_id: str) -> Optional[Run]
    def get_trace(self, trace_id: str) -> list[Run]  # 按 exec_order 排序
    
    # 分页查询（支持多种过滤）
    def list_traces(
        self, page=1, page_size=50,
        run_type=None, tags=None, has_error=None,
        start_after=None, start_before=None
    ) -> dict  # {"items": [...], "total": N, "page": M, "page_size": K, "total_pages": P}
    
    # 统计
    def count_traces(self) -> int  # 根 Run 数量
    def count_runs(self) -> int    # 所有 Run 数量
```

**幂等性实现**

使用数据库原生能力，避免并发 race condition：

```python
if self.settings.is_sqlite:
    stmt = sqlite_insert(Run).values(...).prefix_with("OR IGNORE")
else:
    stmt = pg_insert(Run).values(...).on_conflict_do_nothing(index_elements=["id"])
```

同一 `run.id` 重复提交时静默忽略，以首次为准。

**Alembic 迁移脚本**

Windows 系统 `alembic revision --autogenerate` 遇到编码问题（UnicodeDecodeError: 'gbk'），手动创建迁移脚本：

```python
# backend/alembic/versions/cdb5bf900e44_initial_migration_create_runs_table.py
def upgrade() -> None:
    op.create_table('runs', ...)
    op.create_index('idx_runs_trace_id', 'runs', ['trace_id'])
    op.create_index('idx_runs_parent_run_id', 'runs', ['parent_run_id'])
    op.create_index('idx_runs_start_time', 'runs', ['start_time'])

def downgrade() -> None:
    op.drop_index('idx_runs_start_time', table_name='runs')
    op.drop_index('idx_runs_parent_run_id', table_name='runs')
    op.drop_index('idx_runs_trace_id', table_name='runs')
    op.drop_table('runs')
```

**测试覆盖**

11 个测试用例全部通过（1.41s）：

| 测试 | 验证内容 |
|------|---------|
| `test_save_batch_success` | 批量保存 |
| `test_save_batch_idempotent` | 幂等性（重复提交不报错） |
| `test_get_run_by_id` | 单条查询 |
| `test_get_trace` | 树查询（exec_order 排序） |
| `test_get_trace_empty` | 查询不存在的 trace |
| `test_list_traces_pagination` | 分页 |
| `test_list_traces_filter_run_type` | run_type 过滤 |
| `test_list_traces_filter_error` | 错误状态过滤 |
| `test_list_traces_filter_time_range` | 时间范围过滤 |
| `test_count_traces` / `test_count_runs` | 统计 |

### 使用示例

```python
@router.post("/api/runs/batch")
def batch_ingest(runs: list[Run], db: Session = Depends(get_db)):
    repo = RunRepository(db)
    return repo.save_batch(runs)  # {"accepted": N, "duplicates": M}

@router.get("/api/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db)):
    repo = RunRepository(db)
    runs = repo.get_trace(trace_id)
    if not runs:
        raise HTTPException(404, "Trace not found")
    return runs  # P1.4 转换为树形 JSON
```

### 遗留 / 待注意

- **duration_gt 过滤**：暂未实现，需在 P1.4 API 层计算耗时后过滤
- **tags 过滤性能**：大数据量下可考虑 PostgreSQL GIN 索引或 SQLite 关联表
- **Alembic 编码问题**：Windows 上无法自动生成，后续迁移可在 Linux/Mac 生成
- **PostgreSQL 测试**：当前仅测试 SQLite，PostgreSQL 行为需集成测试验证
- **run_metadata 命名**：API 层需转换回 `metadata`（P1.3-P1.4 实现 Pydantic schema 时处理）

### P1.2 检查点

- [√] ORM 模型（与 SDK dataclass 对齐）
- [√] RunRepository（save_batch、get_trace、list_traces、幂等性）
- [√] Alembic 迁移脚本（创建表和索引）
- [√] 单元测试（11 个全部通过）
- [√] SQLite/PostgreSQL 双支持（引擎配置优化）
- [√] metadata 字段冲突解决

**P1.2 阶段完成总结**：
- ✅ ORM 模型与 SDK 完全对齐
- ✅ Repository 封装完善（批量保存、树查询、分页、统计）
- ✅ 幂等性保证（数据库层原子操作）
- ✅ 测试覆盖充分
- ✅ 数据库迁移就绪
- ✅ 为 P1.3-P1.4 API 层提供完整数据访问能力

---
