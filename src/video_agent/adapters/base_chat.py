"""
Chat Adapter 基类 — LLM 对话调用的统一接口（Rule6: 外部调用走 Adapter）。

Planner 直接持有 BaseChatAdapter 引用，不经过 Tool Manager。

错误分类分流接线：各 chat 实现的 HTTP 请求统一经
dispatch_chat_request 分流 — transient（429/5xx/超时/连接错误）由
with_retry 指数退避重试（上限/退避走 config）；permanent（400/401/403 等）
立即上抛结构化 AdapterError（kind 区分），不重试。
"""
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional

import httpx
from pydantic import BaseModel

from src.video_agent.adapters.errors import build_status_error
from src.video_agent.adapters.retry import with_retry
from src.video_agent.config import settings
from src.video_agent.utils import gen_id


def new_request_id() -> str:
    """同轮请求标识（幂等语义）：一次 chat 调用生成一个 id，
    重试全程复用同一标识（随 X-Request-Id 请求头下发），供上游按标识
    去重，避免同一轮请求被当多次新请求重复计费。"""
    return gen_id("chat-req")


async def dispatch_chat_request(
    request_fn: Callable[[], Awaitable[httpx.Response]],
    *,
    context: str,
) -> httpx.Response:
    """chat HTTP 请求统一分流入口：

    - transient（429/5xx/超时/连接错误）→ with_retry 指数退避重试，
      上限与退避参数走 config（adapter_retry_max / adapter_retry_base_delay）；
      重试耗尽仍 transient → 抛结构化 AdapterError（kind/retryable 齐备）
    - permanent（其余 4xx）→ 不重试，立即抛结构化 AdapterError（kind 区分）
    - 2xx/3xx → 原样返回响应

    request_fn 应闭包复用同一 payload 与请求标识（幂等：重试 = 同轮重提）。
    """
    resp = await with_retry(
        request_fn,
        max_retries=settings.adapter_retry_max,
        base_delay=settings.adapter_retry_base_delay,
        context=context,
    )
    # with_retry 只拦 transient；非 2xx 到这里必是 permanent 4xx → 立即上抛
    if resp.status_code >= 400:
        try:
            body = resp.text[:200]
        except Exception:
            body = ""
        raise build_status_error(resp.status_code, body, context=context)
    return resp


class ChatResponse(BaseModel):
    """LLM 调用结果"""
    content: str = ""
    finish_reason: str = ""
    tool_calls: List[Dict[str, Any]] = []
    raw: Optional[Dict[str, Any]] = None
    # 本轮消耗 token（usage.total_tokens；透明度兑现：轮次账单数据源，
    # 端点未返回 usage 时保持 0，消费方按「有则展示」降级）
    token_usage: int = 0


class StreamChunk(BaseModel):
    """流式增量块"""
    type: str = "text_delta"  # text_delta | reasoning_delta | tool_call | done
    text: str = ""
    tool_name: str = ""
    tool_args: Dict[str, Any] = {}
    finish_reason: str = ""  # 仅在 type="done" 时携带（stop / length / tool_calls）
    # 仅在 type="done" 时机会性携带（中继在流内下发 usage 才有值，不强求）
    usage_tokens: int = 0


class BaseChatAdapter(ABC):
    """LLM Chat 适配器抽象基类"""

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        thinking_level: Optional[str] = None,
    ) -> ChatResponse:
        """非流式 chat 调用。max_tokens/temperature/timeout 为 None 时回落到全局 settings。
        thinking_level：本次调用的思考档位覆盖（None=沿用全局配置）。"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        thinking_level: Optional[str] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式 chat 调用（SSE）。max_tokens/temperature/timeout 为 None 时回落到全局 settings。
        thinking_level：本次调用的思考档位覆盖（None=沿用全局配置）。"""
        ...
        yield  # pragma: no cover

    @property
    def supports_function_calling(self) -> bool:
        """是否支持 OpenAI 标准 function calling"""
        return False
