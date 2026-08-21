"""
Chat Adapter 基类 — LLM 对话调用的统一接口（Rule6: 外部调用走 Adapter）。

Planner 直接持有 BaseChatAdapter 引用，不经过 Tool Manager。
"""
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional

from pydantic import BaseModel


class ChatResponse(BaseModel):
    """LLM 调用结果"""
    content: str = ""
    finish_reason: str = ""
    tool_calls: List[Dict[str, Any]] = []
    raw: Optional[Dict[str, Any]] = None
    # 本轮消耗 token（usage.total_tokens；批2 透明度兑现：轮次账单数据源，
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
