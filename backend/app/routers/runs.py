"""
runs.py — Run 摄入 API 路由

提供批量摄入接口：POST /api/runs/batch
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.db.base import get_db
from app.db.repository import RunRepository
from app.models.run import Run as RunORM
from app.schemas.run import BatchRunsRequest, BatchRunsResponse
from app.config import get_settings

router = APIRouter(prefix="/runs", tags=["Runs"])


@router.post("/batch", response_model=BatchRunsResponse, status_code=status.HTTP_201_CREATED)
def batch_ingest(
    request: BatchRunsRequest,
    db: Session = Depends(get_db),
):
    """批量摄入 Run 数据

    接收 SDK 上报的 Run 批次，写入数据库。
    同一 run.id 重复提交时静默忽略（幂等性保证）。

    Args:
        request: 批量请求体，包含 Run 列表
        db: 数据库会话（依赖注入）

    Returns:
        BatchRunsResponse: {"accepted": N, "duplicates": M, "total": K}

    Raises:
        HTTPException 400: 批量大小超过限制
        HTTPException 500: 数据库错误
    """
    settings = get_settings()

    # 验证批量大小（二次检查，Pydantic 已做第一层验证）
    if len(request.runs) > settings.max_batch_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"批量大小不能超过 {settings.max_batch_size}，收到: {len(request.runs)}",
        )

    # 将 Pydantic 模型转换为 ORM 模型
    orm_runs = []
    for run_schema in request.runs:
        # 注意：metadata 字段在 API 层叫 metadata，在 ORM 层叫 run_metadata
        orm_run = RunORM(
            id=run_schema.id,
            trace_id=run_schema.trace_id,
            parent_run_id=run_schema.parent_run_id,
            name=run_schema.name,
            run_type=run_schema.run_type,
            inputs=run_schema.inputs,
            outputs=run_schema.outputs,
            error=run_schema.error,
            start_time=run_schema.start_time,
            end_time=run_schema.end_time,
            run_metadata=run_schema.metadata,  # API metadata → ORM run_metadata
            tags=run_schema.tags,
            exec_order=run_schema.exec_order,
        )
        orm_runs.append(orm_run)

    # 调用 Repository 保存
    repo = RunRepository(db)
    try:
        result = repo.save_batch(orm_runs)
        return BatchRunsResponse(
            accepted=result["accepted"],
            duplicates=result["duplicates"],
            total=len(request.runs),
        )
    except SQLAlchemyError as e:
        # 数据库错误：打印日志，返回 500
        print(f"[ERROR] Database error in batch_ingest: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="数据库错误，请稍后重试",
        )
