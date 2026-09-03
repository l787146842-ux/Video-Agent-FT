"""LLM Chat 数据契约与端口（依赖倒置：core 拥有契约，adapters 实现）。

宪法铁律：core 层不得 import adapters 层（ARCHITECTURE_RULES §六）。
Planner / TurnExecutor / fc_tool_runner 需要「LLM 调用结果的数据形状」
（ChatResponse / StreamChunk）——这两个纯数据类属**高层策略拥有的契约**，
故下沉本模块；adapters/base_chat.py 反过来依赖本模块并 re-export（保持
`adapters.base_chat.ChatResponse` 等旧导入路径不变），各具体 chat 实现照旧使用。

Chat 适配器的抽象基类 `BaseChatAdapter` 是 Rule 4 宪法锚点，定义留在
adapters/base_chat.py（外部调用必须继承它）；core 侧需要引用「一个 chat
适配器长什么样」时，依赖本模块的结构化端口 `ChatAdapterPort`（Protocol），
不 import adapters——BaseChatAdapter 的实现结构化满足本端口。

本模块是叶子（只依赖 typing / pydantic），不 import 任何 adapters/core
具体实现，杜绝循环依赖。adapters → 本模块属「端口/接口模块放行」方向
（check_layer_imports R3_ALLOWED_CORE_MODULES）。
"""
from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol

from pydantic import BaseModel


class ChatResponse(BaseModel):
    """LLM 调用结果"""
    content: str = ""
    finish_reason: str = ""
    tool_calls: List[Dict[str, Any]] = []
    raw: Optional[Dict[str, Any]] = None
    # 本轮消耗 token（usage.total_tokens；透明度兑现：轮次账单数据源，
    # 端点未返回 usage 时保持 0，消费方按「有则展示」降级）
    token_usage: int = 0
    # P2-1 KV-cache 遥测：本轮 prompt token 与供应商前缀缓存命中 token
    #（提取口径见 adapters.base_chat.extract_prompt_cache_usage；端点未返回时保 0）
    prompt_tokens: int = 0
    cached_tokens: int = 0


class StreamChunk(BaseModel):
    """流式增量块"""
    type: str = "text_delta"  # text_delta | reasoning_delta | tool_call | done
    text: str = ""
    tool_name: str = ""
    tool_args: Dict[str, Any] = {}
    finish_reason: str = ""  # 仅在 type="done" 时携带（stop / length / tool_calls）
    # 仅在 type="done" 时机会性携带（中继在流内下发 usage 才有值，不强求）
    usage_tokens: int = 0
    # 仅在 type="done" 时机会性携带：本轮 prompt token 与前缀缓存命中 token
    #（P2-1 KV-cache 遥测，流内未下发 usage 时保 0）
    prompt_tokens: int = 0
    cached_tokens: int = 0


class ChatAdapterPort(Protocol):
    """LLM Chat 适配器端口（结构化类型 · 依赖倒置）。

    core（Planner 等）只依赖本端口描述的能力形状，不 import adapters；
    具体抽象基类 = adapters/base_chat.py::BaseChatAdapter（Rule 4 宪法锚点，
    定义留在 adapters），其实现结构化满足本端口。方法签名与 ABC 保持一致。
    """

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
        """非流式 chat 调用（max_tokens/temperature/timeout/thinking_level
        为 None 时回落全局 settings）。"""
        ...

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        thinking_level: Optional[str] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式 chat 调用（SSE），产出 StreamChunk 增量块。"""
        ...

    @property
    def supports_function_calling(self) -> bool:
        """是否支持 OpenAI 标准 function calling。"""
        ...


__all__ = [
    "ChatResponse",
    "StreamChunk",
    "ChatAdapterPort",
]
