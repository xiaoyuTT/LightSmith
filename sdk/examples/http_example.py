"""
HTTP Transport 示例：演示如何使用 HTTP 上报将 Run 数据发送到后端

前置条件：
1. 后端服务已启动：cd backend && uvicorn app.main:app --reload
2. 后端地址：http://localhost:8000

运行方式：
  python examples/http_example.py
"""

import sys
import os
import time

# 添加 SDK 到 Python 路径（开发环境）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import lightsmith as ls
from lightsmith.models import RunType


def main():
    """主函数：演示 HTTP Transport 的使用"""

    print("=== LightSmith HTTP Transport 示例 ===\n")

    # 方式 1：使用默认配置（从环境变量读取）
    print("1. 初始化 HTTP Transport（使用默认配置）")
    ls.init_http_transport()
    print("   - 后端地址：http://localhost:8000（默认）")
    print("   - 批量大小：100 条")
    print("   - Flush 间隔：5 秒\n")

    # 方式 2：使用自定义配置
    # ls.init_http_transport(
    #     endpoint="http://localhost:8000",
    #     max_batch_size=50,
    #     flush_interval=3.0,
    # )

    # 方式 3：使用 init_auto（根据环境变量自动选择）
    # 设置环境变量 LIGHTSMITH_LOCAL=true 使用 SQLite，否则使用 HTTP
    # ls.init_auto()

    # 定义一些被追踪的函数
    @ls.traceable(name="fetch_user", run_type=RunType.TOOL)
    def fetch_user(user_id: int):
        """模拟从数据库获取用户"""
        time.sleep(0.1)
        return {"id": user_id, "name": f"User_{user_id}", "email": f"user{user_id}@example.com"}

    @ls.traceable(name="process_user", run_type=RunType.CHAIN)
    def process_user(user_id: int):
        """处理用户数据"""
        print(f"   Processing user {user_id}...")

        # 嵌套调用（自动建立父子关系）
        user = fetch_user(user_id)

        # 模拟处理时间
        time.sleep(0.05)

        return {
            "processed": True,
            "user": user,
            "timestamp": time.time(),
        }

    # 执行多个追踪函数
    print("2. 执行被追踪的函数...")
    for i in range(1, 4):
        result = process_user(i)
        print(f"   ✓ User {i} processed")

    print("\n3. 等待批量上报...")
    print("   - Run 数据会在队列满（100 条）或 5 秒后自动上报到后端")
    print("   - 当前已添加 6 条 Run（3 个根 Run + 3 个子 Run）")
    print("   - 等待 5 秒后会触发自动 flush...\n")

    # 等待定时器触发（或者手动 flush）
    time.sleep(6)

    print("4. 数据已上报到后端！")
    print("\n5. 查看数据：")
    print("   - 浏览器访问：http://localhost:8000/api/docs")
    print("   - 或使用 curl：")
    print("     curl http://localhost:8000/api/traces")
    print("\n=== 示例完成 ===")


if __name__ == "__main__":
    main()
