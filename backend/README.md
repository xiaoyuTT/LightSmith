# LightSmith Backend

FastAPI 后端服务，提供调用追踪数据的摄入与查询功能。

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -e ".[dev]"
```

**常见安装问题**：

**问题1：`Multiple top-level packages discovered` 错误**

```
error: Multiple top-level packages discovered in a flat-layout: ['app', 'alembic', 'execute'].
```

**原因**：setuptools 在 `backend/` 目录发现多个顶层目录，不知道该打包哪个。

**解决**：已在 `pyproject.toml` 中配置包发现规则，只打包 `app` 包。如果仍有问题，检查 `pyproject.toml` 是否包含：

```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["app*"]
exclude = ["tests*", "alembic*", "execute*"]
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，修改数据库连接等配置
```

**什么是 `.env.example`？**

`.env.example` 是环境变量配置模板：
- **`.env.example`**：示例配置，提交到 Git（公开、安全）
- **`.env`**：真实配置，不提交到 Git（包含敏感信息如密码）

```bash
# .env.example（模板 - 可以公开）
LIGHTSMITH_DATABASE_URL=postgresql://user:password@localhost:5432/db
#                                     ^^^^ ^^^^^^^^ 示例值

# .env（实际配置 - 保密）
LIGHTSMITH_DATABASE_URL=postgresql://admin:MyReal$ecret@prod.db.com/db
#                                     ^^^^^ ^^^^^^^^^^^^^ 真实密码
```

**为什么这样设计？**
- ✅ 新人克隆项目后，复制模板即可快速配置
- ✅ 真实密码不会泄露到 Git 仓库
- ✅ 团队成员知道需要配置哪些环境变量

### 3. 初始化数据库（PostgreSQL）

```bash
# 确保 PostgreSQL 已启动
# 创建数据库（首次）
createdb lightsmith

# 运行数据库迁移
alembic upgrade head
```

### 4. 启动开发服务器

```bash
# 方式 1：使用 uvicorn（推荐）
uvicorn app.main:app --reload --port 8000

# 方式 2：直接运行 main.py
python -m app.main
```

服务启动后访问：
- API 文档：http://localhost:8000/api/docs
- ReDoc 文档：http://localhost:8000/api/redoc
- 健康检查：http://localhost:8000/health

## 项目结构

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 配置管理（pydantic-settings）
│   ├── db/
│   │   ├── base.py          # SQLAlchemy 引擎和会话
│   │   └── __init__.py
│   ├── models/              # SQLAlchemy ORM 模型（P1.2）
│   ├── schemas/             # Pydantic 请求/响应 schema（P1.3-P1.4）
│   └── routers/             # API 路由（P1.3-P1.4）
├── alembic/                 # 数据库迁移脚本
│   ├── env.py               # Alembic 环境配置
│   └── versions/            # 迁移版本（自动生成）
├── tests/                   # 测试套件
├── .env.example             # 环境变量模板
├── alembic.ini              # Alembic 配置
├── pyproject.toml           # 项目配置（现代标准，PEP 621）
└── README.md
```

**注意**：本项目使用现代 Python 打包标准（PEP 621），仅需 `pyproject.toml` 一个配置文件。不需要 `setup.py` 或 `setup.cfg`。

## API 端点

### 健康检查

```bash
GET /health
```

**响应示例**：
```json
{
  "status": "ok",
  "service": "LightSmith Backend",
  "version": "0.1.0"
}
```

### 批量摄入 Run 数据

```bash
POST /api/runs/batch
```

**请求示例**：
```bash
curl -X POST http://localhost:8000/api/runs/batch \
  -H "Content-Type: application/json" \
  -d '{
    "runs": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "trace_id": "550e8400-e29b-41d4-a716-446655440001",
        "parent_run_id": null,
        "name": "process_order",
        "run_type": "chain",
        "inputs": {"order_id": "12345"},
        "outputs": {"status": "success"},
        "error": null,
        "start_time": "2026-04-03T10:00:00Z",
        "end_time": "2026-04-03T10:00:02.5Z",
        "metadata": {"env": "production"},
        "tags": ["payment", "critical"],
        "exec_order": 0
      }
    ]
  }'
```

**响应示例**：
```json
{
  "accepted": 1,
  "duplicates": 0,
  "total": 1
}
```

**字段说明**：

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | Run 的全局唯一 ID（UUID4） |
| `trace_id` | string | ✅ | 顶层调用链的 ID |
| `parent_run_id` | string\|null | ✅ | 父 Run 的 ID，顶层为 null |
| `name` | string | ✅ | 函数名或展示名 |
| `run_type` | string | ✅ | `chain`/`llm`/`tool`/`agent`/`custom` |
| `inputs` | object | ✅ | 函数入参的 JSON 快照 |
| `outputs` | object\|null | ✅ | 函数返回值的 JSON 快照 |
| `error` | string\|null | ✅ | 异常信息 |
| `start_time` | string | ✅ | 创建时间（UTC ISO 8601） |
| `end_time` | string\|null | ✅ | 结束时间（UTC ISO 8601） |
| `metadata` | object | ✅ | 用户自定义键值对 |
| `tags` | array | ✅ | 字符串标签列表 |
| `exec_order` | integer | ✅ | 同一父节点下的创建顺序 |

**特性**：
- ✅ 幂等性保证（重复提交同一 `run.id` 自动忽略）
- ✅ 批量大小限制（默认最多 1000 个 Run）
- ✅ 严格输入验证（Pydantic 自动验证）
- ✅ 错误处理（422 输入错误、500 数据库错误）

### 查询 Traces 列表

```bash
GET /api/traces
```

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `page` | int | 页码（默认 1） |
| `page_size` | int | 每页大小（默认 50，1-1000） |
| `run_type` | string | 过滤 run_type |
| `tags` | string | 过滤 tags（逗号分隔，OR 逻辑） |
| `has_error` | bool | 过滤是否有错误 |
| `start_after` | string | 过滤 start_time ≥ 此时间（ISO 8601） |
| `start_before` | string | 过滤 start_time ≤ 此时间（ISO 8601） |

**请求示例**：
```bash
# 默认查询
curl http://localhost:8000/api/traces

# 分页 + 过滤
curl "http://localhost:8000/api/traces?page=1&page_size=20&run_type=chain"

# 按 tags 过滤
curl "http://localhost:8000/api/traces?tags=production,critical"
```

**响应示例**：
```json
{
  "items": [
    {
      "id": "run-1",
      "trace_id": "trace-1",
      "name": "main_task",
      "run_type": "chain",
      "status": "success",
      "error": null,
      "start_time": "2026-04-03T10:00:00Z",
      "end_time": "2026-04-03T10:00:02Z",
      "duration_ms": 2000.0,
      "tags": ["production"]
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 50,
  "total_pages": 2
}
```

### 获取完整 Trace 树

```bash
GET /api/traces/{trace_id}
```

**请求示例**：
```bash
curl http://localhost:8000/api/traces/trace-1
```

**响应示例**（树形 JSON，递归结构）：
```json
{
  "id": "run-root",
  "trace_id": "trace-1",
  "parent_run_id": null,
  "name": "main_task",
  "run_type": "chain",
  "inputs": {"arg": "value"},
  "outputs": {"result": "success"},
  "error": null,
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
      "name": "sub_task",
      "run_type": "tool",
      "inputs": {},
      "outputs": {},
      "error": null,
      "start_time": "2026-04-03T10:00:00.5Z",
      "end_time": "2026-04-03T10:00:01Z",
      "metadata": {},
      "tags": [],
      "exec_order": 0,
      "duration_ms": 500.0,
      "status": "success",
      "children": []
    }
  ]
}
```

**重要**：这个树形 JSON 结构是前端 TypeScript 类型的对齐基准：
- 每个节点包含完整的 Run 数据
- `children` 字段递归包含子节点
- 叶子节点的 `children` 为空数组
- 子节点按 `exec_order` 排序

### 获取单个 Run

```bash
GET /api/traces/{trace_id}/runs/{run_id}
```

**请求示例**：
```bash
curl http://localhost:8000/api/traces/trace-1/runs/run-1
```

**响应**：单个 Run 的完整数据（RunSchema 格式）

## 开发任务

- [x] P1.1 项目脚手架
- [x] P1.2 数据库层（SQLAlchemy ORM）
- [x] P1.3 Run 摄入 API
- [x] P1.4 Trace 查询 API
- [ ] P1.5 SDK HTTP Transport 层
- [ ] P1.6 Docker 化

## 测试

### 单元测试（pytest）

```bash
# 运行全部测试
python -m pytest tests/ -v

# 详细输出
python -m pytest tests/ -v -s

# 覆盖率报告
python -m pytest tests/ --cov=app --cov-report=html
```

**当前测试覆盖**：
- ✅ 11 个 Repository 测试（数据库层）
- ✅ 13 个 Run API 测试（摄入接口）
- ✅ 15 个 Trace API 测试（查询接口）
- ✅ **总计 39 个测试，全部通过**

### 手动集成测试

```bash
# 启动服务（终端1）
uvicorn app.main:app --reload --port 8000

# 运行手动测试脚本（终端2）
python scripts/test_api.py
```

**说明**：`scripts/test_api.py` 是手动集成测试脚本，使用 `requests` 库测试真实的 HTTP 服务。

## 数据库迁移

```bash
# 生成新迁移（检测 ORM 模型变更）
alembic revision --autogenerate -m "描述变更"

# 执行迁移
alembic upgrade head

# 回滚
alembic downgrade -1

# 查看状态
alembic current
```

## 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `LIGHTSMITH_DATABASE_URL` | `postgresql://...` | 数据库连接 URL |
| `LIGHTSMITH_HOST` | `0.0.0.0` | 绑定地址 |
| `LIGHTSMITH_PORT` | `8000` | 监听端口 |
| `LIGHTSMITH_DEBUG` | `false` | 调试模式 |
| `LIGHTSMITH_CORS_ORIGINS` | `["http://localhost:3000"]` | CORS 允许源 |
| `LIGHTSMITH_MAX_BATCH_SIZE` | `1000` | 批量摄入最大数量 |

完整配置项见 `app/config.py`。

## 验证安装

安装完成后，运行以下命令验证：

```bash
# 验证配置模块
python -c "from app.config import get_settings; s = get_settings(); print(f'✅ Config: {s.app_name}')"

# 验证 FastAPI 应用
python -c "from app.main import app; print(f'✅ FastAPI: {app.title}')"

# 验证数据库连接模块
python -c "from app.db import engine; print(f'✅ Database: {engine.url.drivername}')"
```

## 常见问题

### Q: 为什么使用 `-e` 安装？

`-e` 表示"可编辑模式"（editable），代码修改后无需重新安装即可生效。

**对比**：

| 安装方式 | `pip install .` | `pip install -e .` |
|---------|----------------|-------------------|
| **代码位置** | 复制到 site-packages | 保留在项目目录 |
| **修改代码后** | 需要重新安装 | 重启即可生效 |
| **工作原理** | 物理复制文件 | 创建路径指针 |
| **适用场景** | 生产部署 | 开发调试 |

**什么是"复制到 site-packages"？**

```
普通安装（pip install .）：
───────────────────────────
你的项目目录              Python 的 site-packages 
backend/                  E:\Anaconda\envs\...\site-packages\
  app/                      app/  ← 复制过来的副本
    config.py                 config.py
    main.py                   main.py

修改 backend/app/config.py → site-packages 中的副本不变 → 需要重新安装

可编辑安装（pip install -e .）：
─────────────────────────────
你的项目目录              Python 的 site-packages
backend/                  E:\Anaconda\envs\...\site-packages\
  app/                      lightsmith-backend.egg-link ← 指针文件
    config.py                   ↓
    main.py                 指向 backend/ 目录

修改 backend/app/config.py → Python 直接读取最新代码 → 重启即可生效
```

**开发流程**：
```bash
pip install -e ".[dev]"  # 只需安装一次
# 修改代码 → 重启服务 → 新代码生效（无需重新安装）
```

### Q: psycopg2-binary 安装失败？

Windows 上可能需要 Visual C++ 运行库：

```bash
# 方案1：安装 Visual C++ 可再发行组件包
# 下载：https://aka.ms/vs/17/release/vc_redist.x64.exe

# 方案2：使用预编译的二进制包（已在依赖中）
pip install psycopg2-binary

# 方案3：开发环境使用 SQLite（无需 PostgreSQL 驱动）
# 在 .env 中设置：
# LIGHTSMITH_DATABASE_URL=sqlite:///./lightsmith.db
```

### Q: uvicorn 启动后修改代码不生效？

确保使用 `--reload` 参数：

```bash
uvicorn app.main:app --reload  # 自动检测文件修改并重启
```

注意：
- 修改 `.py` 文件：自动重载 ✅
- 修改 `pyproject.toml` 依赖：需重新 `pip install -e .` ❌
- 修改 `.env` 文件：需手动重启 uvicorn ❌

### Q: `.env` 和 `.env.example` 有什么区别？

| 文件 | 作用 | 内容 | Git 状态 |
|------|------|------|---------|
| `.env.example` | 配置模板 | 示例值、注释 | ✅ 提交到仓库 |
| `.env` | 实际配置 | 真实密码、生产环境配置 | ❌ 不提交（在 .gitignore 中）|

**使用流程**：
```bash
# 1. 克隆项目
git clone <repo-url>
cd backend

# 2. 复制模板
cp .env.example .env

# 3. 修改真实配置
nano .env  # 修改数据库密码等敏感信息

# 4. 启动服务
uvicorn app.main:app --reload
# ✅ 程序读取 .env 中的真实配置
```

**安全性**：
- `.env.example` 提交到 Git，团队共享（无敏感信息）
- `.env` 保留在本地，每个开发者自己配置（有真实密码）
- 防止密码泄露到 GitHub 等公开仓库

### Q: 为什么同时有 `.env.example`、`pyproject.toml` 和 `config.py`？

这三个文件各司其职：

```
pyproject.toml        → 项目元信息（名称、版本、依赖）
  ↓
app/config.py         → 读取环境变量，提供类型验证
  ↓ 读取
.env 文件             → 实际配置值（数据库URL、端口等）
  ↑ 模板
.env.example          → 配置模板（提交到Git）
```

**示例**：
```python
# pyproject.toml - 声明需要 pydantic-settings
dependencies = ["pydantic-settings>=2.5.0"]

# app/config.py - 定义配置结构和验证
class Settings(BaseSettings):
    database_url: str = Field(default="postgresql://...")
    port: int = Field(default=8000, ge=1, le=65535)

# .env - 提供实际值
LIGHTSMITH_DATABASE_URL=postgresql://admin:secret@localhost/db
LIGHTSMITH_PORT=8000
```
