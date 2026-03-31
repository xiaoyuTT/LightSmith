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

**为什么 `next_exec_order` 必须用 `threading.Lock` 而非 `ContextVar`**

调用栈（`_run_stack`）和 `exec_order` 计数器需要**截然相反**的语义：

| 状态 | 目标 | 工具 |
|------|------|------|
| `_run_stack` 调用栈 | **隔离**：每个协程/线程走自己的调用路径 | `ContextVar` |
| `exec_order` 计数器 | **共享**：兄弟节点从同一个数字往上数 | `dict + threading.Lock` |

考虑下面这个并发场景：

```python
@traceable
async def parent():
    await asyncio.gather(child_a(), child_b())   # 两个兄弟节点并发启动
```

`child_a` 和 `child_b` 同属 `parent` 下的兄弟节点，应各自分到 `exec_order=0` 和 `exec_order=1`。

**如果用 `ContextVar` 存计数器：**

`asyncio.create_task()` 在创建子任务时会自动调用 `copy_context()`，每个子任务拿到一份**独立的计数器副本**，两个子任务各自从 0 开始计数——最终 `child_a` 和 `child_b` 都得到 `exec_order=0`，编号冲突。

```
create_task(child_a)  → 复制上下文副本，计数器=0 → child_a 取得 0，写回自己的副本
create_task(child_b)  → 复制上下文副本，计数器=0 → child_b 取得 0，写回自己的副本
结果：两个兄弟都是 exec_order=0 ❌
```

**用全局 `dict + threading.Lock`：**

所有协程和线程访问的是同一个 `_exec_order_counters` dict，`with _exec_order_lock` 保证读-改-写原子完成——一个拿到 0，计数器变成 1；另一个再来拿到 1，顺序由实际调度顺序决定，唯一且正确。

```
child_a 进入 with lock → 读到 0 → 写回 1 → 释放锁 → exec_order=0
child_b 进入 with lock → 读到 1 → 写回 2 → 释放锁 → exec_order=1
结果：兄弟节点 exec_order 唯一有序 ✅
```

**一句话总结**：`ContextVar` 的隔离特性让调用栈在协程间互不干扰，但这个隔离对于需要"全局共享计数"的 `exec_order` 来说反而是破坏性的。两种工具服务于两种相反的并发需求，各司其职。

---

**`run_in_executor` 的重要已知限制（Python 3.11）**

`loop.run_in_executor` 启动的线程以**默认值**（空栈）开始，不继承调用协程的 ContextVar 状态。这是 Python 3.11 的实际行为（不同于部分文档的描述）。

**后果**：P0.3 装饰器若要支持 `ThreadPoolExecutor` 场景（用户在装饰器内部调用 `executor.submit`），需要通过函数参数显式传递 `run_id` 和 `trace_id`，而不能依赖上下文自动传播。此行为已通过测试记录，作为已知设计约束留给 P0.3 处理。

### 遗留 / 待注意

- `exec_order` 计数器在根 Run 结束时需调用 `clear_exec_order_counters(trace_id)` 清理，防止长期运行进程内存泄漏；P0.3 装饰器负责在根 Run 的 `finally` 块中调用。
- `run_in_executor` 线程不继承协程上下文（Python 3.11），P0.3 若需支持此场景需显式参数传递。

---

## P0.3 `@traceable` 装饰器

**完成时间**：2026-03-31
**状态**：[√] 已完成

### 完成内容

| 任务 | 产出文件 |
|------|---------|
| `@traceable` 装饰器（同步 + 异步） | `sdk/lightsmith/decorators.py` |
| `set_run_writer` / `_emit_run` 写入钩子 | `sdk/lightsmith/decorators.py` |
| `_safe_serialize` 入参序列化 + repr fallback | `sdk/lightsmith/decorators.py` |
| `process_inputs` / `process_outputs` 用户钩子 | `sdk/lightsmith/decorators.py` |
| 单元测试（47 个用例，全部通过） | `sdk/tests/test_decorators.py` |
| 公开接口更新 | `sdk/lightsmith/__init__.py` |

### 关键决策

**写入钩子设计（`set_run_writer`）**

P0.3 不绑定任何存储，装饰器在每次函数退出时调用 `_emit_run(run)`，后者转发给全局 `_run_writer`。默认为 `None`（无存储）。P0.4 只需调用 `set_run_writer(sqlite_writer.save)` 即可接入存储，无需修改装饰器任何代码。测试也通过此机制注入捕获列表，干净解耦。

**`_safe_serialize` 递归序列化策略**

采用 "已知类型直接返回，未知类型 try JSON → fallback repr 截断" 的分层策略：
1. `str / int / float / bool / None` → 直接返回
2. `dict` → 递归处理（key 强制转 str）
3. `list / tuple` → 递归处理每个元素
4. 其他类型 → 尝试 `json.dumps`；失败则 `repr()` 并截断至 1000 字符，后缀附加 `[truncated, type=XXX]`

这样既覆盖了嵌套结构（dict 套 list 套自定义对象），又对"看起来 JSON 兼容但实际不是"的对象（如 `decimal.Decimal`）提供保险。

**`@traceable` 双语法支持（带/不带括号）**

通过检查第一个参数 `func` 是否为 `None` 来区分两种调用方式：
- `@traceable`（无括号）：Python 会将被装饰函数作为第一个位置参数传入，`func is not None`，直接调用 `decorator(func)`
- `@traceable(...)` 或 `@traceable()`（带括号）：`func is None`，返回 `decorator` 本身

```python
def traceable(func=None, *, name=None, ...):
    def decorator(fn): ...
    if func is not None:   # @traceable（不带括号）
        return decorator(func)
    return decorator       # @traceable(...) 或 @traceable()
```

**`try/except/finally` 异常捕获模式**

```python
caught_exc: Optional[BaseException] = None
output: Any = None
try:
    output = fn(*args, **kwargs)   # 正常执行
    return output
except BaseException as exc:
    caught_exc = exc               # 保存引用（避免 Python 3 的 except 作用域删除）
    raise                          # 原样重抛，不吞异常
finally:
    pop_run()
    _finalize_run(run, output, caught_exc, process_outputs)  # 无论成败都记录
    _emit_run(run)
    if is_root:
        clear_exec_order_counters(run.trace_id)
```

Python 3 的 `except E as e` 在 except 块结束后会删除 `e` 变量（避免引用循环），但 `caught_exc = exc` 把引用赋给了另一个变量，不受此影响。`finally` 因此能安全访问 `caught_exc`。

**`is_root` 在 `push_run` 之前捕获**

`run.is_root` 等价于 `run.parent_run_id is None`，在 `_build_run` 中已设定。必须在 `push_run` 之前记录 `is_root`，因为 `push_run` 后当前 run 进入调用栈，此时 `get_current_run_id()` 会返回当前 run 的 id，如果之后再判断会出现误判（对这段逻辑来说无影响，但明确记录时序更安全）。

### 测试覆盖范围

- `TestSyncWrapper`（15 个）：Run 发射、默认名称、自定义名称、run_type、metadata、tags、入参序列化、outputs、None 返回、时间字段、根节点、`functools.wraps`、返回值透传
- `TestAsyncWrapper`（5 个）：自动识别 async、outputs、inputs、时间字段、返回值透传
- `TestExceptionCapture`（7 个）：error 字段包含异常类型和消息、异常向上传播、outputs 不被设置、end_time 仍设置、async 异常捕获和传播、Traceback 字符串包含
- `TestNestedDecorators`（7 个）：parent_run_id 正确设置、trace_id 整棵树共享、兄弟节点 exec_order 自增、3 层嵌套关系完整验证、异步嵌套、独立调用 trace_id 不同、调用后上下文干净
- `TestSerialization`（9 个）：不可序列化对象 fallback、大 repr 截断、嵌套 dict、process_inputs 钩子、process_outputs 钩子、钩子崩溃静默忽略（inputs/outputs）、钩子返回非 dict 忽略、kwargs 序列化
- `TestDecoratorSyntax`（4 个）：无括号、空括号、全参数、writer 失败不影响业务代码

### 实现细节

**入参绑定：`inspect.signature` + `bind`**

使用 `inspect.signature(func).bind(*args, **kwargs)` 将位置参数映射到参数名，再调用 `bound.apply_defaults()` 补全有默认值但未传入的参数。这样 `inputs` 字典总是完整的命名 dict，而非 `{"__args": [...]}` 格式。

仅在绑定失败时（极端情况，如 `*args` 函数）降级为 `__args / __kwargs` 格式，保证任何函数都能追踪。

**`@functools.wraps(fn)` 的作用**

装饰器本质上用 `sync_wrapper` / `async_wrapper` **替换**了原函数，若不加 `wraps`，函数的元信息会丢失：

```python
@traceable
async def my_func(x):
    """计算结果"""
    ...

print(my_func.__name__)   # 不加 wraps → "async_wrapper"，加了 → "my_func"
print(my_func.__doc__)    # 不加 wraps → None，           加了 → "计算结果"
```

`functools.wraps(fn)` 将 `fn` 的 `__name__`、`__qualname__`、`__doc__`、`__module__`、`__annotations__`、`__dict__` 复制到 wrapper，并额外写入 `__wrapped__ = fn`（指向原始函数的引用）。这是 Python 装饰器的惯例做法，确保反射、日志、traceback、IDE 类型提示均能看到正确的函数信息。

**`process_inputs` / `process_outputs` 防御策略**

两个钩子遵守相同的防御逻辑：
1. 钩子抛异常 → 静默忽略，保留原始序列化结果
2. 钩子返回非 `dict` → 忽略，保留原始结果
3. 两重保护均为 try/except 包裹 + `isinstance(processed, dict)` 检查

这确保用户钩子的任何问题都不会影响追踪本身，也不会影响被装饰的业务函数。

**`exec_order` 计数器生命周期**

根 Run（`is_root = True`）退出时，在 `finally` 块中调用 `clear_exec_order_counters(run.trace_id)`，清理该 trace 下所有 `(trace_id, parent_run_id)` 键。这解决了 P0.2 遗留的内存泄漏问题：长时间运行的进程（如 Agent 循环）中，每条 trace 结束后内存会被及时释放。

### 遗留 / 待注意

- `set_run_writer` 当前为同步接口；P0.4 SQLite writer 也是同步的，匹配。P1.5 HTTP writer 需要异步能力时，可在 writer 内部用 `asyncio.create_task` 或 `run_in_executor` 处理，装饰器本身不需要改动。
- `run_in_executor` 线程不继承协程上下文（P0.2 已知约束），P0.3 未处理此场景——在 `@traceable` 函数内通过 `executor.submit` 调用另一个 `@traceable` 函数时，子 Run 的 `parent_run_id` 会为 `None`（变成独立根节点）。这是 P0 阶段的已知限制，P1+ 可通过显式传递 `run_id` 参数来解决。

---

## P0.4 本地存储（SQLite Writer）

**完成时间**：2026-03-31
**状态**：[√] 已完成

### 完成内容

| 任务 | 产出文件 |
|------|---------|
| SQLite schema（DDL + 3 个索引） | `sdk/lightsmith/storage/sqlite.py` |
| `RunWriter.save`（同步写入，线程安全） | `sdk/lightsmith/storage/sqlite.py` |
| `RunWriter.async_save`（`run_in_executor` 包装） | `sdk/lightsmith/storage/sqlite.py` |
| `RunWriter.get_trace`（一次查询取出整棵树） | `sdk/lightsmith/storage/sqlite.py` |
| `get_default_writer`（进程级单例） | `sdk/lightsmith/storage/sqlite.py` |
| `init_local_storage` 便捷函数 | `sdk/lightsmith/__init__.py` |
| storage 子包导出 | `sdk/lightsmith/storage/__init__.py` |
| 单元测试（18 个用例，全部通过） | `sdk/tests/test_sqlite.py` |

### 关键决策

**JSON 列存储 dict / list 字段**

`inputs`、`outputs`、`metadata`、`tags` 四个字段在 SQLite 中以 JSON 文本存储（`json.dumps` / `json.loads`）。
原因：SQLite 没有原生 JSON 列类型（区别于 PostgreSQL 的 `jsonb`），文本 JSON 是 P0 阶段唯一零依赖的方案。
P1.2 迁移到 SQLAlchemy + PostgreSQL 时，这些列改为 `JSONB` 类型，ORM 自动处理序列化，此处的 `json.dumps/loads` 由 SQLAlchemy 的类型系统接管。

**`INSERT OR IGNORE` 幂等性**

写入使用 `INSERT OR IGNORE`，同一 `run.id` 重复写入时静默跳过，首次写入结果不被覆盖。
这与 P1.3 后端 `POST /api/runs/batch` 设计的幂等性要求（"以首次为准"）保持一致。
P1 PostgreSQL 版本将改用 `ON CONFLICT DO NOTHING`，语义完全对等。

**`threading.Lock` 保护单一连接 vs 连接池**

`RunWriter` 持有一个 `sqlite3.Connection`（`check_same_thread=False`），所有读写操作通过 `threading.Lock` 串行化。
选择理由：P0 场景中 SQLite 写入并发量极低，单连接 + 锁的方案零依赖、零配置、行为可预期。
连接池（如 `concurrent.futures.ThreadPoolExecutor` + 每线程一个连接）仅在高并发 P1 场景中才有意义，届时后端直接切 PostgreSQL + SQLAlchemy 连接池，P0 的实现不需要演进。

**`async_save` 选择 `run_in_executor` 而非 `aiosqlite`**

PLAN.md 给出两个选项：`run_in_executor`（包装同步代码）和 `aiosqlite`（原生异步 SQLite）。
选择 `run_in_executor` 的原因：
1. 零新依赖（`pyproject.toml` 中 `dependencies = []` 维持不变）
2. 与 P0.2 中已记录的"run_in_executor 不继承协程上下文"一致，行为可预期
3. SQLite 写入是毫秒级操作，线程池的调度开销可接受
4. P1.5 HTTP Transport 引入真正的异步 IO 时，存储层已是 PostgreSQL，届时 `aiosqlite` 不再相关

**`get_default_writer` 单例 + 双重检查锁（DCL）**

```python
def get_default_writer() -> RunWriter:
    global _default_writer
    if _default_writer is None:           # 快速路径（无锁）
        with _default_writer_lock:
            if _default_writer is None:   # 确保只初始化一次
                _default_writer = RunWriter()
    return _default_writer
```

外层 `if` 避免每次调用都争抢锁（热路径性能），内层 `if` 防止多线程同时通过外层检查时重复初始化。Python 的 GIL 虽然在某些场景下能"意外"保证单例，但 DCL 明确表达意图，对 nogil Python（3.13+）也安全。

**`init_local_storage` 便捷函数**

```python
import lightsmith as ls
ls.init_local_storage()   # 一行开启本地存储

@ls.traceable
def my_func(x):
    return x * 2
```

`init_local_storage` 创建一个**新的** `RunWriter`（而非复用 `get_default_writer` 的单例），便于测试和多数据库场景。它调用 `set_run_writer(writer.save)` 将写入钩子注入装饰器，无需修改任何追踪代码。返回 `RunWriter` 实例供调用方直接调用 `get_trace` 等方法。

### SQLite Schema 设计

```sql
CREATE TABLE runs (
    id            TEXT PRIMARY KEY,       -- UUID4 字符串
    trace_id      TEXT NOT NULL,          -- 整棵树共享
    parent_run_id TEXT,                   -- NULL = 根节点
    name          TEXT NOT NULL,
    run_type      TEXT NOT NULL,          -- 枚举字符串值
    inputs        TEXT NOT NULL DEFAULT '{}',   -- JSON
    outputs       TEXT,                          -- JSON，NULL = 未完成
    error         TEXT,                          -- NULL = 无错误
    start_time    TEXT NOT NULL,          -- ISO 8601 UTC
    end_time      TEXT,                   -- NULL = 仍在运行
    metadata      TEXT NOT NULL DEFAULT '{}',   -- JSON
    tags          TEXT NOT NULL DEFAULT '[]',   -- JSON
    exec_order    INTEGER NOT NULL DEFAULT 0
);

-- P1.4 GET /api/traces?trace_id=X 和 get_trace() 的主要访问模式
CREATE INDEX idx_runs_trace_id      ON runs (trace_id);
-- 树重建时按 parent_run_id 分组
CREATE INDEX idx_runs_parent_run_id ON runs (parent_run_id);
-- P1.4 按时间范围过滤的基础
CREATE INDEX idx_runs_start_time    ON runs (start_time);
```

字段与 `Run` dataclass 一一对应，`DDL` 用 `executescript` 在连接初始化时执行，`CREATE TABLE IF NOT EXISTS` 和 `CREATE INDEX IF NOT EXISTS` 保证幂等性，多次初始化安全。

### 测试覆盖范围

- `TestRunWriterBasic`（6 个）：save + get_trace 基础、全字段往返无损、None 可选字段、error 字段、幂等性（重复写入）、不存在 trace 返回空列表
- `TestRunWriterMultipleRuns`（4 个）：同 trace 多条 Run、exec_order 升序排列、不同 trace 隔离、parent_run_id 保留
- `TestRunWriterAsync`（2 个）：async_save 写入结果一致、10 协程并发无丢失
- `TestRunWriterIntegration`（3 个）：@traceable + RunWriter 端到端、3 层嵌套树完整验证（trace_id 共享 + 父子关系 + 3 条记录）、异常 Run 被持久化
- `TestDefaultPath`（3 个）：环境变量覆盖、默认路径为 ~/.lightsmith/traces.db、自动创建嵌套目录

### 架构图：P0.4 数据流

```
@traceable 函数退出
       │
       ▼
  _emit_run(run)
  ────────────────────────────────────────────────────────────
  decorators.py: _run_writer(run)           ← set_run_writer 注入的函数
       │
       ▼
  RunWriter.save(run)                       ← 同步路径
  (or async_save → run_in_executor → save)  ← 异步路径
       │
       ├── _run_to_row(run)                 ← Run → SQL 参数 tuple（JSON 序列化）
       ├── _lock.acquire()
       ├── conn.execute(INSERT OR IGNORE)
       ├── conn.commit()
       └── _lock.release()
                              ↓
                      SQLite 文件
              ~/.lightsmith/traces.db
                      (或环境变量指定路径)
                              ↓
       get_trace(trace_id) ──► SELECT ... WHERE trace_id = ? ORDER BY exec_order
                              ↓
                    list[Run]（整棵调用树）
```

### 接口契约（供 P0.5 和 P1.2 使用）

P0.5 CLI 工具直接调用 `RunWriter.get_trace(trace_id)` 拿到 `list[Run]`，用 `parent_run_id` 重建树结构后打印。

P1.2 将此 SQLite schema 迁移为 SQLAlchemy ORM 模型时，字段名和类型保持不变；`JSONB` 类型替代 JSON 文本列，但 `Run` dataclass 的序列化/反序列化逻辑不受影响。

### 遗留 / 待注意

- SQLite WAL 模式未启用：P0 场景单进程写入，默认日志模式（DELETE）足够。若需多进程并发写入（P1 之前不会出现），可在 `__init__` 中 `conn.execute("PRAGMA journal_mode=WAL")`。
- `RunWriter` 未注册 `atexit` 钩子自动 `close`：Python 进程退出时 SQLite 连接和文件句柄会被操作系统回收，P0 阶段可接受。P1.5 的 HTTP `BatchBuffer` 需要 `atexit` 确保数据 flush，届时一并处理。
- `get_default_writer` 返回的单例在测试中需要小心——测试间共享同一个数据库文件（`~/.lightsmith/traces.db`），会互相污染。`test_sqlite.py` 通过 `tmp_writer` fixture 为每个测试创建独立临时数据库，避免了这个问题。

---
