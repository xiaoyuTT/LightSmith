# LightSmith

> 🔍 仿 LangSmith 的可观测性工具  
> **装饰器插桩 · 调用树追踪 · Web UI 可视化**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-brightgreen.svg)](https://www.docker.com/)

---

## 目录

- [简介](#简介)
- [特性](#特性)
- [快速开始](#快速开始)
- [架构](#架构)
- [开发进度](#开发进度)
- [文档](#文档)
- [技术栈](#技术栈)

---

## 简介

LightSmith 是一个轻量级的 AI 应用可观测性工具，专注于**调用链追踪**和**性能分析**。

### 核心能力

- **零侵入追踪**：通过 `@traceable` 装饰器自动记录函数调用
- **树形可视化**：完整复现调用关系和执行顺序
- **批量上报**：SDK 自动批量上报到后端（100 条 / 5s 触发）
- **Docker 一键部署**：`docker-compose up -d` 即可启动后端 + PostgreSQL

### 适用场景

- **LLM 应用调试**：追踪 Agent 调用链、Token 消耗、耗时分析
- **分布式任务监控**：多个 Tool 并发调用的执行顺序和依赖关系
- **性能瓶颈定位**：快速找到慢节点（耗时 > 1s 的函数）
- **错误溯源**：异常堆栈 + 调用上下文一目了然

---

## 特性

### SDK（Python）

- ✅ **装饰器插桩**：`@traceable` 自动记录函数的输入、输出、耗时、错误
- ✅ **异步支持**：自动识别 `async def`，无需区分同步/异步
- ✅ **上下文管理**：基于 `contextvars` 实现线程安全 + asyncio 协程安全
- ✅ **批量上报**：内存队列 + 双触发机制（满 100 条 或 5s）
- ✅ **离线 fallback**：`LIGHTSMITH_LOCAL=true` 自动切换到本地 SQLite

### 后端（FastAPI）

- ✅ **Run 摄入 API**：`POST /api/runs/batch` 批量接收 SDK 上报
- ✅ **Trace 查询 API**：`GET /api/traces` 分页列表 + `GET /api/traces/{id}` 树形 JSON
- ✅ **数据库支持**：PostgreSQL（生产） / SQLite（开发）
- ✅ **Docker 化**：多阶段构建，最终镜像 ~180MB
- ✅ **健康检查**：`/health` 端点，支持容器编排（Swarm / Kubernetes）

### 前端（React + TypeScript）

- ⏳ **Trace 列表页**：分页、过滤（run_type、tags、时间范围）（P2.3）
- ⏳ **追踪树详情页**：递归渲染、展开/折叠、节点详情面板（P2.4）
- ⏳ **甘特图视图**：时间轴可视化（P3.4）

---

## 快速开始

### 方式 1：Docker（推荐）

#### 1. 启动后端服务

```bash
# 克隆仓库
git clone https://github.com/your-username/LightSmith.git
cd LightSmith

# 配置环境变量（可选，使用默认配置可跳过）
cp .env.example .env
vim .env  # 根据需要修改配置

# 启动服务（后端 + PostgreSQL）
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f backend
```

#### 2. 安装 Python SDK

```bash
cd sdk
pip install -e .
```

#### 3. 编写追踪代码

```python
import lightsmith as ls

# 初始化 HTTP Transport（使用默认配置）
# 默认连接到 http://localhost:8000
ls.init_http_transport()

# 或显式指定后端地址
# ls.init_http_transport(endpoint="http://localhost:8000")

# 使用 @traceable 装饰器
@ls.traceable(name="process_order", run_type="chain", tags=["production"])
def process_order(order_id):
    user = fetch_user(order_id)
    result = calculate_price(user)
    return result

@ls.traceable(name="fetch_user", run_type="tool")
def fetch_user(order_id):
    return {"user_id": 123, "name": "Alice"}

@ls.traceable(name="calculate_price", run_type="llm")
def calculate_price(user):
    return {"price": 99.99}

# 调用函数（自动上报到后端）
result = process_order("order-001")
print(result)
```

#### 4. 查看追踪数据

```bash
# 查看 Trace 列表
curl http://localhost:8000/api/traces

# 查看 Swagger UI（交互式 API 文档）
open http://localhost:8000/api/docs

# 或运行端到端测试脚本
python tests/e2e/test_docker_e2e.py
```

### 方式 2：本地开发

#### 1. 启动 PostgreSQL

```bash
# macOS / Linux
brew install postgresql
createdb lightsmith

# 或使用 Docker
docker run -d \
  --name lightsmith-postgres \
  -e POSTGRES_USER=lightsmith \
  -e POSTGRES_PASSWORD=lightsmith \
  -e POSTGRES_DB=lightsmith \
  -p 5432:5432 \
  postgres:16-alpine
```

#### 2. 启动后端服务

```bash
cd backend

# 安装依赖
pip install -e ".[dev]"

# 配置环境变量（使用本地开发专用配置）
cp .env.example .env
vim .env  # 修改 LIGHTSMITH_DATABASE_URL 为 localhost:5432

# 运行数据库迁移
alembic upgrade head

# 启动服务
uvicorn app.main:app --reload --port 8000
```

#### 3. 安装 SDK 并测试

```bash
cd ../sdk
pip install -e .

# 运行示例脚本
python examples/http_example.py
```

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                         用户代码                              │
│  @traceable 装饰器自动记录函数调用（输入、输出、耗时、错误）    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │   LightSmith SDK      │
         │   (Python Package)    │
         │                       │
         │  · BatchBuffer        │  ← 内存队列（100 条 / 5s）
         │  · HttpClient         │  ← HTTP 上报 + 重试
         │  · atexit 钩子        │  ← 进程退出时 flush
         └───────────┬───────────┘
                     │
                     │ POST /api/runs/batch
                     ▼
         ┌───────────────────────┐
         │   LightSmith Backend  │
         │   (FastAPI)           │
         │                       │
         │  · Run 摄入 API       │
         │  · Trace 查询 API     │
         │  · 健康检查           │
         └───────────┬───────────┘
                     │
                     │ SQLAlchemy ORM
                     ▼
         ┌───────────────────────┐
         │   PostgreSQL          │
         │   (数据持久化)        │
         │                       │
         │  · runs 表            │
         │  · 索引（trace_id）   │
         └───────────────────────┘
                     │
                     │ GET /api/traces
                     ▼
         ┌───────────────────────┐
         │   React 前端          │
         │   (P2 阶段)           │
         │                       │
         │  · Trace 列表页       │
         │  · 追踪树详情页       │
         └───────────────────────┘
```

---

## 开发进度

### ✅ P0 · SDK 核心层（已完成）

- [√] P0.1 基础数据模型（Run dataclass、RunType 枚举）
- [√] P0.2 上下文管理器（调用树核心、线程安全 + asyncio 安全）
- [√] P0.3 `@traceable` 装饰器（同步/异步自动识别）
- [√] P0.4 本地存储（SQLite Writer）
- [√] P0.5 CLI 树打印工具
- [-] P0.6 `wrap_openai` SDK 包装器（暂不实现）

**测试覆盖**：131 个测试用例全部通过

### ✅ P1 · 后端服务层（已完成）

- [√] P1.1 项目脚手架（FastAPI + SQLAlchemy + Alembic + pydantic-settings）
- [√] P1.2 数据库层（ORM 模型、RunRepository、Alembic 迁移）
- [√] P1.3 Run 摄入 API（`POST /api/runs/batch`、幂等性、输入验证）
- [√] P1.4 Trace 查询 API（`GET /api/traces`、树形 JSON）
- [√] P1.5 SDK HTTP Transport 层（BatchBuffer、HttpClient、atexit 钩子）
- [√] P1.6 Docker 化（Dockerfile、docker-compose.yml、健康检查）

**测试覆盖**：58 个单元测试 + 5 个端到端测试场景

### ⏳ P2 · 前端 UI 层（待开始）

- [ ] P2.1 项目脚手架（Vite + React + TypeScript + Tailwind CSS）
- [ ] P2.2 API 客户端层（TypeScript 类型与后端 schema 对齐）
- [ ] P2.3 Trace 列表页（分页、过滤、跳转）
- [ ] P2.4 追踪树详情页（递归渲染、展开/折叠、详情面板）
- [ ] P2.5 整体 UI 布局（顶栏、空状态页、Loading 骨架屏）

### ⏳ P3 · 完善打磨（待开始）

- [ ] P3.1 搜索与高级过滤
- [ ] P3.2 API Key 鉴权（轻量版）
- [ ] P3.3 前端 Docker 化
- [ ] P3.4 时间轴甘特图
- [ ] P3.5 SDK 接入文档

### ⏳ P4 · 进阶功能（可选）

- [ ] Token 成本估算
- [ ] Trace 对比
- [ ] Webhook 通知
- [ ] 数据导出（JSON / CSV）
- [ ] Prometheus metrics 端点
- [ ] TypeScript SDK

---

## 文档

- **[PLAN.md](./PLAN.md)** - 项目整体计划（路线图、技术栈、测试规范）
- **[execute/EXECUTE_P1.md](./execute/EXECUTE_P1.md)** - P1 阶段开发日志（详细设计和实现）
- **[backend/README.md](./backend/README.md)** - 后端服务文档
- **[sdk/README.md](./sdk/README.md)** - SDK 使用文档（待完善）
- **API 文档** - http://localhost:8000/api/docs（FastAPI 自动生成）

---

## 技术栈

### SDK

- **Python 3.11+**
- **contextvars**（上下文管理）
- **threading**（BatchBuffer 定时器）
- **urllib.request**（HTTP 客户端，标准库无额外依赖）
- **SQLite**（离线 fallback）

### 后端

- **FastAPI 0.115+**（Web 框架）
- **Uvicorn**（ASGI 服务器）
- **SQLAlchemy 2.0+**（ORM）
- **Alembic**（数据库迁移）
- **pydantic-settings**（配置管理）
- **PostgreSQL**（生产数据库）

### 前端（P2 阶段）

- **React 18**（UI 框架）
- **TypeScript**（类型安全）
- **Vite**（构建工具）
- **Tailwind CSS + shadcn/ui**（样式和组件）
- **react-router-dom**（路由）

### 基础设施

- **Docker + Docker Compose**（容器化）
- **PostgreSQL 16**（数据库）
- **pytest**（单元测试）
- **httpx**（API 集成测试）

---

## 快速命令参考

```bash
# ========== Docker 部署 ==========
docker-compose up -d          # 启动服务
docker-compose down           # 停止服务
docker-compose logs -f        # 查看日志
docker-compose ps             # 查看状态

# ========== 数据库操作 ==========
# 进入 PostgreSQL 容器
docker-compose exec postgres psql -U lightsmith -d lightsmith

# 查询最近的 Traces
SELECT trace_id, name, run_type, start_time 
FROM runs 
WHERE parent_run_id IS NULL 
ORDER BY start_time DESC 
LIMIT 10;

# ========== 后端开发 ==========
cd backend
uvicorn app.main:app --reload --port 8000  # 启动服务
alembic upgrade head                        # 应用迁移
alembic revision -m "your description"      # 创建迁移
pytest tests/                               # 运行测试

# ========== SDK 开发 ==========
cd sdk
pip install -e ".[dev]"                     # 安装开发依赖
pytest tests/                               # 运行测试
python examples/http_example.py             # 运行示例

# ========== 端到端测试 ==========
python tests/e2e/test_docker_e2e.py         # 验证完整流程
```

---

## 常见问题

### Q: 如何配置 SDK 连接到后端？

**方式 1：使用默认配置（推荐）**
```python
import lightsmith as ls
ls.init_http_transport()  # 默认连接到 http://localhost:8000
```

**方式 2：显式指定后端地址**
```python
import lightsmith as ls
ls.init_http_transport(endpoint="http://your-backend:8000")
```

**方式 3：使用环境变量**
```bash
# 在 shell 中设置（Linux/macOS）
export LIGHTSMITH_ENDPOINT=http://localhost:8000
export LIGHTSMITH_API_KEY=your-api-key  # 可选，P3.2 启用

# Windows PowerShell
$env:LIGHTSMITH_ENDPOINT = "http://localhost:8000"

# 然后在代码中
python your_app.py
```

```python
# 或在代码中设置
import os
os.environ["LIGHTSMITH_ENDPOINT"] = "http://localhost:8000"

import lightsmith as ls
ls.init_http_transport()  # 会读取环境变量
```

### Q: 如何切换本地 SQLite 模式？

```python
# 方式 1：使用 init_local_storage
import lightsmith as ls
ls.init_local_storage()  # 使用本地 SQLite

# 方式 2：使用 init_auto（根据环境变量自动选择）
import os
os.environ["LIGHTSMITH_LOCAL"] = "true"

import lightsmith as ls
ls.init_auto()  # 自动选择 SQLite 模式
```

### Q: 如何修改批量上报大小？

```python
ls.init_http_transport(
    max_batch_size=50,      # 批量大小（默认 100）
    flush_interval=3.0,     # 定时 flush 间隔（秒，默认 5.0）
)
```

### Q: Docker 容器无法启动？

```bash
# 1. 查看日志
docker-compose logs backend
docker-compose logs postgres

# 2. 检查端口占用
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# 3. 清理资源
docker-compose down -v
docker system prune -a
```

### Q: 如何备份 PostgreSQL 数据？

```bash
# 导出备份
docker-compose exec -T postgres pg_dump -U lightsmith -d lightsmith \
  | gzip > backup_$(date +%Y%m%d).sql.gz

# 恢复备份
gunzip < backup_20260405.sql.gz | \
  docker-compose exec -T postgres psql -U lightsmith -d lightsmith
```

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

**开发流程**：
1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交代码：`git commit -m "feat: add your feature"`
4. 推送分支：`git push origin feature/your-feature`
5. 提交 Pull Request

**代码规范**：
- Python 代码使用 `black` 格式化（line-length 100）
- TypeScript 代码使用 `prettier` 格式化
- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/)

---

## 许可证

[MIT License](./LICENSE)

---

## 致谢

本项目设计灵感来自 [LangSmith](https://www.langchain.com/langsmith)。

---

*最后更新：2026-04-05*
