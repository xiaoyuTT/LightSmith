# LightSmith 开发执行日志

> 每完成一个计划步骤后在此追加总结，记录实际完成情况、关键决策和遗留问题。

---

## 整体测试原理与实现

本项目 SDK 层（`sdk/`）使用 **pytest** 作为测试框架。以下说明测试的工作原理，帮助理解各 P0.x 测试文件的设计。

### pytest 如何发现测试

pytest 按以下规则自动找到并运行测试，无需手动注册：

```
sdk/
└── tests/
    ├── test_models.py      ← 文件名以 test_ 开头
    └── test_context.py
```

- **文件**：文件名以 `test_` 开头（或 `_test` 结尾）
- **类**：类名以 `Test` 开头，且不需要继承任何基类
- **方法/函数**：方法名以 `test_` 开头

```python
class TestRunType:              # ← pytest 识别此类
    def test_values_are_strings(self):   # ← pytest 识别并运行此方法
        assert RunType.LLM == "llm"
```

### assert 的魔法重写

pytest 在收集测试时会重写（rewrite）`assert` 语句的字节码。当断言失败时，pytest 能自动展开表达式，打印出左右两侧的实际值，而无需手动写 `assertEqual(a, b)` 这类冗长的 API：

```
# 失败示例：assert restored.run_type is RunType.LLM
AssertionError: assert <RunType.CHAIN: 'chain'> is <RunType.LLM: 'llm'>
#                       ^ 左侧实际值              ^ 右侧期望值
```

这是 pytest 相比 unittest 最直接的优势——断言写法与普通 Python 代码相同。

### 配置文件：`pyproject.toml`

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]       # 只在 tests/ 目录下查找测试文件
asyncio_mode = "auto"       # pytest-asyncio 配置项（见下方异步测试说明）
```

`testpaths` 告诉 pytest 不必扫描整个项目，只看 `tests/` 目录，加快收集速度。

### fixture：测试的 setup / teardown

`pytest.fixture` 是 pytest 的依赖注入机制，用于在测试前后执行准备和清理工作。

**`autouse=True`** 表示该 fixture 自动应用到当前文件/类的所有测试，无需在每个测试方法上手动引用：

```python
# test_context.py 中的 fixture
@pytest.fixture(autouse=True)
def clean_context():
    _run_stack.set(())   # 测试前：重置 ContextVar，防止上一个测试的状态污染下一个
    yield                # ← 此处执行测试本体
    _run_stack.set(())   # 测试后：再次清理
```

`yield` 把 fixture 分成两段：`yield` 前是 setup，`yield` 后是 teardown。这比 `setUp` / `tearDown` 写法更紧凑，且清理逻辑与准备逻辑在同一函数内，可读性更好。

**为什么测试间需要清理 ContextVar？**  
pytest 默认在同一个进程、同一个线程内顺序运行所有测试。`ContextVar` 是进程级别的全局状态。若测试 A 调用了 `push_run()` 但没有配对 `pop_run()`，测试 B 启动时栈不为空，测试结果将不可预期。`autouse` fixture 保证每个测试都以干净状态启动。

### 异步测试的处理方式

`pyproject.toml` 里写了 `asyncio_mode = "auto"`，但当前 pytest-asyncio 版本（0.23）将其作为 `[tool.pytest.ini_options]` 中的选项时**未被识别**（pytest 运行时会输出 `PytestConfigWarning: Unknown config option: asyncio_mode`）。

因此本项目的异步测试采用了**显式 `asyncio.run()` 包装**的方式——测试方法本身是同步的，在方法内部构造 `async def main()` 再用 `asyncio.run()` 驱动：

```python
def test_concurrent_tasks_do_not_pollute_each_other(self):
    async def task(run_id, trace_id):
        push_run(run_id, trace_id)
        await asyncio.sleep(0)
        result = get_current_run_id()
        pop_run()
        return result

    async def main():
        return await asyncio.gather(task("run-A", "trace-A"), task("run-B", "trace-B"))

    results = asyncio.run(main())   # ← 同步入口，pytest 正常运行
    assert results[0] == "run-A"
```

这种方式的好处：对 pytest-asyncio 版本无要求，行为完全可预期；缺点：每个异步测试需要多写一层包装函数。若后续升级 pytest-asyncio 并修复配置，可改为直接 `async def test_...()` 形式。

### 如何运行测试

```bash
# 进入 SDK 目录（所有命令都在此目录下执行）
cd sdk

# 运行全部测试
python -m pytest

# 详细输出（显示每个测试名称和结果）
python -m pytest -v

# 只运行某个文件
python -m pytest tests/test_context.py

# 只运行某个测试类
python -m pytest tests/test_context.py::TestAsyncIsolation

# 只运行某个测试方法
python -m pytest tests/test_context.py::TestAsyncIsolation::test_100_concurrent_coroutines_isolated
```

---

## P0.1 基础数据模型

**完成时间**：2026-03-31
**状态**：[√] 已完成

### 完成内容

| 任务 | 产出文件 |
|------|---------|
| `RunType` 枚举（5 种类型） | `sdk/lightsmith/models.py` |
| `Run` dataclass（13 个字段） | `sdk/lightsmith/models.py` |
| `to_dict()` / `from_dict()` 序列化 | `sdk/lightsmith/models.py` |
| 单元测试（22 个用例，全部通过） | `sdk/tests/test_models.py` |
| SDK 包初始化 + 公开接口 | `sdk/lightsmith/__init__.py` |
| 项目构建配置 | `sdk/pyproject.toml` |
| 子包占位文件 | `storage/__init__.py`、`integrations/__init__.py` |

### 关键决策

- **`RunType` 继承 `str`**：枚举值即字符串，`to_dict` 无需额外转换，前后端 JSON 互通无障碍。
- **时间字段存 ISO 8601 字符串**（而非 `datetime` 对象）：序列化零成本，跨语言兼容，P1 后端和 P2 前端可直接使用。
- **`from_dict` 兼容 str/enum 两种 `run_type` 输入**：防御性设计，来自 JSON 解析的字符串和已是枚举的对象都能正常处理。
- **可变默认值全部用 `field(default_factory=...)`**：避免所有实例共享同一 `dict`/`list` 对象的经典陷阱，测试专项覆盖此场景。

### 测试覆盖范围

- `TestRunType`：枚举值类型、字符串反向构造、全成员完整性
- `TestRunDefaults`：ID 唯一性、默认值正确性、可变默认值隔离
- `TestSerialization`：全字段往返、经 JSON 字符串中转的往返、None 字段往返、run_type str/enum 两种输入兼容
- `TestConvenienceProperties`：`duration_ms`、`is_root`、`has_error`、`__repr__`

### 实现细节

**`Run` dataclass 字段分组设计**

字段按职责分为四组，顺序与 UI 展示层级对齐：

```
身份字段   id / trace_id / parent_run_id     → 确定节点在树中的位置
描述字段   name / run_type                   → 决定 UI 图标和分类
数据字段   inputs / outputs / error          → 核心业务内容，体积最大
时间字段   start_time / end_time             → ISO 8601 UTC 字符串
扩展字段   metadata / tags / exec_order      → 用户自定义 + 排序
```

**序列化实现要点**

`to_dict` 只做一件事：将 `run_type` 枚举转为字符串（`.value`），其余字段直接赋值。这是唯一需要类型转换的字段，因为 `json.dumps` 不能直接序列化枚举对象。

`from_dict` 的防御逻辑：
```python
raw_type = d.get("run_type", RunType.CUSTOM)
if isinstance(raw_type, str):
    d["run_type"] = RunType(raw_type)
```
先判断再转换，支持两种输入来源：
- 来自 `json.loads` 的字符串 → 转枚举
- 已经是枚举对象（如测试中直接构造）→ 不做处理，避免 `RunType(RunType.LLM)` 的冗余调用

**`duration_ms` 属性实现**

```python
(end - start).total_seconds() * 1000
```
两个带时区的 `datetime` 相减得到 `timedelta`，再换算为毫秒浮点数。存储层用字符串、计算层用 `datetime`，两者通过 `datetime.fromisoformat()` 桥接，不在对象上持有 `datetime` 实例，避免序列化复杂度。

**`field(default_factory=...)` 的必要性**

这是 Python 中经典的"可变默认值陷阱"，分两层：

*第一层：`= {}` 为何导致共享*

Python 在**解析类定义时**就把默认值对象创建好并挂在类上，所有实例拿到的是同一个引用：

```python
@dataclass
class Bad:
    inputs: dict = {}   # 这个 {} 只创建一次

a, b = Bad(), Bad()
a.inputs["key"] = "value"
print(b.inputs)          # {"key": "value"} ← b 被污染
print(a.inputs is b.inputs)  # True
```

*第二层：`default_factory` 如何修复*

`field(default_factory=dict)` 让 dataclass 在**每次实例化时**调用 `dict()`，各实例拥有独立对象：

```python
@dataclass
class Good:
    inputs: dict = field(default_factory=dict)

a, b = Good(), Good()
a.inputs["key"] = "value"
print(b.inputs)              # {} ← 互不影响
print(a.inputs is b.inputs)  # False
```

项目中受影响的字段分两类：

| 字段 | 使用 `default_factory` 的原因 |
|------|-------------------------------|
| `inputs`、`metadata` | 可变 dict，共享会互相污染 |
| `tags` | 可变 list，同上 |
| `id`、`trace_id` | 需运行时调用 `uuid.uuid4()`，每个实例必须不同 |
| `start_time` | 需运行时调用 `datetime.now()`，固定值在所有实例上完全相同，毫无意义 |

后两类字段即使不存在"共享污染"问题，也必须用 `default_factory`——它们的值需要在**实例化的那一刻**动态生成，而非类定义时生成一次后冻结。

### 遗留 / 待注意

- `exec_order` 默认值为 `0`，实际赋值逻辑由 P0.2 上下文管理器负责，当前为占位。
- `trace_id` 在顶层 Run 创建时自动生成独立 UUID；P0.2 装饰器需负责将子 Run 的 `trace_id` 对齐到根 Run。

---

## P0.2 上下文管理器（调用树核心）

**完成时间**：2026-03-31
**状态**：[√] 已完成

### 完成内容

| 任务 | 产出文件 |
|------|---------|
| `ContextVar` 调用栈 + `push_run` / `pop_run` / `get_current_run_id` | `sdk/lightsmith/context.py` |
| `get_current_trace_id`（P0.3 装饰器所需） | `sdk/lightsmith/context.py` |
| `next_exec_order` 原子计数器 | `sdk/lightsmith/context.py` |
| `clear_exec_order_counters` 内存清理 | `sdk/lightsmith/context.py` |
| 单元测试（24 个用例，全部通过） | `sdk/tests/test_context.py` |
| 公开接口更新 | `sdk/lightsmith/__init__.py` |

### 关键决策

- **调用栈用不可变 `tuple` 存储**：每次 `push_run` / `pop_run` 都 `set` 一个新 `tuple`，利用 `ContextVar` 的写时复制（copy-on-write）语义，asyncio 任务和线程自动得到隔离。不需要 Token / reset 机制，实现简单且无泄漏。

- **exec_order 计数器用 `dict + threading.Lock` 而非 `ContextVar`**：exec_order 需要"跨协程共享"——同一 parent 下的兄弟节点无论在哪个协程创建，都应全局有序。`ContextVar` 的隔离语义反而有害，因此用普通 dict 加锁实现原子自增。

- **额外暴露 `get_current_trace_id`**：P0.3 装饰器在创建子 Run 时需要将 `trace_id` 对齐到根 Run，此函数从调用栈顶读取，免去显式传参。

### 测试覆盖范围

- `TestBasicStack`（9 个）：空栈返回 None、push/pop LIFO 顺序、多次 pop 空栈无异常、trace_id 跟随栈顶
- `TestExecOrder`（7 个）：从 0 开始自增、不同 parent 独立计数、不同 trace 独立计数、clear 后重置、20 线程并发无重复
- `TestAsyncIsolation`（5 个）：并发任务互不污染、子任务继承父任务快照、子任务 push 不影响父任务、100 协程全隔离、5 层深度嵌套
- `TestThreadIsolation`（2 个）：10 线程独立栈、主线程不受子线程影响
- `TestAsyncThreadMix`（1 个）：`run_in_executor` 线程上下文行为验证

### 实现细节

**调用栈不可变 tuple 的隔离语义**

隔离效果是 **Python `contextvars` 内置能力** 与 **代码中不可变 tuple 设计** 共同作用的结果，各自负责一半：

*第一层：Python `contextvars` + `asyncio` 提供隔离的"门"*

`asyncio.create_task()` 创建子任务时，会自动调用 `contextvars.copy_context()`，把当前任务的上下文**浅拷贝**一份交给子任务。之后子任务内任何 `ContextVar.set(...)` 调用，只修改子任务自己的绑定，父任务的绑定不受影响。这个机制由 Python 运行时保证，代码里无需额外设定。

```
主协程                        子任务（asyncio.create_task）
────────────────────────      ──────────────────────────────────
_run_stack = ()
push("root")
_run_stack = (("root","t1"),)
  │
  ├─ create_task(child)   ←── copy_context() 快照：子任务起点 = (("root","t1"),)
  │                              push("child")  → _run_stack.set(新 tuple)
  │                              _run_stack = (("root","t1"),("child","t1"),)
  │                              ... 子任务内的 set 只改子任务自己的绑定 ...
  │                              pop()
  │
  └─ 协程继续，_run_stack 仍是 (("root","t1"),)
```

*第二层：不可变 tuple 确保永远走这扇"门"*

`copy_context()` 是浅拷贝——只拷贝"ContextVar → 值"的映射，不拷贝值本身。若存的是**可变 list**，父子任务会拿到指向同一个 list 对象的引用，`append()` 直接修改对象会绕过 ContextVar 的隔离机制：

```python
# 危险：可变 list + 原地修改（子任务 append 会污染父任务）
def push_run_bad(run_id, trace_id):
    _run_stack.get().append((run_id, trace_id))  # 修改共享对象，隔离被穿透

# 正确：不可变 tuple + set()（每次生成新对象，隔离正常工作）
def push_run(run_id, trace_id):
    _run_stack.set(_run_stack.get() + ((run_id, trace_id),))  # 走 ContextVar 正规路径
```

| 能力来源 | 负责的事 |
|---------|---------|
| Python `contextvars` + `asyncio.create_task()` | 子任务得到上下文快照，`set()` 只影响当前任务 |
| 代码中使用不可变 tuple | 强制每次修改都走 `set()`，无法意外绕过隔离机制 |

**`run_in_executor` 的重要已知限制（Python 3.11）**

`loop.run_in_executor` 启动的线程以**默认值**（空栈）开始，不继承调用协程的 ContextVar 状态。这是 Python 3.11 的实际行为（不同于部分文档的描述）。

**后果**：P0.3 装饰器若要支持 `ThreadPoolExecutor` 场景（用户在装饰器内部调用 `executor.submit`），需要通过函数参数显式传递 `run_id` 和 `trace_id`，而不能依赖上下文自动传播。此行为已通过测试记录，作为已知设计约束留给 P0.3 处理。

### 遗留 / 待注意

- `exec_order` 计数器在根 Run 结束时需调用 `clear_exec_order_counters(trace_id)` 清理，防止长期运行进程内存泄漏；P0.3 装饰器负责在根 Run 的 `finally` 块中调用。
- `run_in_executor` 线程不继承协程上下文（Python 3.11），P0.3 若需支持此场景需显式参数传递。

---
