"""
test_api.py — 手动集成测试脚本

测试 Run 摄入 API 的真实 HTTP 行为。

用法：
1. 启动服务（终端1）：uvicorn app.main:app --reload --port 8000
2. 运行此脚本（终端2）：python scripts/test_api.py

注意：
- 这是手动集成测试，需要先启动服务
- 单元测试请使用：python -m pytest tests/
- 使用 requests 库发送真实 HTTP 请求
"""

import requests
import json
from datetime import datetime, timezone

# API 端点
BASE_URL = "http://localhost:8000"
BATCH_ENDPOINT = f"{BASE_URL}/api/runs/batch"
HEALTH_ENDPOINT = f"{BASE_URL}/health"


def test_health_check():
    """测试健康检查端点"""
    print("=" * 60)
    print("测试：健康检查")
    print("=" * 60)

    response = requests.get(HEALTH_ENDPOINT)
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print()


def test_single_run():
    """测试：提交单个 Run"""
    print("=" * 60)
    print("测试：提交单个 Run")
    print("=" * 60)

    data = {
        "runs": [
            {
                "id": "test-run-001",
                "trace_id": "test-trace-001",
                "parent_run_id": None,
                "name": "test_function",
                "run_type": "chain",
                "inputs": {"arg1": "value1", "arg2": 42},
                "outputs": {"result": "success"},
                "error": None,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "metadata": {"version": "1.0", "env": "test"},
                "tags": ["test", "manual"],
                "exec_order": 0,
            }
        ]
    }

    print(f"请求体: {json.dumps(data, indent=2, ensure_ascii=False)}")

    response = requests.post(BATCH_ENDPOINT, json=data)
    print(f"\n状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print()


def test_multiple_runs():
    """测试：批量提交多个 Run"""
    print("=" * 60)
    print("测试：批量提交多个 Run")
    print("=" * 60)

    runs = []
    for i in range(5):
        runs.append({
            "id": f"test-run-00{i+2}",
            "trace_id": "test-trace-002",
            "parent_run_id": None,
            "name": f"test_function_{i}",
            "run_type": "chain",
            "inputs": {"index": i},
            "outputs": {"result": f"done_{i}"},
            "error": None,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": datetime.now(timezone.utc).isoformat(),
            "metadata": {},
            "tags": ["batch", "test"],
            "exec_order": i,
        })

    data = {"runs": runs}

    print(f"请求体: {len(runs)} 个 Run")

    response = requests.post(BATCH_ENDPOINT, json=data)
    print(f"\n状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print()


def test_idempotency():
    """测试：幂等性（重复提交同一 Run）"""
    print("=" * 60)
    print("测试：幂等性（重复提交）")
    print("=" * 60)

    data = {
        "runs": [
            {
                "id": "test-run-idempotent",
                "trace_id": "test-trace-003",
                "parent_run_id": None,
                "name": "idempotent_test",
                "run_type": "chain",
                "inputs": {},
                "outputs": {},
                "error": None,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "metadata": {},
                "tags": ["idempotent"],
                "exec_order": 0,
            }
        ]
    }

    # 第一次提交
    print("第一次提交:")
    response1 = requests.post(BATCH_ENDPOINT, json=data)
    print(f"状态码: {response1.status_code}")
    print(f"响应: {json.dumps(response1.json(), indent=2, ensure_ascii=False)}")

    # 第二次提交（应该被忽略）
    print("\n第二次提交（应该被忽略）:")
    response2 = requests.post(BATCH_ENDPOINT, json=data)
    print(f"状态码: {response2.status_code}")
    print(f"响应: {json.dumps(response2.json(), indent=2, ensure_ascii=False)}")
    print()


def test_error_run():
    """测试：带 error 的 Run"""
    print("=" * 60)
    print("测试：带 error 的 Run")
    print("=" * 60)

    data = {
        "runs": [
            {
                "id": "test-run-error",
                "trace_id": "test-trace-004",
                "parent_run_id": None,
                "name": "failing_function",
                "run_type": "chain",
                "inputs": {"arg": "bad_value"},
                "outputs": None,
                "error": "ValueError: something went wrong\nTraceback...",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "metadata": {},
                "tags": ["error", "test"],
                "exec_order": 0,
            }
        ]
    }

    response = requests.post(BATCH_ENDPOINT, json=data)
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print()


def test_invalid_run_type():
    """测试：无效的 run_type（应该返回 422）"""
    print("=" * 60)
    print("测试：无效的 run_type（应该返回 422）")
    print("=" * 60)

    data = {
        "runs": [
            {
                "id": "test-run-invalid",
                "trace_id": "test-trace-005",
                "parent_run_id": None,
                "name": "invalid_test",
                "run_type": "invalid_type",  # 无效值
                "inputs": {},
                "outputs": {},
                "error": None,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "metadata": {},
                "tags": [],
                "exec_order": 0,
            }
        ]
    }

    response = requests.post(BATCH_ENDPOINT, json=data)
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("LightSmith Run 摄入 API 手动测试")
    print("=" * 60)
    print()

    try:
        # 测试健康检查
        test_health_check()

        # 测试单个 Run
        test_single_run()

        # 测试批量提交
        test_multiple_runs()

        # 测试幂等性
        test_idempotency()

        # 测试 error Run
        test_error_run()

        # 测试输入验证
        test_invalid_run_type()

        print("=" * 60)
        print("所有测试完成！")
        print("=" * 60)

    except requests.exceptions.ConnectionError:
        print("\n[错误] 无法连接到服务器，请确保服务已启动：")
        print("  uvicorn app.main:app --reload --port 8000")
    except Exception as e:
        print(f"\n[错误] 测试失败: {e}")
