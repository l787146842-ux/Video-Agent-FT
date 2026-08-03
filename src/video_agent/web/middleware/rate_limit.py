"""
请求限流中间件 — 基于令牌桶的内存限流。

用法（在 app.py 中）：
    from src.video_agent.web.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware, rate=settings.rate_limit_per_minute)

仅对 /api/agent/chat* 和 /api/generate* 端点生效。
"""
import time
from typing import Dict, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from loguru import logger


class _TokenBucket:
    """单 IP 令牌桶：容量 = rate，每分钟补充 rate 个令牌"""

    __slots__ = ("tokens", "last_refill")

    def __init__(self, rate: int):
        self.tokens: float = float(rate)
        self.last_refill: float = time.monotonic()

    def consume(self, rate: int) -> bool:
        """尝试消费 1 个令牌，成功返回 True"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        # 每分钟补充 rate 个 → 每秒补充 rate/60
        self.tokens = min(float(rate), self.tokens + elapsed * (rate / 60.0))
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


# 受限路径前缀（仅这些端点触发限流）
_LIMITED_PREFIXES: Tuple[str, ...] = (
    "/api/agent/chat",
    "/api/chat",
    "/api/canvas-llm",
    "/api/generate",
)

# 桶清理间隔（秒）：超过此时间未访问的 IP 桶会被回收
_BUCKET_GC_INTERVAL = 300


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    基于令牌桶的 IP 级限流中间件。

    参数：
        app: ASGI 应用
        rate: 每分钟允许的最大请求数（默认 10）
    """

    def __init__(self, app: ASGIApp, rate: int = 10):
        super().__init__(app)
        self.rate = rate
        self._buckets: Dict[str, _TokenBucket] = {}
        self._last_gc: float = time.monotonic()

    def _get_client_ip(self, request: Request) -> str:
        """提取客户端 IP（支持 X-Forwarded-For 代理场景）"""
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _should_limit(self, path: str, method: str) -> bool:
        """判断请求是否需要限流。

        GET/HEAD/OPTIONS 只读请求（如生成状态轮询）直接放行，
        限流只作用于 POST/PUT/DELETE 等提交类端点，避免误杀前端轮询。
        """
        if method.upper() in ("GET", "HEAD", "OPTIONS"):
            return False
        return any(path.startswith(prefix) for prefix in _LIMITED_PREFIXES)

    def _gc_stale_buckets(self) -> None:
        """定期清理长时间未使用的桶，防止内存泄漏"""
        now = time.monotonic()
        if now - self._last_gc < _BUCKET_GC_INTERVAL:
            return
        self._last_gc = now
        stale = [ip for ip, b in self._buckets.items() if now - b.last_refill > _BUCKET_GC_INTERVAL]
        for ip in stale:
            del self._buckets[ip]
        if stale:
            logger.debug(f"[RateLimit] GC 清理 {len(stale)} 个过期桶")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # 非受限路径 / 只读方法直接放行
        if not self._should_limit(request.url.path, request.method):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        bucket = self._buckets.get(client_ip)
        if bucket is None:
            bucket = _TokenBucket(self.rate)
            self._buckets[client_ip] = bucket

        if not bucket.consume(self.rate):
            logger.warning(f"[RateLimit] IP {client_ip} 触发限流: {request.url.path}")
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试", "error_code": "RATE_LIMITED"},
                headers={"Retry-After": "60"},
            )

        self._gc_stale_buckets()
        return await call_next(request)
