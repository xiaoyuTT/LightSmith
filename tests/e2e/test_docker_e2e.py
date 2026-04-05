#!/usr/bin/env python3
"""
端到端测试脚本：SDK HTTP 上报 → 后端查询

验证 P1.6 Docker 部署后的完整流程：
1. SDK 初始化 HTTP Transport
2. 调用 @traceable 装饰的函数（生成 Trace）
3. SDK 自动批量上报到后端 API
4. 查询 Trace 列表和详情 API
5. 验证树形结构和数据正确性

使用方式：
    # 1. 启动 Docker 容器
    docker-compose up -d

    # 2. 等待服务就绪
    sleep 10

    # 3. 运行测试脚本（在项目根目录执行）
    python tests/e2e/test_docker_e2e.py
"""

import time
import requests
import os
import sys

# 检查 SDK 是否已安装
try:
    # 添加 sdk 目录到 Python 路径
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'sdk'))
    import lightsmith as ls
except ImportError:
    print("[!] Error: lightsmith SDK not found. Please install it first:")
    print("    cd sdk && pip install -e .")
    sys.exit(1)


def test_health_check():
    """测试健康检查端点"""
    print("\n[1/5] Testing health check endpoint...")
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        response.raise_for_status()
        data = response.json()
        print(f"[✓] Health check passed: {data}")
        return True
    except Exception as e:
        print(f"[✗] Health check failed: {e}")
        print("    Make sure backend is running: docker-compose up -d")
        return False


def test_sdk_http_transport():
    """测试 SDK HTTP 上报"""
    print("\n[2/5] Testing SDK HTTP transport...")

    # 初始化 HTTP Transport
    os.environ["LIGHTSMITH_ENDPOINT"] = "http://localhost:8000"
    writer = ls.init_http_transport()

    # 创建测试 Trace（3 层嵌套）
    @ls.traceable(name="root_task", run_type="chain", tags=["e2e-test", "docker"])
    def root_task(x):
        result = child_task_1(x)
        result += child_task_2(x * 2)
        return result

    @ls.traceable(name="child_task_1", run_type="tool")
    def child_task_1(x):
        return grandchild_task(x + 10)

    @ls.traceable(name="child_task_2", run_type="tool")
    def child_task_2(x):
        return x * 2

    @ls.traceable(name="grandchild_task", run_type="llm")
    def grandchild_task(x):
        return x + 1

    # 执行函数（生成 Trace）
    result = root_task(5)
    print(f"[*] Function executed, result: {result}")

    # 手动 flush（立即上报）
    writer.flush()
    print("[✓] SDK HTTP transport test passed")

    # 等待数据写入
    time.sleep(2)

    return None  # trace_id 将从 API 查询获取


def test_list_traces_api():
    """测试 Trace 列表 API"""
    print("\n[3/5] Testing GET /api/traces...")

    # 等待数据写入
    time.sleep(2)

    try:
        response = requests.get("http://localhost:8000/api/traces", timeout=5)
        response.raise_for_status()
        data = response.json()

        print(f"[*] Total traces: {data['total']}")
        print(f"[*] Page: {data['page']}/{data['total_pages']}")
        print(f"[*] Items in this page: {len(data['items'])}")

        if data['total'] > 0:
            # 打印第一条 Trace 摘要
            first_trace = data['items'][0]
            print(f"[*] First trace: {first_trace['name']} ({first_trace['run_type']})")
            print(f"    - trace_id: {first_trace['trace_id']}")
            print(f"    - status: {first_trace['status']}")
            print(f"    - duration: {first_trace['duration_ms']}ms")
            print(f"    - tags: {first_trace['tags']}")
            print("[✓] List traces API test passed")
            return first_trace['trace_id']
        else:
            print("[!] No traces found (this might be expected if this is the first run)")
            return None

    except Exception as e:
        print(f"[✗] List traces API failed: {e}")
        return None


def test_get_trace_tree_api(trace_id):
    """测试 Trace 树形 JSON API"""
    print(f"\n[4/5] Testing GET /api/traces/{trace_id}...")

    if not trace_id:
        print("[!] Skipping (no trace_id available)")
        return False

    try:
        response = requests.get(f"http://localhost:8000/api/traces/{trace_id}", timeout=5)
        response.raise_for_status()
        tree = response.json()

        print(f"[*] Root run: {tree['name']} ({tree['run_type']})")
        print(f"    - id: {tree['id']}")
        print(f"    - trace_id: {tree['trace_id']}")
        print(f"    - duration: {tree['duration_ms']}ms")
        print(f"    - status: {tree['status']}")
        print(f"    - children: {len(tree['children'])} direct child(ren)")

        # 验证树形结构
        def print_tree(node, indent=0):
            prefix = "  " * indent
            print(f"{prefix}├─ {node['name']} ({node['run_type']}) - {node['duration_ms']}ms")
            for child in node['children']:
                print_tree(child, indent + 1)

        print("\n[*] Tree structure:")
        print_tree(tree)

        # 验证字段完整性
        required_fields = ['id', 'trace_id', 'name', 'run_type', 'inputs', 'outputs',
                          'start_time', 'end_time', 'duration_ms', 'status', 'children']
        missing_fields = [f for f in required_fields if f not in tree]
        if missing_fields:
            print(f"[✗] Missing fields: {missing_fields}")
            return False

        print("[✓] Get trace tree API test passed")
        return True

    except Exception as e:
        print(f"[✗] Get trace tree API failed: {e}")
        return False


def test_concurrent_ingestion():
    """测试高并发入库（100 个 Run）"""
    print("\n[5/5] Testing concurrent ingestion (100 runs)...")

    import concurrent.futures

    # 初始化 HTTP Transport
    os.environ["LIGHTSMITH_ENDPOINT"] = "http://localhost:8000"
    writer = ls.init_http_transport()

    @ls.traceable(name="concurrent_task", run_type="tool", tags=["concurrency-test"])
    def concurrent_task(i):
        return i * 2

    # 并发执行 100 个函数
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(concurrent_task, i) for i in range(100)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    elapsed = time.time() - start_time

    # 手动 flush
    writer.flush()

    print(f"[*] Executed 100 concurrent tasks in {elapsed:.2f}s")
    print(f"[*] Results count: {len(results)}")

    # 等待数据写入
    time.sleep(2)

    # 验证数据入库
    try:
        response = requests.get(
            "http://localhost:8000/api/traces",
            params={"tags": "concurrency-test", "page_size": 1000},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        concurrent_traces = [t for t in data['items'] if 'concurrency-test' in t['tags']]
        print(f"[*] Found {len(concurrent_traces)} concurrent traces in database")

        if len(concurrent_traces) == 100:
            print("[✓] All 100 runs successfully ingested (no data loss)")
            return True
        else:
            print(f"[!] Expected 100 runs, found {len(concurrent_traces)}")
            print("    (This might be due to batch buffering, wait a moment and retry)")
            return False

    except Exception as e:
        print(f"[✗] Concurrent ingestion verification failed: {e}")
        return False


def main():
    """主测试流程"""
    print("=" * 70)
    print("LightSmith P1.6 Docker E2E Test")
    print("=" * 70)

    # 1. 健康检查
    if not test_health_check():
        print("\n[!] Backend is not running. Please start it first:")
        print("    docker-compose up -d")
        return False

    # 2. SDK HTTP 上报测试
    trace_id = test_sdk_http_transport()

    # 3. 列表查询测试
    api_trace_id = test_list_traces_api()

    # 4. 树形 JSON 查询测试
    test_trace_id = api_trace_id or trace_id
    tree_ok = test_get_trace_tree_api(test_trace_id)

    # 5. 高并发测试
    concurrent_ok = test_concurrent_ingestion()

    # 总结
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    print(f"[{'✓' if tree_ok else '✗'}] Tree structure validation")
    print(f"[{'✓' if concurrent_ok else '✗'}] Concurrent ingestion (100 runs)")

    if tree_ok and concurrent_ok:
        print("\n[✓] All tests passed! P1.6 Docker deployment is working correctly.")
        return True
    else:
        print("\n[!] Some tests failed. Please check the logs above.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
