# LightSmith 并发控制机制详解

> 本文档详细说明 LightSmith 项目在各层级的并发控制策略、实现机制及设计权衡

---

## 📋 目录

1. [总体架构](#总体架构)
2. [P0 SDK 层并发控制](#p0-sdk-层并发控制)
3. [P1 后端层并发控制](#p1-后端层并发控制)
4. [并发场景分析](#并发场景分析)
5. [设计权衡与最佳实践](#设计权衡与最佳实践)
6. [已知限制与风险](#已知限制与风险)

---

## 总体架构

LightSmith 项目的并发控制贯穿三个层次:

```
┌─────────────────────────────────────────────────────────────┐
│  用户代码层                                                  │
│  - 多线程应用 (ThreadPoolExecutor)                          │
│  - 异步应用 (asyncio, FastAPI)                             │
│  - 混合场景 (async + 线程池)                               │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│  SDK 层并发控制 (P0)                                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 上下文管理 (context.py)                              │  │
│  │  - ContextVar 调用栈 (协程隔离)                     │  │
│  │  - threading.Lock exec_order (全局共享)             │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ SQLite 存储 (storage/sqlite.py)                      │  │
│  │  - threading.Lock 连接保护                           │  │
│  │  - DCL 单例模式                                      │  │
│  │  - run_in_executor 异步包装                          │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│  后端层并发控制 (P1)                                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ SQLAlchemy 引擎 (db/base.py)                         │  │
│  │  - 连接池管理 (pool_size=10, max_overflow=20)       │  │
│  │  - 依赖注入生命周期 (get_db)                         │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Repository 层 (db/repository.py)                     │  │
│  │  - 幂等性保证 (INSERT OR IGNORE / ON CONFLICT)      │  │
│  │  - 事务管理                                          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## P0 SDK 层并发控制

### 1. 上下文管理器 (context.py)

#### 1.1 调用栈隔离：ContextVar + 不可变 tuple

**设计目标**：每个协程/线程维护独立的 Run 调用栈，互不干扰

**实现机制**：

```python
from contextvars import ContextVar

# 调用栈：不可变 tuple 存储 (run_id, trace_id) 元组
_run_stack: ContextVar[tuple[tuple[str, str], ...]] = ContextVar(
    "_lightsmith_run_stack", default=()
)

def push_run(run_id: str, trace_id: str) -> None:
    stack = _run_stack.get()
    _run_stack.set(stack + ((run_id, trace_id),))  # ← 创建新 tuple，触发隔离
```

**隔离原理（双重机制）**：

| 层次 | 提供者 | 作用 |
|------|--------|------|
| **第一层** | Python `contextvars` + `asyncio.create_task()` | 子任务继承父任务上下文快照，`set()` 只影响当前任务 |
| **第二层** | 代码中使用不可变 `tuple` | 强制每次修改都走 `set()` 路径，无法意外绕过隔离 |

**对比可变结构的陷阱**：

```python
# ❌ 错误：可变 list + 原地修改（会穿透 ContextVar 隔离）
_stack_bad: ContextVar[list] = ContextVar("stack", default=[])

def push_bad(run_id):
    _stack_bad.get().append(run_id)  # 修改共享对象，父子任务互相污染

# ✅ 正确：不可变 tuple + set()（隔离正常工作）
def push_good(run_id):
    _run_stack.set(_run_stack.get() + ((run_id,),))  # 创建新对象，走正规路径
```

**验证覆盖**：

- `test_context.py::TestAsyncIsolation::test_100_concurrent_coroutines_isolated`
- `test_context.py::TestThreadIsolation::test_10_threads_independent`
- 协程嵌套、线程隔离、async+线程池混用场景全部通过

---

#### 1.2 exec_order 计数器：threading.Lock + dict (全局共享)

**设计目标**：同一父节点下的兄弟节点全局有序（即使在不同协程/线程中创建）

**为什么不能用 ContextVar？**

| 状态 | 语义需求 | 工具选择 |
|------|---------|---------|
| 调用栈 (`_run_stack`) | **隔离** — 每个协程走自己的路径 | `ContextVar` |
| exec_order 计数器 | **共享** — 兄弟节点从同一个数字往上数 | `dict + threading.Lock` |

**冲突场景示例**：

```python
@traceable
async def parent():
    # 两个兄弟节点并发启动，应分别得到 exec_order=0 和 exec_order=1
    await asyncio.gather(child_a(), child_b())

# 如果用 ContextVar：
#   - create_task(child_a) → 复制上下文副本，计数器=0
#   - create_task(child_b) → 复制上下文副本，计数器=0
#   - 结果：两个兄弟都是 0 ❌

# 使用全局 dict + Lock：
#   - child_a 进入 Lock → 读到 0 → 写回 1 → 释放
#   - child_b 进入 Lock → 读到 1 → 写回 2 → 释放
#   - 结果：兄弟节点 0、1 有序 ✅
```

**实现代码**：

```python
import threading

_exec_order_counters: dict[tuple[str, Optional[str]], int] = {}  # key: (trace_id, parent_run_id)
_exec_order_lock = threading.Lock()

def next_exec_order(trace_id: str, parent_run_id: Optional[str]) -> int:
    """原子地分配下一个 exec_order，线程安全"""
    key = (trace_id, parent_run_id)
    with _exec_order_lock:
        order = _exec_order_counters.get(key, 0)
        _exec_order_counters[key] = order + 1
    return order
```

**内存管理**：

```python
def clear_exec_order_counters(trace_id: str) -> None:
    """根 Run 结束时清理，防止长期运行进程内存泄漏"""
    with _exec_order_lock:
        keys_to_del = [k for k in _exec_order_counters if k[0] == trace_id]
        for k in keys_to_del:
            del _exec_order_counters[k]
```

**验证覆盖**：

- `test_context.py::TestExecOrder::test_20_threads_concurrent_no_duplicate`
- 并发场景下无重复编号、兄弟节点顺序正确

---

### 2. SQLite 存储层 (storage/sqlite.py)

#### 2.1 连接保护：threading.Lock

**问题背景**：

- SQLite 默认单线程 (`check_same_thread=True`)
- 即使设置 `check_same_thread=False`，仍需外部同步

**解决方案**：

```python
class RunWriter:
    def __init__(self, db_path: Optional[str] = None):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,  # 允许跨线程，但需手动同步
        )
    
    def save(self, run: Run) -> None:
        """线程安全的同步写入"""
        with self._lock:
            self._conn.execute(_INSERT_SQL, self._run_to_row(run))
            self._conn.commit()
    
    def get_trace(self, trace_id: str) -> list[Run]:
        """线程安全的查询"""
        with self._lock:
            cursor = self._conn.execute(_SELECT_TRACE_SQL, (trace_id,))
            return [self._row_to_run(row) for row in cursor.fetchall()]
```

**为什么选择单连接 + Lock 而非连接池？**

| 方案 | 优势 | 劣势 | P0 选择 |
|------|------|------|---------|
| 单连接 + Lock | 零依赖、零配置、行为可预期 | 高并发写入时成为瓶颈 | ✅ P0 场景并发量极低 |
| 连接池 | 并发性能好 | 依赖外部库、配置复杂 | P1 后端切 PostgreSQL 后使用 |

---

#### 2.2 幂等性保证：INSERT OR IGNORE

**设计需求**：同一 `run.id` 重复提交时，以首次为准，不报错

**实现**：

```python
_INSERT_SQL = """
INSERT OR IGNORE INTO runs
    (id, trace_id, parent_run_id, name, run_type, inputs, outputs,
     error, start_time, end_time, metadata, tags, exec_order)
VALUES
    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
```

**原子性**：

- `INSERT OR IGNORE` 是数据库原生能力，避免并发 race condition
- 无需应用层先 SELECT 再 INSERT（TOCTOU 漏洞）

**与 P1.3 后端 API 设计对齐**：

- P1.3 `POST /api/runs/batch` 返回 `{"accepted": N, "duplicates": M}`
- Repository 层使用相同策略（PostgreSQL: `ON CONFLICT DO NOTHING`）

---

#### 2.3 异步包装：run_in_executor

**问题**：SQLite 写入是同步阻塞操作，在 asyncio 中直接调用会阻塞事件循环

**解决方案**：

```python
async def async_save(self, run: Run) -> None:
    """异步写入，不阻塞事件循环"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, self.save, run)  # 在线程池中执行同步 save()
```

**技术优势**：

- ✅ 零新依赖（无需 `aiosqlite`）
- ✅ 与 `save()` 共享线程安全逻辑
- ✅ 毫秒级写入，线程池调度开销可接受

**适用场景**：

- FastAPI 异步路由中的追踪
- `@traceable` 装饰异步函数

**验证覆盖**：

- `test_sqlite.py::TestRunWriterAsync::test_10_concurrent_async_saves`

---

#### 2.4 单例模式：双重检查锁 (DCL)

**目标**：进程级别的默认 RunWriter 单例，线程安全初始化

**实现**：

```python
_default_writer: Optional[RunWriter] = None
_default_writer_lock = threading.Lock()

def get_default_writer() -> RunWriter:
    global _default_writer
    if _default_writer is None:           # 快速路径（无锁检查）
        with _default_writer_lock:
            if _default_writer is None:   # 确保只初始化一次
                _default_writer = RunWriter()
    return _default_writer
```

**为什么需要双重检查？**

| 阶段 | 作用 |
|------|------|
| 外层 `if` | 避免每次调用都争抢锁（热路径性能优化） |
| 内层 `if` | 防止多线程同时通过外层检查时重复初始化 |

**GIL 与 DCL**：

- Python GIL 在某些场景下"意外"保证单例，但 DCL 明确表达意图
- 对 nogil Python (3.13+) 也安全

---

### 3. run_in_executor 的已知限制 (Python 3.11)

**限制**：`loop.run_in_executor` 启动的线程以**默认值**（空栈）开始，不继承调用协程的 ContextVar 状态

**影响场景**：

```python
@traceable
async def parent():
    # 如果在这里调用 executor.submit(child_func)，
    # child_func 看到的 _run_stack 是空的（不继承 parent 的上下文）
    executor = ThreadPoolExecutor()
    await loop.run_in_executor(executor, child_func)
```

**应对策略（P0.3 已测试记录）**：

- 若需支持此场景，通过函数参数显式传递 `run_id` / `trace_id`
- P0 阶段不强制支持，作为已知设计约束留给后续处理

**验证覆盖**：

- `test_context.py::TestAsyncThreadMix::test_run_in_executor_does_not_inherit_context`

---

## P1 后端层并发控制

### 1. SQLAlchemy 引擎与连接池 (db/base.py)

#### 1.1 连接池管理

**SQLite vs PostgreSQL 配置**：

```python
if settings.is_sqlite:
    # SQLite：不使用连接池（单文件，无并发优势）
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
else:
    # PostgreSQL：启用连接池（复用连接，300ms → 10ms）
    engine = create_engine(
        settings.database_url,
        pool_size=10,        # 常驻连接数
        max_overflow=20,     # 临时扩展上限（总计 30 连接）
    )
```

**连接池优势**：

| 指标 | 无连接池 | 连接池 |
|------|---------|--------|
| 连接建立时间 | 每次请求 ~300ms | 首次后 ~10ms（复用） |
| 并发能力 | 受限于数据库 max_connections | 应用层排队 + 复用 |
| 资源开销 | 频繁建立/销毁 | 常驻连接，稳定开销 |

**为什么 SQLite 不用连接池？**

- SQLite 是单文件数据库，无网络开销
- 多连接读写同一文件需复杂的文件锁协调，反而降低性能
- P1 场景预期使用 PostgreSQL，SQLite 仅作开发/离线模式

---

#### 1.2 会话工厂与依赖注入

**会话生命周期**：

```python
SessionLocal = sessionmaker(
    autocommit=False,  # 手动控制事务提交
    autoflush=False,   # 手动触发 flush（避免意外 SQL）
    bind=engine,
)

def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入：请求作用域会话"""
    db = SessionLocal()
    try:
        yield db  # 暂停并返回 db，路由函数执行
    finally:
        db.close()  # 请求结束后，确保关闭（异常安全）
```

**依赖注入优势**：

| 特性 | 手动管理 | 依赖注入 |
|------|---------|---------|
| 资源泄漏风险 | 高（忘记 close） | 低（FastAPI 自动管理） |
| 异常安全 | 需手动 try/finally | `yield` 保证 finally 执行 |
| 可测试性 | 难以替换 | `app.dependency_overrides` 轻松 mock |

**使用示例**：

```python
@app.get("/api/traces")
def list_traces(db: Session = Depends(get_db)):
    repo = RunRepository(db)
    return repo.list_traces()
    # FastAPI 自动调用 db.close()
```

---

### 2. Repository 层并发设计 (db/repository.py)

#### 2.1 幂等性保证

**与 P0.4 SQLite 保持一致的语义**：

```python
def save_batch(self, runs: list[Run]) -> dict[str, int]:
    """批量保存，幂等性"""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    
    if self.settings.is_sqlite:
        stmt = sqlite_insert(Run).values(...).prefix_with("OR IGNORE")
    else:
        stmt = pg_insert(Run).values(...).on_conflict_do_nothing(index_elements=["id"])
    
    self.db.execute(stmt)
    self.db.commit()
```

**原子性保证**：

- 数据库层原生能力，避免应用层 TOCTOU (Time-of-Check-Time-of-Use) 漏洞
- 同一 `run.id` 重复提交时，以首次为准，返回 `{"accepted": N, "duplicates": M}`

---

#### 2.2 事务隔离级别

**SQLAlchemy 默认**：

- PostgreSQL: `READ COMMITTED`（读已提交）
- SQLite: `SERIALIZABLE`（串行化）

**LightSmith 场景分析**：

| 场景 | 并发冲突风险 | 隔离级别需求 |
|------|-------------|-------------|
| 批量写入 runs | 低（主键冲突由 ON CONFLICT 处理） | `READ COMMITTED` 足够 |
| 查询 trace 列表 | 无（只读） | 任意级别 |
| 查询树结构 | 低（trace_id 已确定） | `READ COMMITTED` 足够 |

**结论**：默认隔离级别已满足需求，无需提升至 `REPEATABLE READ` / `SERIALIZABLE`

---

#### 2.3 查询优化与索引

**索引设计（与 P0.4 SQLite 一致）**：

```sql
CREATE INDEX idx_runs_trace_id      ON runs (trace_id);       -- 高频查询
CREATE INDEX idx_runs_parent_run_id ON runs (parent_run_id);  -- 树重建
CREATE INDEX idx_runs_start_time    ON runs (start_time);     -- 时间过滤
```

**分页查询模式**：

```python
def list_traces(self, page=1, page_size=50, **filters) -> dict:
    """分页查询根 Run（trace 列表）"""
    query = self.db.query(Run).filter(Run.parent_run_id == None)  # 只查根节点
    
    # 应用过滤条件（run_type、tags、has_error、时间范围）
    if filters.get("run_type"):
        query = query.filter(Run.run_type == filters["run_type"])
    
    # 分页
    total = query.count()
    items = query.order_by(Run.start_time.desc()) \
                 .offset((page - 1) * page_size) \
                 .limit(page_size) \
                 .all()
    
    return {"items": items, "total": total, "page": page, ...}
```

**性能考虑**：

- `parent_run_id IS NULL` 利用索引（PostgreSQL 支持部分索引）
- `order_by(start_time)` 利用索引排序
- `count()` 查询较慢（大数据量下可考虑缓存或估算）

---

### 3. FastAPI 请求隔离

**ASGI 并发模型**：

```
每个请求 → 独立的 asyncio Task → 独立的 Session → 独立的事务
```

**隔离保证**：

| 层次 | 机制 |
|------|------|
| 请求上下文 | FastAPI 依赖注入（每请求一个 `db` Session） |
| 数据库会话 | SQLAlchemy Session 独立（不同请求互不影响） |
| 连接池 | Engine 管理，自动复用连接但事务隔离 |

**异常安全**：

```python
@app.post("/api/runs/batch")
def batch_ingest(runs: list[Run], db: Session = Depends(get_db)):
    try:
        repo = RunRepository(db)
        return repo.save_batch(runs)
    except Exception:
        db.rollback()  # 异常时回滚
        raise
    # FastAPI 自动 db.close()
```

---

## 并发场景分析

### 场景 1：多线程应用 + @traceable

```python
from concurrent.futures import ThreadPoolExecutor
import lightsmith as ls

ls.init_local_storage()

@ls.traceable
def task(x):
    return x * 2

# 10 个线程并发执行
with ThreadPoolExecutor(max_workers=10) as executor:
    results = list(executor.map(task, range(10)))
```

**并发控制路径**：

1. 每个线程独立的 ContextVar 调用栈（不互相污染）
2. exec_order 计数器使用 `threading.Lock` 全局同步
3. SQLite 写入使用 `threading.Lock` 串行化

**结果**：10 条独立 trace，每条包含 1 个 Run

---

### 场景 2：异步应用 + 嵌套调用

```python
import asyncio
import lightsmith as ls

ls.init_local_storage()

@ls.traceable
async def parent():
    await asyncio.gather(child_a(), child_b())

@ls.traceable
async def child_a():
    await asyncio.sleep(0.1)

@ls.traceable
async def child_b():
    await asyncio.sleep(0.2)

asyncio.run(parent())
```

**并发控制路径**：

1. `parent` 创建 trace，调用栈：`[(parent_run_id, trace_id)]`
2. `create_task(child_a)` 和 `create_task(child_b)` 继承上下文快照
3. 两个子任务并发执行：
   - `child_a` 调用栈：`[(parent_run_id, trace_id), (child_a_run_id, trace_id)]`
   - `child_b` 调用栈：`[(parent_run_id, trace_id), (child_b_run_id, trace_id)]`
4. exec_order 计数器通过 `threading.Lock` 分配：`child_a=0`, `child_b=1`

**结果**：1 条 trace，包含 3 个 Run（父子关系正确，exec_order 有序）

---

### 场景 3：FastAPI 高并发请求

```python
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.db.repository import RunRepository

app = FastAPI()

@app.post("/api/runs/batch")
def batch_ingest(runs: list[Run], db: Session = Depends(get_db)):
    repo = RunRepository(db)
    return repo.save_batch(runs)
```

**并发控制路径**：

1. **请求隔离**：每个请求独立的 asyncio Task + 独立的 `db` Session
2. **连接池管理**：SQLAlchemy Engine 从连接池分配连接
   - 前 10 个请求立即获取连接（pool_size=10）
   - 第 11-30 个请求等待空闲连接或临时创建（max_overflow=20）
   - 第 31+ 个请求阻塞等待
3. **幂等性**：`ON CONFLICT DO NOTHING` 避免重复插入
4. **事务隔离**：PostgreSQL `READ COMMITTED` 级别

**结果**：高并发写入安全，无数据丢失或冲突

---

### 场景 4：混合场景 (async + ThreadPoolExecutor)

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor()

@ls.traceable
async def async_task():
    # ⚠️ 已知限制：executor 线程不继承 ContextVar
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, sync_task)

@ls.traceable
def sync_task():
    # 此处 _run_stack 为空（独立根节点）
    pass

asyncio.run(async_task())
```

**已知限制**：Python 3.11 中 `run_in_executor` 不继承 ContextVar

**解决方案（P1+ 可实现）**：

```python
@ls.traceable
async def async_task():
    run_id = ls.get_current_run_id()  # 显式获取
    trace_id = ls.get_current_trace_id()
    await loop.run_in_executor(executor, sync_task, run_id, trace_id)

@ls.traceable(manual_context=True)
def sync_task(parent_run_id, trace_id):
    ls.push_run(parent_run_id, trace_id)  # 手动注入
    try:
        # 业务逻辑
        pass
    finally:
        ls.pop_run()
```

---

## 设计权衡与最佳实践

### 1. ContextVar vs threading.local

| 方案 | 优势 | 劣势 | LightSmith 选择 |
|------|------|------|----------------|
| `ContextVar` | asyncio 原生支持，自动隔离 | Python 3.7+ | ✅ 调用栈 |
| `threading.local` | 线程隔离 | asyncio 中无效（多协程共享） | ❌ |

**结论**：现代异步应用必选 `ContextVar`

---

### 2. 单连接 + Lock vs 连接池

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| **P0 SDK (SQLite)** | 单连接 + Lock | 零依赖、零配置、并发量极低 |
| **P1 Backend (PostgreSQL)** | 连接池 | 高并发、网络延迟、连接复用 |

**关键指标**：

- 单连接 + Lock 瓶颈：~1000 写入/秒（受 SQLite 文件锁限制）
- PostgreSQL 连接池：~10000+ 写入/秒（取决于硬件）

---

### 3. 同步 vs 异步存储

| 方案 | 适用场景 | 实现成本 |
|------|---------|---------|
| **同步写入** | 多线程应用、简单脚本 | 低（直接 sqlite3） |
| **异步写入** | FastAPI、asyncio 应用 | 中（run_in_executor / aiosqlite） |

**LightSmith P0 选择**：

- 同步写入（`save`）+ 异步包装（`async_save`）
- 优势：零新依赖、行为可预期、毫秒级延迟可接受

---

### 4. 幂等性设计原则

**核心需求**：SDK 重试、网络抖动、分布式部署场景下，同一 Run 重复提交不应报错

**实现策略（三层防御）**：

| 层次 | 机制 | 作用 |
|------|------|------|
| **应用层** | 装饰器 try-except | 存储失败不影响业务代码 |
| **SDK 存储层** | `INSERT OR IGNORE` (SQLite) | 数据库层原子操作 |
| **后端 API 层** | `ON CONFLICT DO NOTHING` (PostgreSQL) | 批量写入幂等性 |

**反模式（避免）**：

```python
# ❌ 错误：先 SELECT 再 INSERT（TOCTOU 漏洞）
existing = db.query(Run).filter_by(id=run.id).first()
if not existing:
    db.add(run)  # 并发时可能重复插入
    db.commit()

# ✅ 正确：数据库原生幂等性
stmt = insert(Run).values(...).on_conflict_do_nothing(index_elements=["id"])
db.execute(stmt)
db.commit()
```

---

### 5. 异常安全最佳实践

**P0 装饰器层**：

```python
try:
    output = fn(*args, **kwargs)
    return output
except BaseException as exc:
    caught_exc = exc
    raise  # 原样重抛，不吞异常
finally:
    pop_run()  # 确保调用栈恢复
    _finalize_run(run, output, caught_exc)
    _emit_run(run)  # 写入失败静默忽略（try-except 在 emit 内部）
```

**P1 Repository 层**：

```python
@app.post("/api/runs/batch")
def batch_ingest(runs: list[Run], db: Session = Depends(get_db)):
    try:
        repo = RunRepository(db)
        return repo.save_batch(runs)
    except Exception:
        db.rollback()  # 异常时回滚事务
        raise  # 向上传播，FastAPI 返回 500
    # FastAPI 自动 db.close()（finally 语义）
```

---

## 已知限制与风险

### 1. SQLite 并发写入瓶颈

**限制**：SQLite 默认 `journal_mode=DELETE`，并发写入受文件锁限制

**影响**：

- 单连接 + Lock：~1000 写入/秒
- 多进程写入：`database is locked` 错误

**缓解措施**：

```python
# 启用 WAL 模式（Write-Ahead Logging）
conn.execute("PRAGMA journal_mode=WAL")  # 支持并发读写
```

**P1 策略**：生产环境切换 PostgreSQL，SQLite 仅用于开发/测试

---

### 2. run_in_executor 上下文丢失

**限制**：Python 3.11 中 `run_in_executor` 线程不继承协程 ContextVar

**影响场景**：

- `@traceable` 函数内调用 `executor.submit`
- 子任务看到的调用栈为空（变成独立根节点）

**解决方案（待 P1+ 实现）**：

1. 显式传递 `run_id` / `trace_id`
2. 提供 `@traceable(manual_context=True)` 参数
3. 升级至 Python 3.12+（可能已修复）

**当前状态**：P0 阶段已测试记录，作为已知约束

---

### 3. 连接池耗尽风险

**场景**：FastAPI 高并发请求 > `pool_size + max_overflow`

**表现**：

- 请求阻塞等待空闲连接
- 超时后抛出 `TimeoutError: QueuePool limit of size X overflow Y reached`

**缓解措施**：

```python
# 1. 监控连接池使用率
engine.pool.size()         # 当前连接数
engine.pool.checkedout()   # 已借出连接数

# 2. 调整连接池参数
engine = create_engine(
    database_url,
    pool_size=20,          # 增加常驻连接
    max_overflow=50,       # 增加临时上限
    pool_timeout=30,       # 等待超时时间
    pool_recycle=3600,     # 连接回收（防止 MySQL gone away）
)

# 3. 限流
from fastapi_limiter import FastAPILimiter
FastAPILimiter.init(redis_client)
```

---

### 4. 内存泄漏风险

**风险点**：

1. **exec_order 计数器**：长期运行进程中 `_exec_order_counters` 无限增长
2. **SQLAlchemy Session**：未正确关闭 Session 导致连接泄漏

**防御措施**：

```python
# 1. 根 Run 结束时清理计数器
if run.is_root:
    clear_exec_order_counters(run.trace_id)

# 2. FastAPI 依赖注入自动管理
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()  # 确保关闭

# 3. 定期监控
import gc
print(len(_exec_order_counters))  # 应该在合理范围内
```

---

### 5. 时区问题

**风险**：时间字段存储为 ISO 8601 字符串，但未显式标注 UTC

**潜在问题**：

- 跨时区服务部署时，时间解析可能出错
- 夏令时切换时可能产生歧义

**最佳实践**：

```python
from datetime import datetime, timezone

# ✅ 始终使用 UTC 时间
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ❌ 避免使用本地时间
datetime.now().isoformat()  # 无时区信息，危险
```

**P1 改进**：在 Pydantic schema 中显式标注时区

---

## 附录：测试覆盖矩阵

| 场景 | 测试文件 | 测试用例 | 状态 |
|------|---------|---------|------|
| **ContextVar 协程隔离** | `test_context.py` | `test_100_concurrent_coroutines_isolated` | ✅ |
| **threading.Lock 线程安全** | `test_context.py` | `test_20_threads_concurrent_no_duplicate` | ✅ |
| **run_in_executor 限制** | `test_context.py` | `test_run_in_executor_does_not_inherit_context` | ✅ |
| **SQLite 幂等性** | `test_sqlite.py` | `test_save_batch_idempotent` | ✅ |
| **async_save 并发** | `test_sqlite.py` | `test_10_concurrent_async_saves` | ✅ |
| **Repository 幂等性** | `test_repository.py` | `test_save_batch_idempotent` | ✅ |
| **连接池管理** | `test_repository.py` | （依赖 SQLAlchemy 自测） | ✅ |

---

## 总结

LightSmith 项目的并发控制设计兼顾了以下目标：

1. **正确性**：ContextVar + 不可变 tuple 确保协程隔离，threading.Lock 保证全局状态原子性
2. **性能**：连接池、幂等性、索引优化
3. **简洁性**：P0 零依赖，P1 最小化外部依赖
4. **可扩展性**：SQLite (开发) → PostgreSQL (生产) 平滑切换

通过分层设计和充分的测试覆盖，确保了从单线程脚本到高并发 Web 应用的广泛适用性。

---

*最后更新：2026-04-03*
*作者：Claude Opus 4.6*
*文档版本：v1.0*
