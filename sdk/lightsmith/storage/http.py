"""
http.py — LightSmith HTTP Transport 层

提供 HttpWriter 用于向后端批量上报 Run 记录：
  - BatchBuffer：内存队列 + 定时 flush（满 100 条或 5s 触发）
  - HttpClient：向后端 POST /api/runs/batch，带重试（最多 3 次，指数退避）
  - HttpWriter：整合 BatchBuffer 和 HttpClient，提供与 SQLite writer 兼容的接口
  - atexit 钩子：进程退出时强制 flush 剩余数据

配置环境变量：
  - LIGHTSMITH_ENDPOINT: 后端 API 地址（如 http://localhost:8000）
  - LIGHTSMITH_API_KEY: API 密钥（预留，P3.2 启用鉴权时使用）

用法示例：
    from lightsmith.storage.http import HttpWriter
    from lightsmith.decorators import set_run_writer

    writer = HttpWriter(endpoint="http://localhost:8000")
    set_run_writer(writer.save)
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import threading
import time
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from lightsmith.models import Run


# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------

def _default_endpoint() -> str:
    """返回后端 API 地址：优先使用环境变量，否则默认 http://localhost:8000。"""
    return os.environ.get("LIGHTSMITH_ENDPOINT", "http://localhost:8000")


def _default_api_key() -> Optional[str]:
    """返回 API 密钥：从环境变量读取（预留，P3.2 启用鉴权时使用）。"""
    return os.environ.get("LIGHTSMITH_API_KEY")


# ---------------------------------------------------------------------------
# BatchBuffer：内存队列 + 定时 flush
# ---------------------------------------------------------------------------

class BatchBuffer:
    """内存队列，缓冲 Run 记录并在满足条件时触发 flush。

    触发条件：
      - 队列达到 max_size 条记录
      - 距上次 flush 超过 flush_interval 秒

    线程安全：内部使用 threading.Lock 保护队列和定时器。
    """

    def __init__(
        self,
        flush_callback: callable,
        max_size: int = 100,
        flush_interval: float = 5.0,
    ) -> None:
        """初始化 BatchBuffer。

        Args:
            flush_callback: 触发 flush 时调用的函数，接收 list[Run] 参数。
            max_size: 队列最大容量，达到时立即 flush（默认 100）。
            flush_interval: 定时 flush 间隔，单位秒（默认 5.0）。
        """
        self._flush_callback = flush_callback
        self._max_size = max_size
        self._flush_interval = flush_interval

        self._queue: list[Run] = []
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._shutdown = False

    def add(self, run: Run) -> None:
        """添加一条 Run 到队列。

        若队列满（达到 max_size），立即触发 flush。
        否则，若定时器未启动，启动定时器。

        Args:
            run: 要添加的 Run 对象。
        """
        if self._shutdown:
            return  # 已关闭，忽略新 Run

        should_flush = False

        with self._lock:
            self._queue.append(run)
            should_flush = len(self._queue) >= self._max_size

            # 如果队列满，在锁外 flush
            if not should_flush:
                # 否则，启动定时器（如果尚未启动）
                if self._timer is None:
                    self._timer = threading.Timer(self._flush_interval, self._timer_callback)
                    self._timer.daemon = True
                    self._timer.start()

        # 在锁外执行 flush（避免长时间持有锁）
        if should_flush:
            self._flush_now()

    def _ensure_timer(self) -> None:
        """确保定时器已启动（仅在队列非空且定时器未运行时启动）。

        注意：此方法已不再使用，定时器现在在 add() 中直接启动。
        """
        with self._lock:
            if self._timer is None and len(self._queue) > 0 and not self._shutdown:
                self._timer = threading.Timer(self._flush_interval, self._timer_callback)
                self._timer.daemon = True
                self._timer.start()

    def _timer_callback(self) -> None:
        """定时器回调，触发 flush。"""
        self._flush_now()

    def _flush_now(self) -> None:
        """立即 flush 队列中的所有 Run。"""
        with self._lock:
            if len(self._queue) == 0:
                return

            # 取出当前队列
            runs_to_flush = self._queue[:]
            self._queue.clear()

            # 取消定时器
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        # 在锁外调用 flush_callback，避免死锁
        try:
            self._flush_callback(runs_to_flush)
        except Exception:
            # flush 失败时静默忽略（不影响业务代码）
            pass

    def flush(self) -> None:
        """手动触发 flush（通常在进程退出时调用）。"""
        self._flush_now()

    def shutdown(self) -> None:
        """关闭 BatchBuffer，停止接收新 Run，flush 剩余数据。"""
        with self._lock:
            self._shutdown = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        # 在锁外 flush，避免死锁
        self._flush_now()


# ---------------------------------------------------------------------------
# HttpClient：向后端发送批量 Run 请求，带重试
# ---------------------------------------------------------------------------

class HttpClient:
    """向后端 API 发送批量 Run 上报请求，带重试（最多 3 次，指数退避）。

    请求格式：
      POST /api/runs/batch
      Content-Type: application/json
      Authorization: Bearer <api_key>  # 若配置了 api_key

      Body: {"runs": [{"id": "...", "trace_id": "...", ...}, ...]}

    响应格式：
      {"accepted": N, "duplicates": M, "total": K}
    """

    def __init__(
        self,
        endpoint: str,
        api_key: Optional[str] = None,
        max_retries: int = 3,
        timeout: float = 10.0,
    ) -> None:
        """初始化 HttpClient。

        Args:
            endpoint: 后端 API 地址（如 http://localhost:8000）。
            api_key: API 密钥（可选，预留鉴权）。
            max_retries: 最大重试次数（默认 3）。
            timeout: 请求超时时间，单位秒（默认 10.0）。
        """
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._max_retries = max_retries
        self._timeout = timeout

    def send_batch(self, runs: list[Run]) -> dict:
        """向后端发送批量 Run 上报请求。

        Args:
            runs: 要上报的 Run 列表。

        Returns:
            后端响应 dict：{"accepted": N, "duplicates": M, "total": K}

        Raises:
            Exception: 重试 max_retries 次后仍失败时抛出。
        """
        url = f"{self._endpoint}/api/runs/batch"

        # 构造请求体（将 Run 对象序列化为 dict）
        payload = {"runs": [run.to_dict() for run in runs]}
        body = json.dumps(payload).encode("utf-8")

        # 构造请求头
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        # 重试逻辑（指数退避）
        last_exception = None
        for attempt in range(self._max_retries):
            try:
                req = Request(url, data=body, headers=headers, method="POST")
                with urlopen(req, timeout=self._timeout) as response:
                    response_body = response.read().decode("utf-8")
                    return json.loads(response_body)
            except (HTTPError, URLError, TimeoutError) as e:
                last_exception = e
                if attempt < self._max_retries - 1:
                    # 指数退避：1s, 2s, 4s
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                continue
            except Exception as e:
                # 其他异常（如 JSON 解析失败）不重试，直接抛出
                raise

        # 重试耗尽，抛出最后一次异常
        raise last_exception


# ---------------------------------------------------------------------------
# HttpWriter：整合 BatchBuffer 和 HttpClient
# ---------------------------------------------------------------------------

class HttpWriter:
    """将 Run 对象通过 HTTP 批量上报到后端。

    提供与 SQLite writer 兼容的接口（save 方法），可直接注入到 @traceable 装饰器。

    自动注册 atexit 钩子和 SIGTERM handler，确保进程退出时 flush 剩余数据。

    Args:
        endpoint: 后端 API 地址（None 时从 LIGHTSMITH_ENDPOINT 读取）。
        api_key: API 密钥（None 时从 LIGHTSMITH_API_KEY 读取）。
        max_batch_size: 批量大小（默认 100）。
        flush_interval: flush 间隔（秒，默认 5.0）。
        max_retries: HTTP 请求最大重试次数（默认 3）。
        timeout: HTTP 请求超时时间（秒，默认 10.0）。
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        max_batch_size: int = 100,
        flush_interval: float = 5.0,
        max_retries: int = 3,
        timeout: float = 10.0,
    ) -> None:
        self._endpoint = endpoint or _default_endpoint()
        self._api_key = api_key or _default_api_key()

        # 初始化 HttpClient
        self._client = HttpClient(
            endpoint=self._endpoint,
            api_key=self._api_key,
            max_retries=max_retries,
            timeout=timeout,
        )

        # 初始化 BatchBuffer
        self._buffer = BatchBuffer(
            flush_callback=self._flush_callback,
            max_size=max_batch_size,
            flush_interval=flush_interval,
        )

        # 注册退出钩子
        self._register_exit_hooks()

    def _flush_callback(self, runs: list[Run]) -> None:
        """BatchBuffer 的 flush 回调，发送批量请求到后端。"""
        try:
            self._client.send_batch(runs)
        except Exception:
            # 上报失败时静默忽略（不影响业务代码）
            # 可选：记录日志（P3 补充结构化日志）
            pass

    def save(self, run: Run) -> None:
        """将一条 Run 添加到批量上报队列。

        提供与 SQLite writer 兼容的接口，可直接注入到 @traceable 装饰器：
            from lightsmith.storage.http import HttpWriter
            from lightsmith.decorators import set_run_writer

            writer = HttpWriter()
            set_run_writer(writer.save)

        Args:
            run: 要上报的 Run 对象。
        """
        self._buffer.add(run)

    def flush(self) -> None:
        """手动触发 flush（立即上报所有缓冲的 Run）。"""
        self._buffer.flush()

    def shutdown(self) -> None:
        """关闭 HttpWriter，flush 剩余数据并停止接收新 Run。"""
        self._buffer.shutdown()

    def _register_exit_hooks(self) -> None:
        """注册进程退出钩子，确保剩余数据被 flush。

        注意：
          - atexit 在异步程序中无法 await，只能同步阻塞执行。
          - SIGTERM handler 处理容器/进程被杀的情形。
        """
        atexit.register(self.shutdown)

        # 注册 SIGTERM handler（优雅关闭）
        def sigterm_handler(signum, frame):
            self.shutdown()

        signal.signal(signal.SIGTERM, sigterm_handler)


# ---------------------------------------------------------------------------
# 全局默认 HttpWriter（单例，延迟初始化）
# ---------------------------------------------------------------------------

_default_http_writer: Optional[HttpWriter] = None
_default_http_writer_lock = threading.Lock()


def get_default_http_writer() -> HttpWriter:
    """返回进程级别的默认 HttpWriter 单例，线程安全。

    首次调用时按默认配置初始化，后续调用复用同一实例。

    用法：
        from lightsmith.storage.http import get_default_http_writer
        from lightsmith.decorators import set_run_writer

        set_run_writer(get_default_http_writer().save)
    """
    global _default_http_writer
    if _default_http_writer is None:
        with _default_http_writer_lock:
            if _default_http_writer is None:
                _default_http_writer = HttpWriter()
    return _default_http_writer
