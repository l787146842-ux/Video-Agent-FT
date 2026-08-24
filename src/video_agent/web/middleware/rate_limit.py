"""
请求限流中间件 — 基于令牌桶的内存限流。

用法（在 app.py 中）：
    from src.video_agent.web.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(
        RateLimitMiddleware,
        rate=settings.rate_limit_per_minute,
        generate_rate=settings.rate_limit_generate_per_minute,
    )

仅对 /api/agent/chat* 和 /api/generate* 端点生效。
端点分档（P0-3）：聊天类用 rate，生成类用 generate_rate（批量生成需要更高配额），
两组令牌桶按 (IP, 组) 独立计数互不影响。

边界语义：0 的关闭语义由 app.py 装载守卫承载（rate>0 才挂载中间件）；
本模块内 rate=0 = 全拒而非不限流（令牌桶容量 0 无令牌可消费）。
"""
import time
from typing import Dict, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.web.error_payload import classify_legacy_code


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


# 受限路径前缀 → 端点组（chat 严格配额 / generate 批量配额 / write 普通写端点）
# B6/F38：写端点扩面——上传/项目/故事板/对话/技能写操作纳入限流（防上传与
# 状态写入类 DoS；此前仅 /api/agent/chat* 与 /api/generate* 受限）
_LIMITED_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("/api/agent/chat", "chat"),
    ("/api/generate", "generate"),
    ("/api/upload", "write"),
    ("/api/project", "write"),
    ("/api/storyboard", "write"),
    ("/api/conversations", "write"),
    ("/api/skills", "write"),
)

# 桶清理间隔（秒）：超过此时间未访问的 IP 桶会被回收
_BUCKET_GC_INTERVAL = 300


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    基于令牌桶的 IP 级限流中间件（端点分档）。

    参数：
        app: ASGI 应用
        rate: 聊天类端点每分钟允许的最大请求数（默认 10）
        generate_rate: 生成类端点每分钟配额（默认 60，批量生成不误伤）；
                       未传时退化为 rate
    """

    def __init__(self, app: ASGIApp, rate: int = 10, generate_rate: int = 0):
        super().__init__(app)
        self.rate = rate
        self.generate_rate = generate_rate or rate
        self._buckets: Dict[Tuple[str, str], _TokenBucket] = {}
        self._last_gc: float = time.monotonic()

    def _get_client_ip(self, request: Request) -> str:
        """提取客户端 IP。X-Forwarded-For 仅在显式配置 TRUST_PROXY=true 时
        才信任（本机直连部署下该头可被伪造，绕过 IP 级限流）"""
        if settings.trust_proxy:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _limited_group(self, path: str, method: str) -> str:
        """返回请求所属限流组（"chat"/"generate"），不限流返回空串。

        GET/HEAD/OPTIONS 只读请求（如生成状态轮询）直接放行，
        限流只作用于 POST/PUT/DELETE 等提交类端点，避免误杀前端轮询。
        """
        if method.upper() in ("GET", "HEAD", "OPTIONS"):
            return ""
        for prefix, group in _LIMITED_PREFIXES:
            if path.startswith(prefix):
                return group
        return ""

    def _gc_stale_buckets(self) -> None:
        """定期清理长时间未使用的桶，防止内存泄漏"""
        now = time.monotonic()
        if now - self._last_gc < _BUCKET_GC_INTERVAL:
            return
        self._last_gc = now
        stale = [k for k, b in self._buckets.items() if now - b.last_refill > _BUCKET_GC_INTERVAL]
        for k in stale:
            del self._buckets[k]
        if stale:
            logger.debug(f"[RateLimit] GC 清理 {len(stale)} 个过期桶")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # 非受限路径 / 只读方法直接放行
        group = self._limited_group(request.url.path, request.method)
        if not group:
            return await call_next(request)

        rate = self.generate_rate if group in ("generate", "write") else self.rate
        client_ip = self._get_client_ip(request)
        key = (client_ip, group)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _TokenBucket(rate)
            self._buckets[key] = bucket

        if not bucket.consume(rate):
            logger.warning(f"[RateLimit] IP {client_ip} 触发限流({group}): {request.url.path}")
            # P9：非流式错误出口统一走 ErrorPayload 契约（RATE_LIMITED 已在
            # 桥接表登记 → kind=quota / err.quota.rate_limited，状态码 429 不变）
            payload = classify_legacy_code("RATE_LIMITED", "请求过于频繁，请稍后再试")
            return JSONResponse(
                status_code=429,
                content=payload.http_body("RATE_LIMITED"),
                headers={"Retry-After": "60"},
            )

        self._gc_stale_buckets()
        return await call_next(request)
