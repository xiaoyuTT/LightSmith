"""
sqlite.py — LightSmith 本地 SQLite 存储

提供 RunWriter 用于持久化 Run 记录：
  - 同步写入（RunWriter.save）—— 线程安全，内部 Lock 保护
  - 异步写入（RunWriter.async_save）—— loop.run_in_executor 包装，不阻塞事件循环
  - 树查询（RunWriter.get_trace）—— 一次查询取出整棵树

默认存储路径：~/.lightsmith/traces.db
可通过环境变量 LIGHTSMITH_DB_PATH 覆盖。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from lightsmith.models import Run, RunType


# ---------------------------------------------------------------------------
# 默认路径
# ---------------------------------------------------------------------------

def _default_db_path() -> str:
    """返回数据库文件路径：优先使用环境变量，否则 ~/.lightsmith/traces.db。"""
    env = os.environ.get("LIGHTSMITH_DB_PATH")
    if env:
        return env
    return str(Path.home() / ".lightsmith" / "traces.db")


# ---------------------------------------------------------------------------
# DDL：建表 + 索引
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    trace_id      TEXT NOT NULL,
    parent_run_id TEXT,
    name          TEXT NOT NULL,
    run_type      TEXT NOT NULL,
    inputs        TEXT NOT NULL DEFAULT '{}',
    outputs       TEXT,
    error         TEXT,
    start_time    TEXT NOT NULL,
    end_time      TEXT,
    metadata      TEXT NOT NULL DEFAULT '{}',
    tags          TEXT NOT NULL DEFAULT '[]',
    exec_order    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_trace_id
    ON runs (trace_id);

CREATE INDEX IF NOT EXISTS idx_runs_parent_run_id
    ON runs (parent_run_id);

CREATE INDEX IF NOT EXISTS idx_runs_start_time
    ON runs (start_time);
"""

# 同一 run.id 重复写入时静默忽略，保证幂等性
_INSERT_SQL = """
INSERT OR IGNORE INTO runs
    (id, trace_id, parent_run_id, name, run_type, inputs, outputs,
     error, start_time, end_time, metadata, tags, exec_order)
VALUES
    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# 按 exec_order 升序取出整棵树；exec_order 相同时再按 start_time 保证稳定排序
_SELECT_TRACE_SQL = """
SELECT id, trace_id, parent_run_id, name, run_type, inputs, outputs,
       error, start_time, end_time, metadata, tags, exec_order
FROM   runs
WHERE  trace_id = ?
ORDER  BY exec_order ASC, start_time ASC
"""


# ---------------------------------------------------------------------------
# RunWriter
# ---------------------------------------------------------------------------

class RunWriter:
    """将 Run 对象持久化到本地 SQLite 数据库。

    线程安全：内部使用 threading.Lock 保护连接，允许多线程并发写入。
    同一进程内建议共享一个 RunWriter 实例（全局单例，见 get_default_writer()）。

    Args:
        db_path: SQLite 数据库文件路径。
                 None 时依次检查 LIGHTSMITH_DB_PATH 环境变量，
                 未设置则使用 ~/.lightsmith/traces.db。
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _default_db_path()
        self._lock = threading.Lock()

        # 建目录 + 打开连接 + 建表（全在构造期完成，失败立即抛出）
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,  # 线程安全由 _lock 保证
        )
        self._conn.row_factory = sqlite3.Row
        # executescript 会先 COMMIT 未提交事务，再逐句执行 DDL
        self._conn.executescript(_DDL)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _run_to_row(run: Run) -> tuple:
        """将 Run 转为 INSERT 参数 tuple（与 _INSERT_SQL 占位符一一对应）。"""
        return (
            run.id,
            run.trace_id,
            run.parent_run_id,
            run.name,
            run.run_type.value,
            json.dumps(run.inputs, ensure_ascii=False),
            json.dumps(run.outputs, ensure_ascii=False) if run.outputs is not None else None,
            run.error,
            run.start_time,
            run.end_time,
            json.dumps(run.metadata, ensure_ascii=False),
            json.dumps(run.tags, ensure_ascii=False),
            run.exec_order,
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> Run:
        """将 SQLite 行还原为 Run 对象（JSON 列反序列化）。"""
        return Run(
            id=row["id"],
            trace_id=row["trace_id"],
            parent_run_id=row["parent_run_id"],
            name=row["name"],
            run_type=RunType(row["run_type"]),
            inputs=json.loads(row["inputs"]),
            outputs=json.loads(row["outputs"]) if row["outputs"] is not None else None,
            error=row["error"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            metadata=json.loads(row["metadata"]),
            tags=json.loads(row["tags"]),
            exec_order=row["exec_order"],
        )

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def save(self, run: Run) -> None:
        """同步写入一条 Run，线程安全。

        同一 run.id 重复写入时静默忽略（INSERT OR IGNORE），保证幂等性。
        写入失败时异常向上抛出（由调用方 decorators._emit_run 捕获并静默）。

        Args:
            run: 要持久化的 Run 对象（应已完成，即 end_time 已设置）。
        """
        row = self._run_to_row(run)
        with self._lock:
            self._conn.execute(_INSERT_SQL, row)
            self._conn.commit()

    async def async_save(self, run: Run) -> None:
        """异步写入一条 Run，不阻塞事件循环。

        在当前事件循环的默认线程池（ThreadPoolExecutor）中运行同步 save()。
        适用于在 async 函数内直接 await 存储，无需手动切线程。

        Args:
            run: 要持久化的 Run 对象。
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.save, run)

    def get_trace(self, trace_id: str) -> list[Run]:
        """查询某条 trace 的全部 Run，按 exec_order 升序排列。

        一次 SQL 查询取出整棵调用树，调用方可根据 parent_run_id 重建树结构。
        P0.5 CLI 工具和 P1.4 后端查询 API 均依赖此方法。

        Args:
            trace_id: 要查询的 trace 根 ID（= 根 Run 的 trace_id）。

        Returns:
            该 trace 下所有 Run 的列表，按 exec_order ASC, start_time ASC 排序。
            若 trace 不存在，返回空列表。
        """
        with self._lock:
            cursor = self._conn.execute(_SELECT_TRACE_SQL, (trace_id,))
            return [self._row_to_run(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """关闭数据库连接。

        进程正常退出时 Python 会自动关闭，通常不需要手动调用。
        在测试中用于确保临时文件可被安全删除。
        """
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# 全局默认写入器（单例，延迟初始化）
# ---------------------------------------------------------------------------

_default_writer: Optional[RunWriter] = None
_default_writer_lock = threading.Lock()


def get_default_writer() -> RunWriter:
    """返回进程级别的默认 RunWriter 单例，线程安全。

    首次调用时按 _default_db_path() 初始化，后续调用复用同一实例。

    用法：
        from lightsmith.storage.sqlite import get_default_writer
        from lightsmith.decorators import set_run_writer

        set_run_writer(get_default_writer().save)
    """
    global _default_writer
    if _default_writer is None:
        with _default_writer_lock:
            if _default_writer is None:
                _default_writer = RunWriter()
    return _default_writer
