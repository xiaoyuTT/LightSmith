"""
快速验证脚本：测试 HTTP Transport 是否正常工作

前置条件：
  后端服务已启动：cd backend && uvicorn app.main:app --reload

运行方式：
  python examples/quick_test.py
"""

import sys
import os
import time

# 添加 SDK 到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import lightsmith as ls
from lightsmith.models import RunType


def main():
    print("=== LightSmith HTTP Transport 快速验证 ===\n")

    # 初始化 HTTP Transport
    print("1. 初始化 HTTP Transport...")
    writer = ls.init_http_transport()
    print("   ✓ 已连接到 http://localhost:8000\n")

    # 定义测试函数
    @ls.traceable(name="test_function", run_type=RunType.CHAIN)
    def test_function(x: int):
        print(f"   执行 test_function({x})")
        return {"result": x * 2}

    # 执行函数
    print("2. 执行被追踪的函数...")
    for i in range(5):
        test_function(i)

    print(f"   ✓ 已执行 5 个函数调用\n")

    # 手动 flush（立即上报）
    print("3. 手动 flush（立即上报到后端）...")
    writer.flush()
    time.sleep(0.5)  # 等待 HTTP 请求完成
    print("   ✓ 数据已上报\n")

    # 验证
    print("4. 验证数据：")
    print("   访问：http://localhost:8000/api/traces")
    print("   应该能看到 5 条 trace\n")

    print("=== 验证完成 ===")


if __name__ == "__main__":
    main()
