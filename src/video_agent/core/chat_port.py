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

本模块是叶子（只依赖 typing / pydantic / contextvars），不 import 任何
adapters/core 具体实现，杜绝循环依赖。adapters → 本模块属「端口/接口模块
放行」方向（check_layer_imports R3_ALLOWED_CORE_MODULES）。

模型能力声明与传递（2026-11-13 read_image 能力闸）：
- 声明面 `ChatAdapterPort.supports_image_input`（adapters/base_chat.py 的
  BaseChatAdapter 默认 False = fail-closed，真实实现按能力覆盖）；
- 传递面 = 本模块的 contextvar（同 utils/cancel_token.py /
  skill_runtime/progress.py 的 contextvar 先例）：adapter 在 chat 入口把
  自己声明的能力**发布**进当前上下文，工具层
  （tools/skill_file_tools.py 的 read_image）无需 import adapters/web 即可
  读到——tools→core.chat_port 是合法方向（check_layer_imports 只禁
  core/tools→web）。
"""
from contextvars import ContextVar, Token
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
    # 推理模型思考内容（非流式路径捕获；流式经 reasoning_delta 增量）。
    # 是否回传进后续请求由 settings.llm_reasoning_passthrough 统一闸门控制
    reasoning_content: str = ""


class StreamChunk(BaseModel):
    """流式增量块"""
    type: str = "text_delta"  # text_delta | reasoning_delta | tool_call | tool_call_delta | done
    text: str = ""
    tool_name: str = ""
    tool_args: Dict[str, Any] = {}
    # 供应商 tool_call id（上下文与缓存优化计划批 C1）：仅在 type="tool_call"
    # 时携带（端点未下发时空串，消费方回落合成 id），供 tool role 结果配对
    tool_call_id: str = ""
    # 8888 事故批（对齐 dsh「数据不丢」）：type="tool_call" 且 arguments 解析
    # 失败时携带原始参数串与拒因——消费方不再伪造 {}，拒收时把真实原因回喂
    # 模型（抢救成功则两字段为空、tool_args 为抢救后的 dict）
    tool_args_raw: str = ""
    tool_args_error: str = ""
    # 8888 事故批（对齐 dsh tool-call-delta）：type="tool_call_delta" 时携带——
    # 工具参数生成的流式进度提示（tool_index=分片序号，tool_args_len=该调用
    # 已累积参数长度），仅展示用，闸机仍以流末完整参数为准
    tool_index: int = 0
    tool_args_len: int = 0
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

    @property
    def supports_image_input(self) -> bool:
        """当前模型是否接受图片输入（多模态 vision）。

        deny-by-default：未声明者为 False ⇒ 工具层据此**明确拒收**图片加载，
        不把供应商必然 400 的 data URI 塞进上下文（错误在工具层就近暴露，
        不留给下一轮模型调用以「莫名 400」形态炸出）。"""
        ...


# ---------- 模型图片能力：上下文作用域发布面 ----------
#
# 为什么用 contextvar 而不是端口注册表（core/ports.py）：
# - 能力是**按当前调用方 adapter 实例**变化的请求态事实（同一进程里不同
#   供应商/模型并存：子代理可换模、助手通道另建 adapter），不是进程级装配
#   事实；端口表是「web 实现注入 core」的**单例装配面**，塞请求态进去会串线。
# - contextvar 天然随 asyncio 任务链传播（agent_loop → llm_call →
#   fc_tool_runner → tools），与 cancel_token / progress 两个先例同构；
#   async 生成器（chat_stream）内部 set 的绑定同样对**迭代方**可见。
# - 方向合法：tools → core.chat_port 不是 tools → web，check_layer_imports
#   只禁 core/tools import src.video_agent.web。
#
# 三态语义（None / True / False），刻意区分「不知道」与「明确不支持」：
# - None = 当前上下文没有任何模型调用发布过能力（工具被直连：单测 / CLI /
#   非对话路径）。此时**不新增闸**，维持改动前的行为（既有契约
#   tests/unit/test_skill_file_tools.py 直连工具必须仍成功）。
# - True = 最近一次模型调用声明的适配器接受图片输入 ⇒ 允许。
# - False = 最近一次模型调用**明确声明**不支持 ⇒ read_image 拒绝并给可行动
#   错误（错误在工具层就近暴露，不留给下一轮请求以「莫名 400」炸出）。
#
# 发布时机刻意是「模型调用入口 set、不在此后 reset」：工具批执行发生在模型
# 调用**返回之后**（agent_loop：llm_call → fc_tool_runner → 工具），入口处
# reset 会让工具层永远读不到本次调用的声明（闸形同虚设）。值由**每次**模型
# 调用刷新，故正式链路上工具读到的总是「发起这批 tool_calls 的那个模型」的
# 声明；子代理换模时其自身调用会再发布一次（同任务链共享上下文）。
_image_input_supported_var: ContextVar[Optional[bool]] = ContextVar(
    "chat_adapter_supports_image_input", default=None,
)


def publish_model_image_support(supported: bool) -> None:
    """发布「本次模型调用所用适配器是否接受图片输入」到当前上下文。

    调用方 = adapters/base_chat.BaseChatAdapter 的调用入口包装
    （`__init_subclass__` 统一套壳，见该模块 _publish_capability_on_call），
    使工具层在同一次模型调用链下游读到真实能力，且不引入 tools→web 依赖。
    """
    _image_input_supported_var.set(bool(supported))


def current_model_supports_image_input() -> Optional[bool]:
    """当前上下文的模型图片输入能力（None = 未知/未发布，True/False = 已声明）。

    消费方 = tools/skill_file_tools.ReadImageTool：仅当**明确 False** 时拒绝，
    不把必然被上游拒收的图片块塞进上下文。
    """
    return _image_input_supported_var.get()


def reset_model_image_support() -> None:
    """清除能力发布（测试隔离 / 非对话路径复位；生产链路由每次调用刷新）。"""
    _image_input_supported_var.set(None)


__all__ = [
    "ChatResponse",
    "StreamChunk",
    "ChatAdapterPort",
    "publish_model_image_support",
    "current_model_supports_image_input",
    "reset_model_image_support",
]
