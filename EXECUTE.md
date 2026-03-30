# LightSmith 开发执行日志

> 每完成一个计划步骤后在此追加总结，记录实际完成情况、关键决策和遗留问题。

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

Python dataclass 中，若直接写 `inputs: dict = {}`，所有实例会共享同一个 `{}` 对象，对任何一个实例的修改都会影响其他实例。`default_factory=dict` 确保每次实例化都调用 `dict()` 创建新对象。受影响的字段：`inputs`、`metadata`、`tags`，以及 `id`、`trace_id`、`start_time`（需要运行时动态生成值）。

### 遗留 / 待注意

- `exec_order` 默认值为 `0`，实际赋值逻辑由 P0.2 上下文管理器负责，当前为占位。
- `trace_id` 在顶层 Run 创建时自动生成独立 UUID；P0.2 装饰器需负责将子 Run 的 `trace_id` 对齐到根 Run。

---
