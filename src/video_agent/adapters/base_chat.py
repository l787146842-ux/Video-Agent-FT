"""
Chat Adapter 基类 — LLM 对话调用的统一接口（Rule6: 外部调用走 Adapter）。

Planner 直接持有 BaseChatAdapter 引用，不经过 Tool Manager。

错误分类分流接线：各 chat 实现的 HTTP 请求统一经
dispatch_chat_request 分流 — transient（429/5xx/超时/连接错误）由
with_retry 指数退避重试（上限/退避走 config）；permanent（400/401/403 等）
立即上抛结构化 AdapterError（kind 区分），不重试。
"""
import functools
import inspect
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from src.video_agent.adapters.errors import build_status_error
from src.video_agent.adapters.retry import with_retry
from src.video_agent.config import settings
# 依赖倒置：Chat 数据契约（ChatResponse/StreamChunk）下沉 core/chat_port.py，
# core 与 adapters 都依赖共享数据类而非互相依赖；本模块 re-export 保持
# `adapters.base_chat.ChatResponse` 等旧导入路径不变。BaseChatAdapter（Rule 4
# 宪法锚点）仍定义于本模块，其接口结构化满足 core.chat_port.ChatAdapterPort。
from src.video_agent.core.chat_port import (  # noqa: F401  (re-export)
    ChatResponse,
    StreamChunk,
    publish_model_image_support,
)
from src.video_agent.utils import gen_id


def new_request_id() -> str:
    """同轮请求标识（幂等语义）：一次 chat 调用生成一个 id，
    重试全程复用同一标识（随 X-Request-Id 请求头下发），供上游按标识
    去重，避免同轮请求被当多次新请求重复计费。"""
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


def _safe_int(v: Any) -> int:
    """稳健取整：非数字/转换失败/负数一律回落 0。

    遥测可降级：供应商返回畸形值时不得抛异常击穿响应解析主链路。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def extract_prompt_cache_usage(usage: Any) -> Tuple[int, int]:
    """从供应商 usage 提取 (prompt_tokens, cached_tokens)。

    P2-1 KV-cache 遥测：统一各家 prompt cache 命中字段命名差异——
    - OpenAI 系：prompt_tokens + prompt_tokens_details.cached_tokens
    - Anthropic 中继：input_tokens + cache_read_input_tokens
    - DeepSeek：prompt_tokens + prompt_cache_hit_tokens
    缺失/畸形一律回落 (0, 0)：遥测可降级，不影响主流程。
    Anthropic 口径：input_tokens 不含 cache_read_input_tokens，命中取自
    该字段时分母补全（prompt += cached），避免命中量被钳到极低。
    """
    if not isinstance(usage, dict):
        return 0, 0
    prompt = _safe_int(usage.get("prompt_tokens"))
    if prompt == 0:
        prompt = _safe_int(usage.get("input_tokens"))
    details = usage.get("prompt_tokens_details")
    cached = 0
    if isinstance(details, dict):
        cached = _safe_int(details.get("cached_tokens"))
    if cached <= 0:
        cached = _safe_int(usage.get("prompt_cache_hit_tokens"))
    if cached <= 0:
        cached = _safe_int(usage.get("cache_read_input_tokens"))
        if cached > 0:
            # Anthropic 语义：input_tokens 不含命中量，补全分母再钳制
            prompt += cached
    return max(0, prompt), max(0, min(cached, prompt) if prompt > 0 else cached)


def _capability_of(adapter: Any) -> bool:
    """读适配器的图片输入能力声明（异常/缺失一律 False = fail-closed）。"""
    try:
        return bool(getattr(adapter, "supports_image_input", False))
    except Exception:  # noqa: BLE001 —— 能力属性损坏不得击穿模型调用
        return False


def _publish_capability_on_call(fn: Any) -> Any:
    """给 chat / chat_stream 套「入口发布模型图片能力」壳（见 BaseChatAdapter）。

    异步生成器（chat_stream）与协程（chat）分别处理：
    - 生成器：包装体本身是 async 生成器，**首次迭代时**先发布再委托；
    - 协程：包装体是 async def，调用即发布。
    两者都在「调用方上下文」里 set——工具批在模型调用返回后执行，正读得到。
    包裹只做一次（幂等标记 `_publishes_image_capability`），重复套壳不会叠加。
    """
    if inspect.isasyncgenfunction(fn):
        @functools.wraps(fn)
        async def _gen(self: Any, *args: Any, **kwargs: Any):
            publish_model_image_support(_capability_of(self))
            async for chunk in fn(self, *args, **kwargs):
                yield chunk

        _gen._publishes_image_capability = True  # type: ignore[attr-defined]
        return _gen

    @functools.wraps(fn)
    async def _coro(self: Any, *args: Any, **kwargs: Any):
        publish_model_image_support(_capability_of(self))
        return await fn(self, *args, **kwargs)

    _coro._publishes_image_capability = True  # type: ignore[attr-defined]
    return _coro


class BaseChatAdapter(ABC):
    """LLM Chat 适配器抽象基类（Rule 4：外部调用必须继承本类）。

    数据契约 ChatResponse/StreamChunk 下沉 core/chat_port.py（依赖倒置）；
    本 ABC 的接口结构化满足 core.chat_port.ChatAdapterPort，core 侧经该端口
    引用 chat 能力而不 import adapters。

    能力声明与发布（2026-11-13 read_image 能力闸）：
    - `supports_image_input` 是**能力声明**（deny-by-default = False）；
      具体实现按真实支持的模型/协议覆盖；
    - 本类经 `__init_subclass__` 给每个子类的 `chat` / `chat_stream` 套一层
      「入口发布」壳：调用时把 `self.supports_image_input` 写进
      core.chat_port 的 contextvar。于是工具层（read_image）在同一次模型
      调用链下游读到真实能力，无需 tools→adapters/web 反向依赖。
      `chat_stream` 是 async 生成器：能力在生成器**首次迭代前**发布，
      之后同一上下文里的工具批能读到（实测语义见
      tests/unit/test_read_image_capability.py）。
    """

    # 子类覆盖即生效（`__init_subclass__` 读取的是类属性/属性描述符，
    # 对 property 与普通 bool 属性都成立）。
    supports_image_input: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """给子类的 chat/chat_stream 统一套「能力发布」壳（幂等、可继承）。

        只包**子类自身定义**的方法（`cls.__dict__` 里有才算）；未定义的
        `chat_stream` 由基类抽象声明保证具体实现必须提供，故不会漏包。
        壳不改变签名与返回值，只多一次 contextvar 发布（无返回值语义影响）。
        """
        super().__init_subclass__(**kwargs)
        for attr in ("chat", "chat_stream"):
            raw = cls.__dict__.get(attr)
            if raw is None or getattr(raw, "_publishes_image_capability", False):
                continue
            if not callable(raw):
                continue
            setattr(cls, attr, _publish_capability_on_call(raw))

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
