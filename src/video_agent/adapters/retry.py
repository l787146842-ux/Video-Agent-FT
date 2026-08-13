"""
Adapter 请求重试辅助 — 对瞬时故障（5xx、超时、连接错误）自动重试。

用法：
    from src.video_agent.adapters.retry import with_retry

    result = await with_retry(
        lambda: client.post("/chat/completions", json=payload),
        max_retries=2,
        base_delay=1.0,
    )

设计原则：
- 仅对可重试错误（5xx / 超时 / 连接失败）重试，4xx 不重试
- 指数退避：delay = base_delay * 2^(attempt-1)
- 最终仍失败时抛出最后一次异常（由调用方转译为 AdapterError）
"""
import asyncio
from typing import Any, Awaitable, Callable, TypeVar

import httpx
from loguru import logger

from src.video_agent.exceptions import AdapterError
from src.video_agent.utils.stream_notify import notify_stream

T = TypeVar("T")

# 可重试的 httpx 异常类型
RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


def _is_retryable_status(status_code: int) -> bool:
    """5xx 服务端错误可重试，4xx 客户端错误不可重试"""
    return status_code >= 500


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 2,
    base_delay: float = 1.0,
    context: str = "",
) -> T:
    """
    执行异步函数 fn，遇到瞬时故障时自动重试。

    Args:
        fn: 无参异步 callable（通常用 lambda 包装）
        max_retries: 最大重试次数（不含首次执行）
        base_delay: 首次重试等待秒数（指数退避）
        context: 日志上下文标识（如 "chat" / "image"）

    Returns:
        fn 的返回值

    Raises:
        最后一次失败的异常（httpx.HTTPError 子类）
    """
    last_exc: BaseException = RuntimeError("unreachable")

    for attempt in range(max_retries + 1):
        try:
            result = await fn()
            # 检查 HTTP 响应状态码（如果结果是 httpx.Response）
            if isinstance(result, httpx.Response) and _is_retryable_status(result.status_code):
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"[Retry] {context} HTTP {result.status_code}，"
                        f"第 {attempt + 1}/{max_retries} 次重试，等待 {delay:.1f}s"
                    )
                    # 超时重试可视化（7777 事故）：静默重试 → 前端状态栏实时可见
                    await notify_stream(
                        f"⏳ {context or '上游'}繁忙（HTTP {result.status_code}），"
                        f"{delay:.0f}s 后自动重试（{attempt + 1}/{max_retries}）…"
                    )
                    await asyncio.sleep(delay)
                    continue
                # 末次尝试仍收到 5xx：绝不把失败响应当成功返回（P0-2 契约修复）
                raise AdapterError(
                    f"[Retry] {context} HTTP {result.status_code}：服务端错误，"
                    f"已重试 {max_retries} 次仍失败",
                    retryable=True,
                    http_status=result.status_code,
                )
            return result
        except RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"[Retry] {context} {type(e).__name__}: {e}，"
                    f"第 {attempt + 1}/{max_retries} 次重试，等待 {delay:.1f}s"
                )
                await notify_stream(
                    f"⏳ {context or '上游'}无响应（{type(e).__name__}），"
                    f"{delay:.0f}s 后自动重试（{attempt + 1}/{max_retries}）…"
                )
                await asyncio.sleep(delay)
            else:
                raise
        except httpx.HTTPStatusError as e:
            # HTTPStatusError 由 raise_for_status() 抛出，检查是否 5xx
            if _is_retryable_status(e.response.status_code) and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"[Retry] {context} HTTP {e.response.status_code}，"
                    f"第 {attempt + 1}/{max_retries} 次重试，等待 {delay:.1f}s"
                )
                await notify_stream(
                    f"⏳ {context or '上游'}繁忙（HTTP {e.response.status_code}），"
                    f"{delay:.0f}s 后自动重试（{attempt + 1}/{max_retries}）…"
                )
                await asyncio.sleep(delay)
                last_exc = e
                continue
            raise

    raise last_exc  # pragma: no cover
