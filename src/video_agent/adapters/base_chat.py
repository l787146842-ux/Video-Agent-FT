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


class StreamChunk(BaseModel):
    """流式增量块"""
    type: str = "text_delta"  # text_delta | reasoning_delta | tool_call | done
    text: str = ""
    tool_name: str = ""
    tool_args: Dict[str, Any] = {}
    finish_reason: str = ""  # 仅在 type="done" 时携带（stop / length / tool_calls）


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
    ) -> ChatResponse:
        """非流式 chat 调用。max_tokens/temperature/timeout 为 None 时回落到全局 settings。"""
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
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式 chat 调用（SSE）。max_tokens/temperature/timeout 为 None 时回落到全局 settings。"""
        ...
        yield  # pragma: no cover

    @property
    def supports_function_calling(self) -> bool:
        """是否支持 OpenAI 标准 function calling"""
        return False
