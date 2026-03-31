# LightSmith 开发计划

> 仿 LangSmith 的可观测性工具，核心功能：装饰器插桩 / 调用树追踪 / Web UI 可视化
>
> **技术栈**：Python SDK · FastAPI · SQLite→PostgreSQL · React + TypeScript · Docker
>
> **状态标记**：`[ ]` 待开始 · `[~]` 进行中 · `[√]` 已完成 · `[-]` 已跳过/不做

---

## 整体路线图

```
P0 SDK 核心  ──►  P1 后端服务  ──►  P2 前端 UI  ──►  P3 完善打磨  ──►  P4 进阶功能
  (2 周)             (2 周)            (2 周)            (1 周)            (按需)
```

**核心原则**
- P0 不依赖任何网络，SDK 可独立运行并在终端验证
- P1 后端稳定后再接入前端，避免联调拖慢进度
- 每个阶段结束后留 Review 节点，确认设计无误再推进

---

## 项目目录结构

```
LightTrace/                     # 仓库根目录（项目对外名称：LightSmith）
├── sdk/                        # P0 · Python SDK 包
│   ├── lightsmith/
│   │   ├── __init__.py
│   │   ├── models.py           # Run dataclass + RunType 枚举
│   │   ├── context.py          # ContextVar 栈管理
│   │   ├── decorators.py       # @traceable
│   │   ├── storage/
│   │   │   ├── sqlite.py       # 本地 SQLite writer（离线 fallback）
│   │   │   └── http.py         # HTTP transport（P1.5 新增）
│   │   └── integrations/
│   │       └── openai.py       # wrap_openai
│   ├── cli/
│   │   └── tree_printer.py     # P0.5 CLI 工具
│   ├── tests/
│   └── pyproject.toml
├── backend/                    # P1 · FastAPI 后端
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/            # API 路由（runs / traces / auth）
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   ├── schemas/            # Pydantic 请求/响应 schema
│   │   └── db/                 # 数据库连接 + Repository 层
│   ├── alembic/                # 数据库迁移脚本
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/                   # P2 · React 前端
│   ├── src/
│   │   ├── components/         # 通用组件（RunNode、DetailPanel 等）
│   │   ├── pages/              # 路由级页面（TraceList、TraceDetail）
│   │   ├── api/                # API 客户端层（traces.ts）
│   │   └── types/              # TypeScript 类型（与后端 schema 对齐）
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml          # 一键启动后端 + PostgreSQL（P3 加入前端）
├── .env.example                # 环境变量模板
└── PLAN.md
```

---

## 开发环境前置要求

| 工具 | 最低版本 | 用途 |
|------|---------|------|
| Python | 3.11+ | SDK + 后端 |
| Node.js | 20+ | 前端构建 |
| Docker & Docker Compose | 最新稳定版 | 容器化部署 |
| SQLite3 | 系统自带即可 | P0 本地调试 |

---

## 跨阶段接口契约

各阶段结束时须锁定以下接口，后续阶段不得破坏性修改：

**P0 结束前锁定 → `Run` 数据模型**
- `Run` 的全部字段名、类型、序列化格式在 P0.1 确定
- P1.5 HTTP Transport、P1.2 ORM 均以此为基准，不得在 P1 阶段新增/删除字段（只能在 Review 节点统一变更）

**P1 结束前锁定 → REST API 响应 schema**
- `GET /api/traces/{trace_id}` 的树形 JSON schema 在 P1.4 中定义并文档化
- 前端 P2.2 的 TypeScript 类型直接对齐此 schema，不做二次抽象

---

## P0 · SDK 核心层

> **目标**：`@traceable` 装饰器可用，嵌套调用自动建立父子关系，本地 SQLite 存储，CLI 打印追踪树
>
> **验收标准**：写一个 3 层嵌套函数，加上装饰器后能在终端打印出完整的树状调用图，数据已写入 SQLite

### P0.1 基础数据模型

- [√] 定义 `Run` dataclass（id, parent_run_id, trace_id, name, run_type, inputs, outputs, error, start_time, end_time, metadata, tags, exec_order）
- [√] 定义 `RunType` 枚举：`chain / llm / tool / agent / custom`
- [√] 实现 `Run.to_dict()` / `Run.from_dict()` 序列化方法
- [√] 编写单元测试：序列化往返无损

### P0.2 上下文管理器（调用树核心）

- [√] 基于 `contextvars.ContextVar` 实现线程安全的当前 run_id 栈
- [√] 实现 `push_run(run_id)` / `pop_run()` / `get_current_run_id()` 三个操作
- [√] 实现 `exec_order` 赋值：每条 trace 内按兄弟节点创建顺序自增（同一 `parent_run_id` 下从 0 开始计数），存入 `Run`
- [√] 验证异步场景（`asyncio`）下上下文隔离正确（不同协程不互相污染）
- [√] 编写测试：并发 + 异步混用场景

### P0.3 `@traceable` 装饰器

- [√] 实现同步函数包装：进入时创建 Run，退出时记录 outputs 和耗时
- [√] 实现异步函数包装（`async def` 自动识别，不需要用户区分）
- [√] 捕获异常：写入 `run.error`，异常正常向上传播（不吞掉）
- [√] 支持参数：`name`、`run_type`、`metadata`、`tags`
- [√] 实现入参序列化：自动处理不可序列化对象（截断/类型名 fallback）
- [√] 实现 `process_inputs` / `process_outputs` 自定义钩子参数
- [√] 验证嵌套装饰器父子关系自动建立

### P0.4 本地存储（SQLite Writer）

- [√] 设计 SQLite schema（与 P0.1 数据模型对齐）
- [√] 实现同步写入：`RunWriter.save(run: Run)`
- [√] 异步写入：在 async 上下文中用 `loop.run_in_executor` 包装同步写入，避免阻塞事件循环（备选：引入 `aiosqlite`）
- [√] 创建索引：`trace_id`、`parent_run_id`、`start_time`
- [√] 实现树查询：`get_trace(trace_id) -> list[Run]`（一次查询取出整棵树）
- [√] 默认存储路径：`~/.lightsmith/traces.db`，可通过环境变量覆盖

### P0.5 CLI 树打印工具

- [ ] 实现 `tree_printer.py`：从 SQLite 读取一条 trace，格式化打印树
- [ ] 节点行格式：`[run_type 图标] name  耗时ms  [ERROR]`（错误节点红色）
- [ ] 支持 `--trace-id` 参数指定查看某条 trace
- [ ] 支持 `--last` 参数查看最近一条 trace

### P0.6 `wrap_openai` SDK 包装器（可选，P0 末尾）

- [ ] 实现 `wrap_openai(client)` 包装 OpenAI 客户端
- [ ] 自动提取 `model`、`prompt_tokens`、`completion_tokens` 写入 metadata
- [ ] `run_type` 自动设置为 `llm`

### ✅ P0 Review 检查点

- [ ] 3 层嵌套函数 demo 能打印完整树
- [ ] 异步 Agent 场景（多个 tool 并发调用）上下文不混乱
- [ ] 数据库中 `trace_id` / `parent_run_id` 关联正确
- [ ] 装饰器对被装饰函数的性能影响 < 1ms（基准测试）

---

## P1 · 后端服务层

> **目标**：FastAPI 后端可接收 SDK 上报的数据，支持 trace 查询，切换到 PostgreSQL，提供 Docker 部署
>
> **验收标准**：SDK 通过 HTTP 上报，`GET /api/traces` 返回正确的树结构 JSON

### P1.1 项目脚手架

- [ ] 初始化 `backend/` 目录，配置 `pyproject.toml` 依赖（fastapi, uvicorn, sqlalchemy, alembic, pydantic）
- [ ] 配置 `pydantic-settings`：从环境变量读取 DB_URL、PORT 等
- [ ] 配置 Alembic 数据库迁移

### P1.2 数据库层（SQLAlchemy）

- [ ] 将 P0.4 的 SQLite schema 迁移为 SQLAlchemy ORM 模型
- [ ] 实现 `RunRepository`：`save_batch(runs)`、`get_trace(trace_id)`、`list_traces(filters, page, page_size)`
- [ ] 添加 PostgreSQL 支持（环境变量 `DATABASE_URL` 切换）
- [ ] Alembic 初始迁移脚本

### P1.3 Run 摄入 API

- [ ] `POST /api/runs/batch`：接收 `{ "runs": [Run, ...] }` 批量写库
- [ ] 输入校验：Pydantic schema 严格验证
- [ ] 幂等性：同一 `run.id` 重复提交不报错，以首次为准；依赖数据库层实现（SQLite: `INSERT OR IGNORE`，PostgreSQL: `ON CONFLICT DO NOTHING`），避免并发 race condition
- [ ] 返回 `{ "accepted": N, "duplicates": M }`

### P1.4 Trace 查询 API

- [ ] `GET /api/traces`：分页列表，返回根 run 摘要（id, name, duration, status, start_time, tag）
  - 查询参数：`page`、`page_size`、`run_type`、`tags`、`error`、`start_after`、`start_before`、`duration_gt`（ms）
- [ ] `GET /api/traces/{trace_id}`：返回完整树形 JSON（递归嵌套结构，schema：根节点含 `children: Run[]` 字段，子节点递归同结构）；在此任务中定义并文档化该 schema，供前端 P2.2 TypeScript 类型直接对齐
- [ ] `GET /api/runs/{run_id}`：返回单个 Run 完整数据

### P1.5 SDK HTTP Transport 层

> 修改 SDK，将本地 SQLite 写入替换/补充为 HTTP 上报

- [ ] 实现 `BatchBuffer`：内存队列 + 定时 flush（满 100 条 或 5s 触发）
- [ ] 实现 `HttpClient`：向后端 `POST /api/runs/batch`，带重试（最多 3 次，指数退避）
- [ ] 注册 `atexit` 钩子：进程退出时强制 flush 剩余数据（注意：`atexit` 在 asyncio 程序中无法 `await`，需同步阻塞执行；同时注册 `signal.SIGTERM` handler 处理容器/进程被杀情形）
- [ ] 支持配置：`LIGHTSMITH_ENDPOINT`、`LIGHTSMITH_API_KEY`（预留鉴权位）
- [ ] 本地 SQLite 模式保留（离线 fallback，通过 `LIGHTSMITH_LOCAL=true` 启用）

### P1.6 Docker 化

- [ ] 编写 `backend/Dockerfile`（多阶段构建，最终镜像 < 200MB）
- [ ] 编写 `docker-compose.yml`：后端 + PostgreSQL 一键启动
- [ ] 挂载 volume 持久化 PostgreSQL 数据
- [ ] 健康检查：`GET /health` 端点

### ✅ P1 Review 检查点

- [ ] `docker-compose up` 后端可用
- [ ] SDK 运行示例脚本 → HTTP 上报成功 → `GET /api/traces` 能查到数据
- [ ] 树结构 JSON 嵌套关系正确，`exec_order` 排序正确
- [ ] 高并发入库不丢数据（100 个 Run 压测验证）

---

## P2 · 前端 UI 层

> **目标**：React + TypeScript 单页应用，可浏览 trace 列表、点击查看追踪树、展开节点看详情
>
> **验收标准**：浏览器能完整复现 P0 CLI 树打印的效果，并支持点击展开节点详情

### P2.1 项目脚手架

- [ ] 初始化 `frontend/`（Vite + React + TypeScript）
- [ ] 配置 Tailwind CSS + shadcn/ui 组件库
- [ ] 配置 `axios` / `fetch` API 客户端，代理指向后端
- [ ] 配置路由：`react-router-dom`，路由：`/` → 列表，`/trace/:id` → 详情

### P2.2 API 客户端层

- [ ] 定义 TypeScript 类型：`Run`、`Trace`、`TraceTree`（与后端 schema 一一对应）
- [ ] 实现 `api/traces.ts`：`listTraces(params)`、`getTrace(traceId)`、`getRun(runId)`
- [ ] 实现请求错误统一处理

### P2.3 Trace 列表页（`/`）

- [ ] `TraceList` 组件：表格展示根 trace 列表
  - 列：状态色点、名称、run_type 标签、耗时、开始时间、tags
- [ ] 分页组件
- [ ] `FilterBar` 组件：run_type 多选、error 开关、时间范围选择器
- [ ] 点击行跳转到 `TraceDetail` 页

### P2.4 追踪树详情页（`/trace/:id`）

- [ ] `TraceTree` 组件：递归渲染树节点，支持展开/折叠
- [ ] `RunNode` 组件：
  - 图标（🔗链/🤖 LLM/🔧工具）+ 名称 + 耗时 + 状态色
  - 错误节点整行标红
  - 点击选中，高亮显示
- [ ] `DetailPanel` 组件（右侧/下方面板）：
  - Input JSON（格式化可折叠展示，使用 `react-json-view`）
  - Output JSON
  - 耗时、开始/结束时间
  - run_type、tags、metadata key-value 列表
  - 若 run_type=llm：显示 token 用量（若有）
  - 若有 error：红色错误信息 + 堆栈
- [ ] 树节点默认展开 2 层，超深层级懒展开

### P2.5 整体 UI 布局

- [ ] 顶栏：项目名、返回按钮（详情页）
- [ ] 空状态页：无 trace 时提示如何接入 SDK
- [ ] Loading 骨架屏
- [ ] 响应式布局（桌面端优先，1280px 基准）

### ✅ P2 Review 检查点

- [ ] 端到端测试：跑一段 Python 代码 → 上报 → 刷新页面 → 看到 trace → 点开树 → 节点详情正确
- [ ] 错误节点显示正确（红色 + 堆栈）
- [ ] 大 trace（50+ 节点）不卡顿
- [ ] JSON 数据量大时（>10KB）也能正常渲染

---

## P3 · 完善打磨

> **目标**：补齐生产可用性：搜索、过滤、鉴权、前端 Docker 化、接入文档

### P3.1 搜索与高级过滤

- [ ] 后端：`GET /api/traces?search=keyword` 支持模糊搜索（name/inputs/outputs 全文搜索）
- [ ] 后端：`duration_gt` 过滤慢查询
- [ ] 前端：搜索框 + 防抖
- [ ] 前端：按 metadata 字段动态过滤（输入 `key=value`）

### P3.2 API Key 鉴权（轻量版）

- [ ] 后端：`POST /api/auth/keys` 生成 API Key（随机生成，下发原始 key 一次，DB 中只存 `SHA-256(key)` hash，防止数据库泄露导致 key 泄露）
- [ ] 后端：所有 API 接口校验 `Authorization: Bearer <key>` header
- [ ] SDK：支持 `LIGHTSMITH_API_KEY` 环境变量
- [ ] 前端：登录页（输入 key），key 存 localStorage

### P3.3 前端 Docker 化

- [ ] 编写 `frontend/Dockerfile`（Vite build + nginx 静态托管）
- [ ] 更新 `docker-compose.yml`：加入前端服务，nginx 反代后端 `/api`
- [ ] 环境变量：`VITE_API_BASE_URL` 注入

### P3.4 时间轴甘特图

- [ ] 前端：在 `TraceDetail` 页新增甘特图视图，以横向 bar 展示每个 run 的 start_time ~ end_time 区间
- [ ] 无需新 API（数据已在 `GET /api/traces/{trace_id}` 中），纯前端渲染
- [ ] 鼠标悬停显示 run 名称和耗时，点击与树视图联动选中同一节点

### P3.5 SDK 接入文档

- [ ] `README.md`：快速开始（3 步：安装 → 设置环境变量 → 加装饰器）
- [ ] 装饰器 API 文档：所有参数说明 + 示例
- [ ] 完整 Docker 部署文档

### ✅ P3 Review 检查点

- [ ] `docker-compose up` 一键启动前后端 + 数据库
- [ ] 完整走一遍：SDK 接入 → 上报 → UI 查看 → 搜索过滤 → API Key 鉴权
- [ ] 甘特图与树视图联动正确
- [ ] 文档能让新人 10 分钟内跑起来

---

## P4 · 进阶功能（暂不推进，仅作说明）

> 无硬性优先级，按实际需求选做

- [ ] **Token 成本估算**：根据 model 名和 token 数自动计算费用，dashboard 展示总消费
- [ ] **Trace 对比**：选两条 trace 并排对比 Input/Output 差异
- [ ] **Webhook**：支持配置 URL，trace 出错时 POST 通知
- [ ] **数据导出**：选中 trace 导出为 JSON / CSV
- [ ] **Prometheus metrics 端点**：`/metrics` 暴露 trace 数量、平均耗时等
- [ ] **TypeScript SDK**：基于 Python SDK 设计平行实现

---

## 关键技术决策备忘

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 上下文传播 | `contextvars` | 原生支持 asyncio，线程安全 |
| 本地存储 | SQLite fallback | 零依赖，开发调试方便 |
| 生产数据库 | PostgreSQL | JSON 字段支持好，索引能力强 |
| 批量上报 | 100条/5s 双触发 | 平衡延迟和网络请求数 |
| 前端框架 | React + TypeScript | 组件复用好，类型安全 |
| UI 组件库 | shadcn/ui | 无样式锁定，定制灵活 |
| 容器化 | Docker Compose | 一键启动，无需手动配环境 |

---

## 已知风险与对策

| 风险 | 可能影响 | 对策 |
|------|---------|------|
| 上下文在多线程线程池中丢失 | P0 | 测试 `ThreadPoolExecutor` 场景，必要时手动传递 run_id |
| 大 trace（100+ 节点）前端渲染卡顿 | P2 | 虚拟滚动 or 懒展开，超过 50 子节点折叠 |
| SDK 上报失败导致业务代码受影响 | P1 | 所有上报逻辑 try-except，失败只打日志不抛异常 |
| 入参包含不可序列化对象 | P0 | 序列化失败时 fallback 为 `repr()` 截断字符串 |
| SQLite→PostgreSQL 历史数据迁移 | P1 | P0 阶段 SQLite 数据视为开发临时数据，不做迁移；正式使用从 P1 PostgreSQL 起始，README 中明确说明 |

---

*最后更新：2026-03-31*
