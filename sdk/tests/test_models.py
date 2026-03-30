"""
tests/test_models.py — P0.1 单元测试

验收标准（来自 PLAN.md P0.1）：
  - Run 可正常实例化，字段默认值符合预期
  - to_dict() / from_dict() 序列化往返无损（round-trip）
  - RunType 枚举可通过字符串值构造
  - 便利属性 duration_ms / is_root / has_error 行为正确
"""

import json
from datetime import datetime, timezone, timedelta

import pytest

from lightsmith.models import Run, RunType


# ---------------------------------------------------------------------------
# RunType
# ---------------------------------------------------------------------------

class TestRunType:
    def test_values_are_strings(self):
        """RunType 继承 str，枚举值本身即字符串，可直接用于 JSON 序列化。"""
        assert RunType.LLM == "llm"
        assert RunType.CHAIN == "chain"

    def test_construct_from_string(self):
        """可通过字符串值反向构造枚举，支持 from_dict 还原。"""
        assert RunType("llm") is RunType.LLM
        assert RunType("tool") is RunType.TOOL

    def test_all_members_defined(self):
        """确保 PLAN.md 中要求的五种类型都已定义。"""
        expected = {"chain", "llm", "tool", "agent", "custom"}
        actual = {m.value for m in RunType}
        assert actual == expected


# ---------------------------------------------------------------------------
# Run 默认值
# ---------------------------------------------------------------------------

class TestRunDefaults:
    def test_id_auto_generated(self):
        """每次创建 id 不同（UUID4）。"""
        r1, r2 = Run(), Run()
        assert r1.id != r2.id

    def test_trace_id_auto_generated(self):
        """trace_id 默认等于 id（顶层 Run 自成一棵树）。"""
        r = Run()
        # 默认 trace_id 是独立的 UUID，不等于 id
        assert r.trace_id  # 非空
        assert len(r.trace_id) == 36  # UUID4 格式

    def test_parent_run_id_none_by_default(self):
        r = Run()
        assert r.parent_run_id is None
        assert r.is_root is True

    def test_default_run_type(self):
        r = Run()
        assert r.run_type is RunType.CUSTOM

    def test_start_time_is_utc_iso(self):
        """start_time 应为合法的 ISO 8601 UTC 字符串。"""
        r = Run()
        dt = datetime.fromisoformat(r.start_time)
        assert dt.tzinfo is not None  # 有时区信息

    def test_mutable_defaults_are_isolated(self):
        """inputs / outputs / metadata / tags 等可变默认值不共享同一对象。"""
        r1, r2 = Run(), Run()
        r1.inputs["key"] = "value"
        assert "key" not in r2.inputs

        r1.tags.append("x")
        assert "x" not in r2.tags


# ---------------------------------------------------------------------------
# 序列化往返（round-trip）
# ---------------------------------------------------------------------------

class TestSerialization:
    def _make_full_run(self) -> Run:
        """创建一个填充了所有字段的 Run，用于验证序列化完整性。"""
        return Run(
            id="run-001",
            trace_id="trace-abc",
            parent_run_id="run-000",
            name="call_llm",
            run_type=RunType.LLM,
            inputs={"prompt": "hello", "temperature": 0.7},
            outputs={"text": "world"},
            error=None,
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-01-01T00:00:01+00:00",
            metadata={"model": "gpt-4o"},
            tags=["prod", "test"],
            exec_order=2,
        )

    def test_to_dict_run_type_is_string(self):
        """to_dict 输出的 run_type 必须是字符串，而非枚举对象。"""
        d = self._make_full_run().to_dict()
        assert isinstance(d["run_type"], str)
        assert d["run_type"] == "llm"

    def test_round_trip_all_fields(self):
        """from_dict(run.to_dict()) 还原后所有字段与原始 Run 相等。"""
        original = self._make_full_run()
        restored = Run.from_dict(original.to_dict())

        assert restored.id == original.id
        assert restored.trace_id == original.trace_id
        assert restored.parent_run_id == original.parent_run_id
        assert restored.name == original.name
        assert restored.run_type is original.run_type
        assert restored.inputs == original.inputs
        assert restored.outputs == original.outputs
        assert restored.error == original.error
        assert restored.start_time == original.start_time
        assert restored.end_time == original.end_time
        assert restored.metadata == original.metadata
        assert restored.tags == original.tags
        assert restored.exec_order == original.exec_order

    def test_round_trip_via_json(self):
        """经过 json.dumps → json.loads 后 from_dict 仍能正确还原。"""
        original = self._make_full_run()
        json_str = json.dumps(original.to_dict())
        restored = Run.from_dict(json.loads(json_str))
        assert restored.id == original.id
        assert restored.run_type is RunType.LLM

    def test_round_trip_none_fields(self):
        """None 值字段（outputs、error、end_time、parent_run_id）往返后仍为 None。"""
        r = Run(name="minimal")
        restored = Run.from_dict(r.to_dict())
        assert restored.outputs is None
        assert restored.error is None
        assert restored.end_time is None
        assert restored.parent_run_id is None

    def test_from_dict_accepts_string_run_type(self):
        """from_dict 中 run_type 为字符串时应正确转换为枚举。"""
        d = Run(run_type=RunType.TOOL).to_dict()
        assert isinstance(d["run_type"], str)
        restored = Run.from_dict(d)
        assert restored.run_type is RunType.TOOL

    def test_from_dict_accepts_enum_run_type(self):
        """from_dict 中 run_type 已经是枚举时不应报错。"""
        d = Run(run_type=RunType.AGENT).to_dict()
        d["run_type"] = RunType.AGENT  # 直接传枚举
        restored = Run.from_dict(d)
        assert restored.run_type is RunType.AGENT


# ---------------------------------------------------------------------------
# 便利属性
# ---------------------------------------------------------------------------

class TestConvenienceProperties:
    def test_duration_ms_none_when_no_end_time(self):
        r = Run()
        assert r.duration_ms is None

    def test_duration_ms_calculated_correctly(self):
        r = Run(
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-01-01T00:00:01.500000+00:00",
        )
        assert abs(r.duration_ms - 1500.0) < 0.01

    def test_is_root_true_without_parent(self):
        r = Run()
        assert r.is_root is True

    def test_is_root_false_with_parent(self):
        r = Run(parent_run_id="some-parent-id")
        assert r.is_root is False

    def test_has_error_false_by_default(self):
        r = Run()
        assert r.has_error is False

    def test_has_error_true_when_error_set(self):
        r = Run(error="ValueError: something went wrong")
        assert r.has_error is True

    def test_repr_contains_key_info(self):
        r = Run(name="my_func", run_type=RunType.CHAIN)
        s = repr(r)
        assert "chain" in s
        assert "my_func" in s
