"""
test_traces_api.py — Trace 查询 API 测试

测试 GET /api/traces、GET /api/traces/{trace_id}、GET /api/runs/{run_id} 端点
"""

import pytest
import tempfile
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone, timedelta

from app.main import create_app
from app.db.base import Base, get_db
from app.models.run import Run as RunORM


@pytest.fixture
def test_db():
    """创建测试数据库（临时 SQLite 文件）"""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
        os.close(db_fd)
        os.unlink(db_path)


@pytest.fixture
def client(test_db):
    """创建测试客户端（FastAPI TestClient）"""
    app = create_app()

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_trace(test_db):
    """创建示例 trace（3 层树形结构）

    结构：
      root (trace-1)
        ├─ child-1
        │   └─ grandchild-1
        └─ child-2
    """
    now = datetime.now(timezone.utc)

    # 根节点
    root = RunORM(
        id="run-root",
        trace_id="trace-1",
        parent_run_id=None,
        name="root_task",
        run_type="chain",
        inputs={"arg": "value"},
        outputs={"result": "success"},
        error=None,
        start_time=now.isoformat(),
        end_time=(now + timedelta(seconds=2)).isoformat(),
        run_metadata={"version": "1.0"},
        tags=["production", "critical"],
        exec_order=0,
    )

    # 子节点 1
    child1 = RunORM(
        id="run-child-1",
        trace_id="trace-1",
        parent_run_id="run-root",
        name="child_task_1",
        run_type="tool",
        inputs={},
        outputs={},
        error=None,
        start_time=(now + timedelta(milliseconds=100)).isoformat(),
        end_time=(now + timedelta(milliseconds=500)).isoformat(),
        run_metadata={},
        tags=[],
        exec_order=0,
    )

    # 孙节点
    grandchild = RunORM(
        id="run-grandchild-1",
        trace_id="trace-1",
        parent_run_id="run-child-1",
        name="grandchild_task",
        run_type="llm",
        inputs={"prompt": "test"},
        outputs={"response": "ok"},
        error=None,
        start_time=(now + timedelta(milliseconds=150)).isoformat(),
        end_time=(now + timedelta(milliseconds=400)).isoformat(),
        run_metadata={},
        tags=[],
        exec_order=0,
    )

    # 子节点 2
    child2 = RunORM(
        id="run-child-2",
        trace_id="trace-1",
        parent_run_id="run-root",
        name="child_task_2",
        run_type="tool",
        inputs={},
        outputs={},
        error=None,
        start_time=(now + timedelta(milliseconds=600)).isoformat(),
        end_time=(now + timedelta(seconds=1)).isoformat(),
        run_metadata={},
        tags=[],
        exec_order=1,
    )

    test_db.add_all([root, child1, grandchild, child2])
    test_db.commit()

    return {
        "trace_id": "trace-1",
        "root": root,
        "child1": child1,
        "child2": child2,
        "grandchild": grandchild,
    }


@pytest.fixture
def multiple_traces(test_db):
    """创建多个 traces（用于列表测试）"""
    now = datetime.now(timezone.utc)
    traces = []

    for i in range(5):
        trace_id = f"trace-{i}"
        root = RunORM(
            id=f"run-root-{i}",
            trace_id=trace_id,
            parent_run_id=None,
            name=f"task_{i}",
            run_type="chain" if i % 2 == 0 else "llm",
            inputs={},
            outputs={},
            error=f"Error {i}" if i == 3 else None,  # trace-3 有错误
            start_time=(now - timedelta(minutes=i)).isoformat(),
            end_time=(now - timedelta(minutes=i) + timedelta(seconds=i + 1)).isoformat(),
            run_metadata={},
            tags=["production"] if i < 3 else [],
            exec_order=0,
        )
        test_db.add(root)
        traces.append(root)

    test_db.commit()
    return traces


# ---------------------------------------------------------------------------
# GET /api/traces - 分页列表测试
# ---------------------------------------------------------------------------


def test_list_traces_default(client, multiple_traces):
    """测试：默认分页（第 1 页，50 条/页）"""
    response = client.get("/api/traces")

    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "total_pages" in data

    assert data["total"] == 5
    assert data["page"] == 1
    assert data["page_size"] == 50
    assert len(data["items"]) == 5


def test_list_traces_pagination(client, multiple_traces):
    """测试：分页（2 条/页）"""
    # 第 1 页
    response1 = client.get("/api/traces?page=1&page_size=2")
    assert response1.status_code == 200
    data1 = response1.json()
    assert len(data1["items"]) == 2
    assert data1["page"] == 1
    assert data1["total_pages"] == 3

    # 第 2 页
    response2 = client.get("/api/traces?page=2&page_size=2")
    assert response2.status_code == 200
    data2 = response2.json()
    assert len(data2["items"]) == 2
    assert data2["page"] == 2

    # 第 3 页
    response3 = client.get("/api/traces?page=3&page_size=2")
    assert response3.status_code == 200
    data3 = response3.json()
    assert len(data3["items"]) == 1
    assert data3["page"] == 3


def test_list_traces_filter_run_type(client, multiple_traces):
    """测试：按 run_type 过滤"""
    response = client.get("/api/traces?run_type=chain")

    assert response.status_code == 200
    data = response.json()

    # 应该有 3 个 chain 类型（trace-0, trace-2, trace-4）
    assert data["total"] == 3
    assert all(item["run_type"] == "chain" for item in data["items"])


def test_list_traces_filter_has_error(client, multiple_traces):
    """测试：过滤有错误的 trace"""
    response = client.get("/api/traces?has_error=true")

    assert response.status_code == 200
    data = response.json()

    # 应该有 1 个有错误（trace-3）
    assert data["total"] == 1
    assert data["items"][0]["status"] == "error"
    assert data["items"][0]["error"] is not None


def test_list_traces_filter_tags(client, multiple_traces):
    """测试：按 tags 过滤"""
    response = client.get("/api/traces?tags=production")

    assert response.status_code == 200
    data = response.json()

    # 应该有 3 个（trace-0, trace-1, trace-2）
    assert data["total"] == 3


def test_list_traces_empty_result(client, test_db):
    """测试：查询结果为空"""
    response = client.get("/api/traces")

    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 0
    assert len(data["items"]) == 0
    assert data["page"] == 1
    assert data["total_pages"] == 0


# ---------------------------------------------------------------------------
# GET /api/traces/{trace_id} - 树形 JSON 测试
# ---------------------------------------------------------------------------


def test_get_trace_tree_success(client, sample_trace):
    """测试：获取完整树形 JSON"""
    trace_id = sample_trace["trace_id"]
    response = client.get(f"/api/traces/{trace_id}")

    assert response.status_code == 200
    tree = response.json()

    # 验证根节点
    assert tree["id"] == "run-root"
    assert tree["trace_id"] == trace_id
    assert tree["parent_run_id"] is None
    assert tree["name"] == "root_task"
    assert tree["run_type"] == "chain"

    # 验证计算字段
    assert "duration_ms" in tree
    assert "status" in tree
    assert tree["status"] == "success"

    # 验证子节点
    assert "children" in tree
    assert len(tree["children"]) == 2

    # 验证子节点 1（应该有孙节点）
    child1 = tree["children"][0]
    assert child1["id"] == "run-child-1"
    assert child1["name"] == "child_task_1"
    assert len(child1["children"]) == 1

    # 验证孙节点
    grandchild = child1["children"][0]
    assert grandchild["id"] == "run-grandchild-1"
    assert grandchild["name"] == "grandchild_task"
    assert len(grandchild["children"]) == 0  # 叶子节点

    # 验证子节点 2（无子节点）
    child2 = tree["children"][1]
    assert child2["id"] == "run-child-2"
    assert child2["name"] == "child_task_2"
    assert len(child2["children"]) == 0


def test_get_trace_tree_not_found(client):
    """测试：查询不存在的 trace"""
    response = client.get("/api/traces/non-existent-trace")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_trace_tree_structure_validation(client, sample_trace):
    """测试：验证树形结构的正确性"""
    trace_id = sample_trace["trace_id"]
    response = client.get(f"/api/traces/{trace_id}")

    assert response.status_code == 200
    tree = response.json()

    # 递归验证树形结构
    def validate_node(node, parent_id=None):
        """递归验证节点结构"""
        # 必需字段
        assert "id" in node
        assert "trace_id" in node
        assert "parent_run_id" in node
        assert "name" in node
        assert "run_type" in node
        assert "children" in node

        # 验证 parent_run_id 关系
        assert node["parent_run_id"] == parent_id

        # 验证所有子节点
        for child in node["children"]:
            validate_node(child, parent_id=node["id"])

    validate_node(tree, parent_id=None)


# ---------------------------------------------------------------------------
# GET /api/traces/{trace_id}/runs/{run_id} - 单个 Run 测试
# ---------------------------------------------------------------------------


def test_get_run_success(client, sample_trace):
    """测试：获取单个 Run"""
    trace_id = sample_trace["trace_id"]
    run_id = sample_trace["root"].id

    response = client.get(f"/api/traces/{trace_id}/runs/{run_id}")

    assert response.status_code == 200
    run = response.json()

    assert run["id"] == run_id
    assert run["trace_id"] == trace_id
    assert run["name"] == "root_task"
    assert run["run_type"] == "chain"

    # 验证所有字段都存在
    assert "inputs" in run
    assert "outputs" in run
    assert "metadata" in run
    assert "tags" in run
    assert "start_time" in run
    assert "end_time" in run


def test_get_run_not_found(client, sample_trace):
    """测试：查询不存在的 Run"""
    trace_id = sample_trace["trace_id"]
    response = client.get(f"/api/traces/{trace_id}/runs/non-existent-run")

    assert response.status_code == 404


def test_get_run_wrong_trace(client, sample_trace):
    """测试：Run 不属于指定的 Trace"""
    run_id = sample_trace["root"].id
    wrong_trace_id = "wrong-trace-id"

    response = client.get(f"/api/traces/{wrong_trace_id}/runs/{run_id}")

    assert response.status_code == 404
    assert "does not belong to trace" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 边界情况测试
# ---------------------------------------------------------------------------


def test_list_traces_invalid_page(client):
    """测试：无效的页码"""
    response = client.get("/api/traces?page=0")
    assert response.status_code == 422  # Pydantic 验证失败


def test_list_traces_invalid_page_size(client):
    """测试：无效的 page_size"""
    response = client.get("/api/traces?page_size=0")
    assert response.status_code == 422

    response = client.get("/api/traces?page_size=10000")
    assert response.status_code == 422


def test_tree_ordering_by_exec_order(client, test_db):
    """测试：子节点按 exec_order 排序"""
    now = datetime.now(timezone.utc)

    # 创建根节点
    root = RunORM(
        id="run-root",
        trace_id="trace-order",
        parent_run_id=None,
        name="root",
        run_type="chain",
        inputs={},
        outputs={},
        error=None,
        start_time=now.isoformat(),
        end_time=(now + timedelta(seconds=1)).isoformat(),
        run_metadata={},
        tags=[],
        exec_order=0,
    )

    # 创建 3 个子节点（乱序插入）
    child3 = RunORM(
        id="child-3",
        trace_id="trace-order",
        parent_run_id="run-root",
        name="child_3",
        run_type="tool",
        inputs={},
        outputs={},
        error=None,
        start_time=now.isoformat(),
        end_time=(now + timedelta(seconds=1)).isoformat(),
        run_metadata={},
        tags=[],
        exec_order=2,  # 第 3 个
    )

    child1 = RunORM(
        id="child-1",
        trace_id="trace-order",
        parent_run_id="run-root",
        name="child_1",
        run_type="tool",
        inputs={},
        outputs={},
        error=None,
        start_time=now.isoformat(),
        end_time=(now + timedelta(seconds=1)).isoformat(),
        run_metadata={},
        tags=[],
        exec_order=0,  # 第 1 个
    )

    child2 = RunORM(
        id="child-2",
        trace_id="trace-order",
        parent_run_id="run-root",
        name="child_2",
        run_type="tool",
        inputs={},
        outputs={},
        error=None,
        start_time=now.isoformat(),
        end_time=(now + timedelta(seconds=1)).isoformat(),
        run_metadata={},
        tags=[],
        exec_order=1,  # 第 2 个
    )

    test_db.add_all([root, child3, child1, child2])
    test_db.commit()

    # 获取树形 JSON
    response = client.get("/api/traces/trace-order")
    assert response.status_code == 200
    tree = response.json()

    # 验证子节点按 exec_order 排序
    children = tree["children"]
    assert len(children) == 3
    assert children[0]["id"] == "child-1"  # exec_order=0
    assert children[1]["id"] == "child-2"  # exec_order=1
    assert children[2]["id"] == "child-3"  # exec_order=2
