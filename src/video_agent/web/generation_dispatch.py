"""
供应商调用分发（generation.py 三段之一）。

职责：端点解析 + Chat Completions 调用 + 生图供应商路由 + 降级链判定。
实际 HTTP 调用逻辑在 adapters/（openai_compat / agy_cli / canvas_adapter），
本模块只负责：
1. 根据 provider_config 解析端点参数（配置源职责仍在 provider_config）
2. 构造对应的 Adapter 实例并把 AdapterError 统一转译为 GenerationError
3. 生图智能路由（画布优先 + CLI 协议 + 本地直连）与同模型跨厂商降级候选链
"""
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.exceptions import AdapterError, GenerationError
from src.video_agent.config import settings
from src.video_agent.core.provider_config import (
    CLI_PROTOCOLS,
    get_api_key,
    get_api_key_async,
    get_canvas_provider_ids_async,
    get_provider_config,
    get_provider_config_async,
    load_merged_providers_async,
    resolve_provider_ref_async,
)
from src.video_agent.adapters.openai_compat import (
    OpenAICompatChatAdapter,
    OpenAICompatImageAdapter,
)
from src.video_agent.adapters.agy_cli import AgyCliImageAdapter
from src.video_agent.adapters.canvas_adapter import get_canvas_adapter


# ---------- 端点解析（配置源：provider_config） ----------

async def resolve_openai_endpoint_async(provider_id: str, model: str) -> Tuple[str, str, str]:
    """
    解析 (base_url, api_key, effective_model)。
    CLI 协议（gemini-cli / codex / jimeng）没有 base_url，
    自动路由到 custom-api 反代（底层同为 Gemini 模型）。
    解析不出可用端点时抛 GenerationError。
    """
    cfg = await get_provider_config_async(provider_id)
    if not cfg:
        raise GenerationError(f"供应商 '{provider_id}' 未配置，请先在 API 设置页添加")

    base_url = (cfg.get("base_url") or "").strip().rstrip("/")
    api_key = await get_api_key_async(provider_id)
    effective_model = model

    # OpenAI 协议：base_url 未以 /v1 结尾时自动补全（与画布 upstream_models_url 逻辑一致）
    protocol = (cfg.get("protocol") or "openai").lower()
    if base_url and protocol == "openai" and not base_url.endswith("/v1"):
        base_url += "/v1"

    if not base_url and cfg.get("protocol") in CLI_PROTOCOLS:
        fallback = await get_provider_config_async("custom-api")
        if fallback and fallback.get("base_url"):
            base_url = fallback["base_url"].rstrip("/")
            if not base_url.endswith("/v1"):
                base_url += "/v1"
            api_key = await get_api_key_async("custom-api")
            if effective_model in ("auto", ""):
                # 可配置回退模型（CLI_AUTO_CHAT_MODEL）：反代未注册默认模型时
                # 无需改代码，改环境变量即可
                effective_model = settings.cli_auto_chat_model
                logger.info(
                    "[Generation] 提示：若反代报 model not register，请在 .env 设置 "
                    "CLI_AUTO_CHAT_MODEL=<反代已注册的模型名> 后重启服务"
                )
            logger.info(f"[Generation] CLI 协议 '{provider_id}' 路由到反代, model={effective_model}")

    if not base_url:
        raise GenerationError(
            f"供应商 '{provider_id}' 缺少 Base URL（CLI 协议需要先配置 custom-api 反代）"
        )
    return base_url, api_key, effective_model


def resolve_openai_endpoint(provider_id: str, model: str) -> Tuple[str, str, str]:
    """同步版端点解析（供 chat_service 等非事件循环路径使用）。

    语义与 resolve_openai_endpoint_async 完全一致，只把异步 provider_config
    访问换成同步版（画布 HTTP 拉取在调用方线程内执行）。
    """
    from src.video_agent.core.provider_config import (
        CLI_PROTOCOLS,
        get_api_key,
        get_provider_config,
    )

    cfg = get_provider_config(provider_id)
    if not cfg:
        raise GenerationError(f"供应商 '{provider_id}' 未配置，请先在 API 设置页添加")

    base_url = (cfg.get("base_url") or "").strip().rstrip("/")
    api_key = get_api_key(provider_id)
    effective_model = model

    protocol = (cfg.get("protocol") or "openai").lower()
    if base_url and protocol == "openai" and not base_url.endswith("/v1"):
        base_url += "/v1"

    if not base_url and cfg.get("protocol") in CLI_PROTOCOLS:
        fallback = get_provider_config("custom-api")
        if fallback and fallback.get("base_url"):
            base_url = fallback["base_url"].rstrip("/")
            if not base_url.endswith("/v1"):
                base_url += "/v1"
            api_key = get_api_key("custom-api")
            if effective_model in ("auto", ""):
                effective_model = settings.cli_auto_chat_model
                logger.info(
                    "[Generation] 提示：若反代报 model not register，请在 .env 设置 "
                    "CLI_AUTO_CHAT_MODEL=<反代已注册的模型名> 后重启服务"
                )
            logger.info(f"[Generation] CLI 协议 '{provider_id}' 路由到反代, model={effective_model}")

    if not base_url:
        raise GenerationError(
            f"供应商 '{provider_id}' 缺少 Base URL（CLI 协议需要先配置 custom-api 反代）"
        )
    return base_url, api_key, effective_model


# ---------- Chat Completions（委托 OpenAICompatChatAdapter） ----------

async def call_chat_completion(
    provider_id: str,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: int = 8192,
    temperature: float = 0.7,
    timeout: int = 120,
    thinking_level: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """
    OpenAI 兼容 chat 调用。返回 (content, finish_reason)。
    内部委托给 OpenAICompatChatAdapter.chat。
    thinking_level：本次调用思考档位覆盖（None=沿用全局配置）。
    response_format：结构化输出声明（如 {"type":"json_object"}），
    端点不支持时适配器兼容探针自动剥离降级。
    失败抛 GenerationError。
    """
    base_url, api_key, effective_model = await resolve_openai_endpoint_async(provider_id, model)
    adapter = OpenAICompatChatAdapter(base_url=base_url, api_key=api_key, model=effective_model)

    logger.info(f"[Generation] chat: provider={provider_id}, model={effective_model}")
    try:
        response = await adapter.chat(
            messages, max_tokens=max_tokens, temperature=temperature, timeout=timeout,
            thinking_level=thinking_level, response_format=response_format,
        )
    except AdapterError as e:
        raise GenerationError(str(e)) from e
    finally:
        # 临时实例不复用：必须关闭底层 httpx 连接池，否则每次调用泄漏一个 client
        await adapter.close()

    if not response.content:
        raise GenerationError("LLM 返回了空内容")
    return response.content, response.finish_reason


async def call_chat_completion_stream(
    provider_id: str,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: int = 8192,
    temperature: float = 0.7,
    timeout: int = 180,
    on_delta=None,
    reasoning_sink: List[str] | None = None,
    thinking_level: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """
    流式 chat 调用。每收到一段增量文本就 await on_delta(text)。
    内部委托给 OpenAICompatChatAdapter.chat_stream。
    thinking_level：本次调用思考档位覆盖（None=沿用全局配置）。
    response_format：结构化输出声明（如 {"type":"json_object"}），
    端点不支持时适配器兼容探针自动剥离降级。
    返回 (完整内容, finish_reason)。失败抛 GenerationError。
    reasoning_sink（可选）：传入 list 则累积推理模型的思考增量（黑匣子取证用），
    不进上下文。
    """
    base_url, api_key, effective_model = await resolve_openai_endpoint_async(provider_id, model)
    adapter = OpenAICompatChatAdapter(base_url=base_url, api_key=api_key, model=effective_model)

    logger.info(f"[Generation] chat(stream): provider={provider_id}, model={effective_model}")
    content_parts: List[str] = []
    finish_reason = ""

    try:
        async for chunk in adapter.chat_stream(
            messages, max_tokens=max_tokens, temperature=temperature, timeout=timeout,
            thinking_level=thinking_level, response_format=response_format,
        ):
            if chunk.type == "text_delta" and chunk.text:
                content_parts.append(chunk.text)
                if on_delta:
                    await on_delta(chunk.text)
            elif chunk.type == "reasoning_delta" and chunk.text and reasoning_sink is not None:
                reasoning_sink.append(chunk.text)
            elif chunk.type == "done":
                # 透传真实 finish_reason（length=撞输出上限被截断），
                # 不再一律当 stop：截断检测靠它
                finish_reason = getattr(chunk, "finish_reason", "") or "stop"
    except AdapterError as e:
        raise GenerationError(str(e)) from e
    finally:
        # 临时实例不复用：关闭底层 httpx 连接池，避免每次流式调用泄漏
        await adapter.close()

    content = "".join(content_parts)
    if not content:
        raise GenerationError("LLM 流式返回了空内容")
    return content, finish_reason


# ---------- 图片生成（智能路由：画布优先 + 本地兜底） ----------

# 比例 → 1K 基准尺寸（与前端 image-sizes.ts 保持一致）
_IMAGE_1K_SIZES: Dict[str, str] = {
    "1:1": "1024x1024", "2:3": "1024x1536", "3:2": "1536x1024",
    "3:4": "1008x1344", "4:3": "1344x1008", "9:16": "720x1280",
    "16:9": "1280x720", "21:9": "1280x544", "9:21": "544x1280",
}
# 分辨率档位 → 尺寸倍率（1K=基准，2K=2 倍，4K=4 倍）
_RESOLUTION_MULTIPLIERS: Dict[str, int] = {"1K": 1, "2K": 2, "4K": 4}


def image_size_for(aspect_ratio: str, resolution: str = "1K") -> str:
    """按 比例 + 分辨率档位 计算生图尺寸（如 16:9 + 2K → 2560x1440）"""
    base = _IMAGE_1K_SIZES.get((aspect_ratio or "").strip(), _IMAGE_1K_SIZES["16:9"])
    mult = _RESOLUTION_MULTIPLIERS.get((resolution or "1K").strip().upper(), 1)
    if mult == 1:
        return base
    try:
        w, h = (int(x) for x in base.split("x"))
        return f"{w * mult}x{h * mult}"
    except (ValueError, AttributeError):
        return base


async def _try_canvas_image_generation(
    provider_id: str,
    model: str,
    prompt: str,
    *,
    size: str = "1024x1024",
    aspect_ratio: str = "",
) -> Optional[str]:
    """尝试通过画布执行生图。
    仅当画布在线且目标 provider 存在于画布配置中时才尝试。
    返回图片 URL，不适用或失败时返回 None。"""
    # 判断 provider 是否画布可处理
    canvas_ids = await get_canvas_provider_ids_async()
    if provider_id not in canvas_ids:
        return None  # Agent 独有的 provider，跳过画布

    adapter = get_canvas_adapter()
    if not await adapter.is_online():
        return None  # 画布离线

    # 画布在线且能处理该 provider，发起请求
    payload: Dict[str, Any] = {
        "provider_id": provider_id,
        "model": model,
        "prompt": prompt,
    }
    if size:
        payload["size"] = size
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio

    logger.info(f"[Generation] 生图路由到画布: provider={provider_id}, model={model}")
    try:
        result = await adapter.generate_image_online(payload)
        # 画布 /api/online-image 返回格式: {"images": [...], ...}
        images = result.get("images") or []
        if images:
            return images[0]
        logger.warning("[Generation] 画布生图未返回图片，fallthrough 到本地")
        return None
    except Exception as e:
        logger.warning(f"[Generation] 画布生图失败，fallthrough 到本地: {e}")
        return None


# ---------- 生成侧降级链 ----------
#
# 实现位于 core/generation_fallback.py 公开 API；本模块保留薄 re-export 壳，
# web 内部消费点（generation.py 壳 / generation_submit.py）零改动。

from src.video_agent.core.generation_fallback import (  # noqa: E402,F401
    _NON_RETRYABLE_GEN_HINTS,
    gen_fallback_candidates as _gen_fallback_candidates,
    is_retryable_gen_error as _is_retryable_gen_error,
)


async def generate_image_via_provider(
    provider_id: str,
    model: str,
    prompt: str,
    *,
    size: str = "1024x1024",
    aspect_ratio: str = "",
    resolution: str = "",
    reference_images: Optional[List[str]] = None,
) -> str:
    """
    统一图片生成（智能路由）：
    1. 画布在线 + provider 存在于画布 → 通过画布 API 执行（不带参考图时）
    2. CLI 协议（gemini-cli）→ AgyCliImageAdapter（不支持参考图）
    3. 其他供应商 → OpenAICompatImageAdapter 本地直连（支持参考图多模态）
    返回图片 URL。失败抛 GenerationError。

    reference_images：参考素材 URL 列表（@ 引用的素材），会内联发送给多模态模型。
    resolution：分辨率档位（1K/2K/4K），CLI 类适配器会写进提示词让模型感知。
    """
    # 供应商兼容显示名（LLM action 常传界面上的名称如 Grsai）→ 内部 id
    provider_id = await resolve_provider_ref_async(provider_id)
    refs = reference_images or []

    # 空模型兜底（彻底修复「model not register: ''/MissingParameter」）：
    # 模型解析优先级：规格文档指定（LLM action 参数）→ 预览框草稿参数
    # （action_executor 已按此链传入）→ 供应商配置的第一个图片模型
    cfg0 = await get_provider_config_async(provider_id)
    if cfg0 and not model:
        defaults = [m for m in (cfg0.get("image_models") or []) if m]
        if defaults:
            model = defaults[0]
            logger.info(f"[Generation] 模型未指定，回退供应商 '{provider_id}' 默认模型: {model}")

    # ① 尝试画布路由（画布在线 + provider 画布可处理；带参考图时跳过，画布不接收参考图）
    if not refs:
        canvas_result = await _try_canvas_image_generation(
            provider_id, model, prompt, size=size, aspect_ratio=aspect_ratio
        )
        if canvas_result:
            return canvas_result

    # ② 本地直连逻辑（原有路径）
    cfg = await get_provider_config_async(provider_id)

    # CLI 协议 → AgyCliImageAdapter（不支持参考图；带参考图时降级走反代多模态路径）
    if cfg and cfg.get("protocol") in CLI_PROTOCOLS and not refs:
        logger.info(f"[Generation] CLI 协议 '{provider_id}' → AgyCliImageAdapter")
        adapter = AgyCliImageAdapter()
        try:
            result = await adapter.generate_image(prompt, aspect_ratio=aspect_ratio, resolution=resolution)
        except AdapterError as e:
            raise GenerationError(str(e)) from e
        if result.image_urls:
            return result.image_urls[0]
        raise GenerationError("agy CLI 未返回图片")

    # 其他供应商 → OpenAICompatImageAdapter
    base_url, api_key, effective_model = await resolve_openai_endpoint_async(provider_id, model)
    adapter_img = OpenAICompatImageAdapter(base_url=base_url, api_key=api_key, model=effective_model)

    logger.info(f"[Generation] image(本地): provider={provider_id}, model={effective_model}, refs={len(refs)}")
    try:
        result = await adapter_img.generate_image(
            prompt, size=size, aspect_ratio=aspect_ratio, reference_images=refs
        )
    except AdapterError as e:
        raise GenerationError(str(e)) from e
    finally:
        # 临时实例不复用：关闭底层 httpx 连接池，避免每次生图泄漏
        await adapter_img.close()

    if result.image_urls:
        return result.image_urls[0]
    raise GenerationError("供应商没有返回任何图片")
