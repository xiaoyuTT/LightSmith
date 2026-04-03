# LightSmith 开发执行日志

> 每完成一个计划步骤后在此追加总结，记录实际完成情况、关键决策和遗留问题。
>
> **文档结构**：本文件为索引，详细内容按阶段分离到 `execute/` 目录下的独立文件中。

---

## 📂 文档导航

### [P0 · SDK 核心层](execute/EXECUTE_P0.md)

**目标**：`@traceable` 装饰器可用，嵌套调用自动建立父子关系，本地 SQLite 存储，CLI 打印追踪树

**包含章节**：
- 整体测试原理与实现（pytest、fixture、异步测试）
- P0.1 基础数据模型
- P0.2 上下文管理器（调用树核心）
- P0.3 `@traceable` 装饰器
- P0.4 本地存储（SQLite Writer）
- P0.5 CLI 树打印工具

**状态**：✅ 已完成（2026-03-31 ~ 2026-04-02）

---

### [P1 · 后端服务层](execute/EXECUTE_P1.md)

**目标**：FastAPI 后端可接收 SDK 上报的数据，支持 trace 查询，切换到 PostgreSQL，提供 Docker 部署

**包含章节**：
- P1.1 项目脚手架 ✅
- P1.2 数据库层（SQLAlchemy）✅
- P1.3 Run 摄入 API ✅
- P1.4 Trace 查询 API
- P1.5 SDK HTTP Transport 层
- P1.6 Docker 化

**状态**：🚧 进行中（P1.1-P1.3 已完成）

---

### [P2 · 前端 UI 层](execute/EXECUTE_P2.md)

**目标**：React + TypeScript 单页应用，可浏览 trace 列表、点击查看追踪树、展开节点看详情

**包含章节**：
- P2.1 项目脚手架
- P2.2 API 客户端层
- P2.3 Trace 列表页
- P2.4 追踪树详情页
- P2.5 整体 UI 布局

**状态**：⏳ 待开始

---

### [P3 · 完善打磨](execute/EXECUTE_P3.md)

**目标**：补齐生产可用性：搜索、过滤、鉴权、前端 Docker 化、接入文档

**包含章节**：
- P3.1 搜索与高级过滤
- P3.2 API Key 鉴权（轻量版）
- P3.3 前端 Docker 化
- P3.4 时间轴甘特图
- P3.5 SDK 接入文档

**状态**：⏳ 待开始

---

### [P4 · 进阶功能](execute/EXECUTE_P4.md)

**目标**：可选的进阶功能，按实际需求选做

**包含章节**：
- Token 成本估算
- Trace 对比
- Webhook 通知
- 数据导出
- Prometheus metrics
- TypeScript SDK

**状态**：⏳ 暂不推进

---

## 📊 整体进度

| 阶段 | 状态 | 完成时间 | 验收标准 |
|------|------|---------|---------|
| **P0 SDK 核心** | ✅ 已完成 | 2026-03-31 ~ 04-02 | 3 层嵌套函数能打印完整树，数据已写入 SQLite |
| **P1 后端服务** | 🚧 进行中 | 2026-04-03 ~ | SDK 通过 HTTP 上报，`GET /api/traces` 返回树结构 JSON |
| **P2 前端 UI** | ⏳ 待开始 | - | 浏览器能完整复现 CLI 树打印，支持点击展开详情 |
| **P3 完善打磨** | ⏳ 待开始 | - | `docker-compose up` 一键启动，完整走一遍接入流程 |
| **P4 进阶功能** | ⏳ 待开始 | - | 按需选做 |

---

## 🎯 当前焦点

**正在进行**：P1.4 Trace 查询 API

**下一步**：
1. 实现 `GET /api/traces` 分页列表（返回根 Run 摘要）
2. 实现 `GET /api/traces/{trace_id}` 树形 JSON（递归嵌套结构）
3. 实现 `GET /api/runs/{run_id}` 单个 Run 查询
4. 定义并文档化树形 JSON schema（供前端对齐）

---

## 📝 文档更新说明

**文档拆分原则**：
- 每个阶段（P0/P1/P2/P3/P4）独立一个文件
- 通用的测试原理、工具说明放在对应阶段文件的开头
- 本索引文件仅记录导航、进度概览和当前焦点

**查看详细实现**：点击上方章节标题或直接打开 `execute/` 目录下的对应文件。

**更新时间**：2026-04-03

---

## 📈 最新进展

**2026-04-03**：
- ✅ **P1.3 Run 摄入 API** 完成
  - 实现 `POST /api/runs/batch` 端点
  - Pydantic schemas（RunSchema、BatchRunsRequest、BatchRunsResponse）
  - 13 个测试用例全部通过
  - 修复 Windows 控制台编码问题（emoji → 纯文本）
  - Repository 去耦合（不依赖全局配置）
  - Pydantic v2 迁移完成（Config → ConfigDict）

---

*最后更新：2026-04-03*
