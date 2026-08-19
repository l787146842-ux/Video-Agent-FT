"""
供应商调用管线 — 薄代理层（Phase 2: Adapter 归位）。

实际 HTTP 调用逻辑已迁移到 adapters/openai_compat.py 和 adapters/agy_cli.py，
本模块仅负责：
1. 根据 provider_config 解析端点参数（配置源职责仍在 provider_config）
2. 构造对应的 Adapter 实例
3. 将 AdapterError 统一转译为面向用户的 GenerationError

供 routes/generate.py、routes/agent.py、routes/workflow.py 共用。
"""
import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.exceptions import AdapterError, GenerationError
from src.video_agent.config import settings
from src.video_agent.web.task_manager import get_task_manager
from src.video_agent.web.provider_config import (
    CLI_PROTOCOLS,
    get_api_key,
    get_api_key_async,
    get_canvas_provider_ids_async,
    get_provider_config,
    get_provider_config_async,
    is_mock_provider,
    is_mock_provider_async,
    load_merged_providers_async,
    resolve_provider_ref,
    resolve_provider_ref_async,
)
from src.video_agent.adapters.openai_compat import (
    OpenAICompatChatAdapter,
    OpenAICompatImageAdapter,
    extract_base64_image,
    persist_data_uri,
)
from src.video_agent.adapters.agy_cli import AgyCliImageAdapter
from src.video_agent.adapters.canvas_adapter import get_canvas_adapter
from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete
from src.video_agent.state import storyboard_ops as ops


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
                # 无需改代码，改环境变量即可（曾硬编码 gemini-3.1-flash-image 导致 400）
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
    from src.video_agent.web.provider_config import (
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
    内部委托给 OpenAICompatChatAdapter.chat()。
    thinking_level：本次调用思考档位覆盖（None=沿用全局配置，2222 二轮）。
    response_format（audit-0819d）：结构化输出声明（如 {"type":"json_object"}），
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
    内部委托给 OpenAICompatChatAdapter.chat_stream()。
    thinking_level：本次调用思考档位覆盖（None=沿用全局配置，2222 二轮）。
    response_format（audit-0819d）：结构化输出声明（如 {"type":"json_object"}），
    端点不支持时适配器兼容探针自动剥离降级。
    返回 (完整内容, finish_reason)。失败抛 GenerationError。
    reasoning_sink（可选）：传入 list 则累积推理模型的思考增量（黑匣子取证用，
    888 事故），不进上下文。
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
                # 不再一律当 stop：截断检测靠它（888 事故）
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


# ---------- 生成侧降级链（7777 二轮：同模型跨厂商，失败才触发） ----------

# 不可重试的失败特征：内容审核/鉴权/配置类错误换厂商也无意义，直接报错
_NON_RETRYABLE_GEN_HINTS = (
    "审核", "敏感", "违规", "moderation", "unauthorized",
    "余额不足", "未配置", "400", "401", "403", "404",
)


def _is_retryable_gen_error(e: Exception) -> bool:
    """生成任务失败是否可换厂商重试。

    优先结构化标记（AdapterError.retryable，含 __cause__ 转译链）；
    无标记时除内容审核/鉴权/配置类特征外默认可重试（生成失败多为
    厂商容量/排队问题，同模型换厂商有机会）。
    """
    for obj in (e, getattr(e, "__cause__", None)):
        flag = getattr(obj, "retryable", None)
        if isinstance(flag, bool):
            return flag
    msg = str(e)
    return not any(h in msg for h in _NON_RETRYABLE_GEN_HINTS)


async def _gen_fallback_candidates(provider_id: str, model: str, kind: str) -> List[tuple]:
    """生成侧 fallback 候选链：同模型跨厂商，模型永不换。

    主 (provider, model) → 其他启用供应商中明确在 image_models/video_models
    里列出同名模型的供应商（kind=image/video）。模型列表为空的供应商
    无法验证是否提供该模型，不入链（用户审定：空列表不选）。
    mock 供应商不入链；总长度受 settings.model_fallback_max_candidates 限制。
    """
    limit = max(1, settings.model_fallback_max_candidates)
    candidates: List[tuple] = [(provider_id, model)]
    if not str(model or "").strip():
        return candidates[:limit]
    if await is_mock_provider_async(provider_id, model):
        return candidates[:limit]
    try:
        providers = await load_merged_providers_async()
    except Exception:
        return candidates[:limit]
    models_key = "image_models" if kind == "image" else "video_models"
    for p in providers:
        if len(candidates) >= limit:
            break
        pid = p.get("id") or ""
        if not pid or pid == provider_id or not p.get("enabled", True):
            continue
        if await is_mock_provider_async(pid):
            continue
        models = [str(m or "").strip() for m in (p.get(models_key) or [])]
        if model in models and (pid, model) not in candidates:
            candidates.append((pid, model))
    return candidates[:limit]


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

    # 空模型兑底（彻底修复「model not register: ''/MissingParameter」）：
    # 模型解析优先级：规格文档指定（LLM action 参数）→ 预览框草稿参数
    # （action_executor 已按此链传入）→ 供应商配置的第一个图片模型
    cfg0 = await get_provider_config_async(provider_id)
    if cfg0 and not model and not await is_mock_provider_async(provider_id, model):
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


# ---------- 生图并发节流 + 429 退避 + 连败熔断（4444） ----------
# 15 张并发提交全撞 429（4444 现场）：并发上限 settings.image_gen_concurrency；
# 429 指数退避重试 2 次；同供应商连败 ≥6 且 60s 内熔断开路，新提交直接报错
# （P2 确定性拦截，防模型一轮轮反复触发整批）。
_image_gen_sem: Optional[asyncio.Semaphore] = None
_IMAGE_FAIL_STREAK: Dict[str, Dict[str, float]] = {}
IMAGE_CIRCUIT_THRESHOLD = 6
IMAGE_CIRCUIT_WINDOW = 60.0

IMAGE_CIRCUIT_ERROR = (
    "出图渠道连败熔断：上游持续限流/报错。请约 1 分钟后重试，"
    "或在 API 配置/规格文档更换出图渠道。"
)


def _get_image_sem() -> asyncio.Semaphore:
    global _image_gen_sem
    if _image_gen_sem is None:
        _image_gen_sem = asyncio.Semaphore(max(1, settings.image_gen_concurrency))
    return _image_gen_sem


def image_circuit_open(provider_id: str) -> bool:
    st = _IMAGE_FAIL_STREAK.get(provider_id or "")
    return bool(
        st and st["n"] >= IMAGE_CIRCUIT_THRESHOLD
        and (time.time() - st["ts"]) < IMAGE_CIRCUIT_WINDOW
    )


def _image_result(provider_id: str, ok: bool) -> None:
    st = _IMAGE_FAIL_STREAK.setdefault(provider_id or "", {"n": 0.0, "ts": 0.0})
    if ok:
        st["n"] = 0.0
    else:
        st["n"] += 1
        st["ts"] = time.time()


async def _gen_image_throttled(
    pid: str, mdl: str, prompt: str, *, size: str,
    aspect_ratio: str, resolution: str, reference_images: Optional[List] = None,
) -> str:
    """并发节流 + 429 退避的生图调用（4444）。退避等待不占并发位。"""
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            async with _get_image_sem():
                url = await generate_image_via_provider(
                    pid, mdl, prompt, size=size, aspect_ratio=aspect_ratio,
                    resolution=resolution, reference_images=reference_images,
                )
            _image_result(pid, True)
            return url
        except Exception as e:
            last = e
            _image_result(pid, False)
            if "429" in str(e) and attempt < 2:
                logger.warning(f"[Generation] 生图 429 限流，退避 {5 * (attempt + 1)}s 重试（{pid}）")
                await asyncio.sleep(5 * (attempt + 1))
                continue
            raise
    raise last or GenerationError("生图失败")


def submit_image_task(
    state_dict: Dict[str, Any],
    draft: Dict[str, Any],
    provider_id: str,
    model: str,
    refs: List[Dict],
    aspect_ratio: str = "16:9",
    resolution: str = "1K",
    on_failure_save=None,
    draft_type: str = "keyElement",
) -> str:
    """提交异步生图任务（通过 GenerationTaskManager 统一管理）。

    从 action_executor 下沉（批次5）：Agent 与路由层共用的生图提交管线。
    尺寸由 比例 + 分辨率档位（1K/2K/4K）计算，确保生图模型感知分辨率。
    提示词中的 @引用会被解析为位置标记，被引用的素材（refAssets +
    sceneRefs 参考图）随请求发送给多模态生图模型。
    on_failure_save: 失败时调用的持久化回调（通常为 svc.save_debounced）。
    返回 task_id。
    """
    import time

    from src.video_agent.utils import gen_id
    from src.video_agent.web.prompt_refs import (
        build_storyboard_media_map,
        resolve_prompt_mentions,
    )
    from src.video_agent.web.task_manager import get_task_manager, writeback_if_complete

    tm = get_task_manager()
    task_id = f"{gen_id('img')}-{draft.get('id', 'x')[-4:]}"
    size = image_size_for(aspect_ratio, resolution)
    size_note = f"{size} ({aspect_ratio}, {resolution})"

    # 连败熔断（4444）：上游持续限流时新提交直接报错，不再起整批任务
    if image_circuit_open(provider_id):
        raise GenerationError(IMAGE_CIRCUIT_ERROR)

    # --- 解析 @引用：重写提示词 + 汇总参考图（草稿自身 refAssets 优先，sceneRefs 其次）---
    base_ref_urls: List[str] = [u for u in (draft.get("refAssets") or []) if u]
    for r in refs:
        u = r.get("url") if isinstance(r, dict) else ""
        if u and u not in base_ref_urls:
            base_ref_urls.append(u)
    media_map = build_storyboard_media_map(state_dict)
    eff_prompt, final_refs = resolve_prompt_mentions(
        draft.get("prompt", ""), base_ref_urls, media_map, max_refs=settings.image_ref_limit
    )

    task = tm.create_task(
        task_id,
        status="processing",
        draft_id=draft.get("id", ""),
        draft_type=draft_type,
        prompt=eff_prompt,
        model=model,
        result=None,
    )
    # 可等待 Future：工具/工作流等需要同步等结果的调用方，
    # 提交后可 await wait_image_task(task_id)。结果统一为 ("ok"|"error", payload)，
    # 不用 set_exception 避免无人 await 时的 "exception never retrieved" 告警。
    try:
        task["_done"] = asyncio.get_running_loop().create_future()
    except RuntimeError:
        pass  # 无事件循环（单元测试）时不可等待，靠任务状态轮询兑底
    prev_tag = draft.get("tag") or ""
    draft["tag"] = "生成中"
    # 生成日志：提交即记录 started；前端据此立即点亮卡片转圈（改进2）
    tm.record_gen_log(
        media_type="image", status="started", provider=provider_id, model=model,
        prompt=eff_prompt, draft_id=draft.get("id", ""), requested_size=size_note,
        source="agent", task_id=task_id,
    )
    tm.notify({
        "task_id": task_id, "status": "started", "kind": "image",
        "draft_id": draft.get("id", ""),
    })

    async def _run():
        t0 = time.time()
        task = tm.get_task(task_id)
        # 同模型跨厂商降级（7777 二轮）：仅当主厂商失败且为可重试故障时，
        # 才换提供同一模型的其他厂商；首个成功即止，模型永不换
        candidates = [(provider_id, model)]
        try:
            url = None
            used_pid, used_model = provider_id, model
            last_err: Optional[Exception] = None
            idx = 0
            while True:
                pid, mdl = candidates[idx]
                try:
                    url = await _gen_image_throttled(
                        pid, mdl, eff_prompt,
                        size=size, aspect_ratio=aspect_ratio, resolution=resolution,
                        reference_images=final_refs,
                    )
                    used_pid, used_model = pid, mdl
                    break
                except Exception as e:
                    last_err = e
                    if not _is_retryable_gen_error(e) or not settings.model_fallback_enabled:
                        raise
                    if idx == len(candidates) - 1:
                        # 首次失败才拉取同模型跨厂商候选，避免主厂商成功时
                        # 无事加载供应商配置/画布（阻塞生图提交）
                        fallback = await _gen_fallback_candidates(provider_id, model, "image")
                        extra = [c for c in fallback if c not in candidates]
                        if not extra:
                            raise
                        candidates.extend(extra)
                    logger.warning(
                        f"[Generation] 生图厂商 {pid} 失败（{str(e)[:60]}），"
                        f"同模型 {mdl} 切换厂商 {candidates[idx + 1][0]} 重试"
                    )
                    idx += 1
            if url is None:  # 理论不可达（成功 break / 失败 raise），防御兜底
                raise last_err or GenerationError("生图失败")
            # 降级后实际生效的厂商回写草稿参数栏 + 持久化（与提交时预选一致）
            if used_pid != provider_id:
                draft["providerId"] = used_pid
                if used_model:
                    draft["model"] = used_model
                if on_failure_save is not None:
                    on_failure_save()
            if task:
                elapsed = round(time.time() - t0, 1)
                tm.update_task(task_id, status="succeeded", result={"images": [url]}, elapsed=elapsed)
                tm.notify({
                    "task_id": task_id, "status": "succeeded", "kind": "image",
                    "draft_id": draft.get("id", ""),
                    "result": {"images": [url]}, "elapsed": elapsed,
                })
                tm.record_gen_log(
                    media_type="image", status="succeeded", provider=used_pid, model=used_model,
                    prompt=eff_prompt, draft_id=draft.get("id", ""), result_url=url,
                    elapsed=elapsed, requested_size=size_note, source="agent",
                    task_id=task_id,
                )
                writeback_if_complete(task_id)
                fut = task.get("_done")
                if fut is not None and not fut.done():
                    fut.set_result(("ok", url))
        except Exception as e:  # 统一兜底（含 GenerationError），保证任务状态闭环
            draft["tag"] = prev_tag  # 失败时恢复原标签，避免卡片永远卡在"生成中"
            if on_failure_save is not None:
                on_failure_save()
            elapsed = round(time.time() - t0, 1)
            tm.update_task(task_id, status="failed", error=str(e), elapsed=elapsed)
            tm.notify({
                "task_id": task_id, "status": "failed", "kind": "image",
                "draft_id": draft.get("id", ""), "error": str(e), "elapsed": elapsed,
            })
            tm.record_gen_log(
                media_type="image", status="failed", provider=provider_id, model=model,
                prompt=eff_prompt, draft_id=draft.get("id", ""), error=str(e),
                elapsed=elapsed, requested_size=size_note, source="agent",
                task_id=task_id,
            )
            fut = task.get("_done") if task else None
            if fut is not None and not fut.done():
                fut.set_result(("error", str(e)))
            logger.warning(f"[StudioActions] 生图失败 {draft.get('id')}: {e}")

    try:
        tm.track(_run())
    except RuntimeError:
        pass  # 无事件循环时跳过（单元测试场景）
    return task_id


async def wait_image_task(task_id: str, timeout: float = 600.0) -> Tuple[bool, str]:
    """等待 submit_image_task 提交的生图任务到达终态。

    返回 (是否成功, 图片URL或错误信息)。超时返回失败。
    供 image_generate 工具与工作流使用：提交走统一任务管线
    （生成日志 + SSE 读秒），本函数只负责同步等结果。
    """
    tm = get_task_manager()
    task = tm.get_task(task_id)
    if not task:
        return False, "任务不存在"
    fut = task.get("_done")
    if fut is not None:
        try:
            # shield：超时只放弃等待，不取消共享 Future（任务继续跑完写回草稿）
            status, payload = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            return status == "ok", payload
        except asyncio.TimeoutError:
            return False, f"生成超时（{int(timeout)}s）"
    # 兑底：提交时无事件循环（无 Future），轮询任务状态
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        t = tm.get_task(task_id)
        if not t:
            return False, "任务已丢失"
        st = t.get("status")
        if st in ("succeeded", "completed"):
            imgs = (t.get("result") or {}).get("images") or []
            return (True, imgs[0]) if imgs else (False, "供应商没有返回任何图片")
        if st == "failed":
            return False, t.get("error") or "生成失败"
        await asyncio.sleep(1)
    return False, f"生成超时（{int(timeout)}s）"


# ---------- 视频生成（分镜参考自动挂接 + 统一提交管线） ----------

# 音频扩展名：用于把 refAssets/素材 URL 里的音色参考音频从参考图里分离出来
_AUDIO_URL_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


def is_audio_url(url: str) -> bool:
    """按扩展名判断 URL 是否音频素材（去 query/hash 后判断）"""
    u = str(url or "").strip().lower().split("?")[0].split("#")[0]
    return u.endswith(_AUDIO_URL_EXTS)


def collect_shot_video_refs(
    state_dict: Dict[str, Any],
    group: Optional[Dict[str, Any]],
    draft: Dict[str, Any],
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """自动收集分镜视频生成的参考素材：
    1. sceneRefs 引用的关键元素概念图（多参考图，role=reference）；
    2. 草稿 refAssets / audioUrl 中的音色参考音频（role=reference_audio）。

    返回 (image_refs, audio_refs)，均已去重；限额取 settings（C3：Seedance 2.5 口径）。
    """
    image_refs: List[Dict[str, str]] = ops.resolve_scene_refs(
        state_dict, group, limit=settings.video_ref_limit_image
    )

    audio_refs: List[Dict[str, str]] = []
    seen_audio: set = set()
    for url in list(draft.get("refAssets") or []) + [draft.get("audioUrl") or ""]:
        url = str(url or "").strip()
        if not url or url in seen_audio or not is_audio_url(url):
            continue
        seen_audio.add(url)
        audio_refs.append({"url": url, "role": "reference_audio"})
    return image_refs, audio_refs[:settings.video_ref_limit_audio]


def submit_video_task(
    state_dict: Dict[str, Any],
    draft: Dict[str, Any],
    draft_type: str,
    provider_id: str,
    model: str,
    *,
    duration: int = 5,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    image_refs: Optional[List[Dict[str, str]]] = None,
    video_refs: Optional[List[Dict[str, str]]] = None,
    audio_refs: Optional[List[Dict[str, str]]] = None,
    source: str = "agent",
    on_failure_save=None,
) -> str:
    """提交异步视频生成任务（Agent 与路由层共用）。

    参考素材自动挂接：
    - 提示词 @引用 → 位置标记重写 + 对应素材随请求发送；
    - image_refs/audio_refs（分镜 sceneRefs 元素图与音色参考音频）与 @引用去重合并；
    - 存在任一参考素材时走 Seedance 2.0 MultiModalToVideo 媒体列表格式，
      无参考时回退经典首帧格式。
    on_failure_save: 失败时调用的持久化回调（通常为 svc.save_debounced）。
    返回 task_id。失败抛 GenerationError。
    """
    import time

    from src.video_agent.utils import gen_id
    from src.video_agent.web.prompt_refs import (
        build_storyboard_media_map,
        resolve_prompt_mentions,
    )
    from src.video_agent.web.provider_config import is_mock_provider
    from src.video_agent.web.task_manager import get_task_manager, writeback_if_complete

    provider_id = resolve_provider_ref(provider_id)

    # --- @引用解析 + 参考素材合并去重（草稿 refAssets 优先，显式参考其次）---
    base_ref_urls: List[str] = [u for u in (draft.get("refAssets") or []) if u]
    for r in (image_refs or []) + (video_refs or []) + (audio_refs or []):
        u = str((r or {}).get("url") or "").strip()
        if u and u not in base_ref_urls:
            base_ref_urls.append(u)
    media_map = build_storyboard_media_map(state_dict)
    eff_prompt, final_refs = resolve_prompt_mentions(
        draft.get("prompt", ""), base_ref_urls, media_map,
        max_refs=settings.video_ref_limit_total,
    )

    # 按媒体类型三桶拆分（C3）：图/视频/音频；视频类参考原先被静默丢弃，
    # 现走独立 reference_video 通道（Seedance 2.5 支持 ≤10 段视频参考）
    explicit_role = {
        str(r.get("url")): r.get("role")
        for r in (image_refs or []) + (video_refs or []) if r.get("url")
    }
    out_images: List[Dict[str, str]] = []
    out_videos: List[Dict[str, str]] = []
    out_audios: List[Dict[str, str]] = []
    for u in final_refs:
        kind = (media_map.get(u) or {}).get("kind") or ""
        role = explicit_role.get(u, "")
        if role == "reference_video" or kind == "video":
            out_videos.append({"url": u, "role": role or "reference_video"})
        elif kind == "audio" or (kind not in ("image", "video") and is_audio_url(u)):
            out_audios.append({"url": u, "role": "reference_audio"})
        else:
            out_images.append({"url": u, "role": role or "reference"})
    out_images = out_images[:settings.video_ref_limit_image]
    out_videos = out_videos[:settings.video_ref_limit_video]
    out_audios = out_audios[:settings.video_ref_limit_audio]

    media_refs_payload = out_images + out_videos + out_audios

    # 供应商适配器：真实供应商从启动注册的适配器表取；mock 解析为 mock_video
    from src.video_agent.web.providers import resolve_adapter_name
    if is_mock_provider(provider_id, model):
        adapter_name = resolve_adapter_name(provider_id, "video")
    else:
        adapter_name = provider_id or "modelscope"
    try:
        adapter = AdapterFactory.get_adapter("video_generation", adapter_name)
    except ValueError as e:
        raise GenerationError(
            f"供应商 '{adapter_name}' 的视频生成尚未配置，请先在 API 设置中添加 video_models"
        ) from e

    # 空模型兑底：供应商配置的第一个视频模型
    if not model and not is_mock_provider(provider_id, model):
        cfg0 = get_provider_config(provider_id)
        if cfg0:
            defaults = [m for m in (cfg0.get("video_models") or []) if m]
            if defaults:
                model = defaults[0]
                logger.info(f"[Generation] 视频模型未指定，回退供应商 '{provider_id}' 默认: {model}")

    tm = get_task_manager()
    task_id = f"{gen_id('vid')}-{draft.get('id', 'x')[-4:]}"
    size_note = f"{resolution} ({aspect_ratio}, {duration}s)"

    tm.create_task(
        task_id,
        status="processing",
        adapter_type="video_generation",
        adapter_name=adapter_name,
        draft_id=draft.get("id", ""),
        draft_type=draft_type,
        prompt=eff_prompt,
        model=model,
        result=None,
    )
    prev_tag = draft.get("tag") or ""
    draft["tag"] = "生成中"
    tm.record_gen_log(
        media_type="video", status="started", provider=provider_id, model=model,
        prompt=eff_prompt, draft_id=draft.get("id", ""), requested_size=size_note,
        source=source, task_id=task_id,
    )
    tm.notify({
        "task_id": task_id, "status": "started", "kind": "video",
        "draft_id": draft.get("id", ""),
    })

    async def _run():
        t0 = time.time()
        task = tm.get_task(task_id)
        # 同模型跨厂商降级（7777 二轮）：仅当主厂商失败且为可重试故障时，
        # 才换提供同一模型的其他厂商；首个成功即止，模型永不换
        candidates = [(provider_id, model)]
        try:
            first_frame = out_images[0]["url"] if out_images and out_images[0].get("role") == "first_frame" else ""
            result = None
            used_pid, used_model = provider_id, model
            last_err: Optional[Exception] = None
            idx = 0
            while True:
                pid, mdl = candidates[idx]
                try:
                    if idx == 0:
                        adapter_c = adapter
                    else:
                        if is_mock_provider(pid, mdl):
                            adapter_name_c = resolve_adapter_name(pid, "video")
                        else:
                            adapter_name_c = pid or "modelscope"
                        adapter_c = AdapterFactory.get_adapter("video_generation", adapter_name_c)
                    result = await adapter_c.generate(
                        image_url=first_frame,
                        prompt=eff_prompt,
                        model=mdl or None,
                        duration=duration,
                        resolution=resolution,
                        aspect_ratio=aspect_ratio,
                        media_refs=media_refs_payload or None,
                    )
                    if result.status != "completed":
                        # 异步任务：轮询等待结果（MMG 文档建议整体预算至少 30 分钟）
                        result = await wait_until_complete(adapter_c, result.task_id, timeout=1800)
                    if not str(getattr(result, "video_url", "") or ""):
                        raise GenerationError("视频生成未返回结果")
                    used_pid, used_model = pid, mdl
                    break
                except Exception as e:
                    last_err = e
                    if not _is_retryable_gen_error(e) or not settings.model_fallback_enabled:
                        raise
                    if idx == len(candidates) - 1:
                        # 首次失败才拉取同模型跨厂商候选，避免主厂商成功时
                        # 无事加载供应商配置/画布（阻塞出视频提交）
                        fallback = await _gen_fallback_candidates(provider_id, model, "video")
                        extra = [c for c in fallback if c not in candidates]
                        if not extra:
                            raise
                        candidates.extend(extra)
                    logger.warning(
                        f"[Generation] 视频厂商 {pid} 失败（{str(e)[:60]}），"
                        f"同模型 {mdl} 切换厂商 {candidates[idx + 1][0]} 重试"
                    )
                    idx += 1
            if result is None:  # 理论不可达（成功 break / 失败 raise），防御兜底
                raise last_err or GenerationError("视频生成失败")
            # 降级后实际生效的厂商回写草稿参数栏 + 持久化
            if used_pid != provider_id:
                draft["providerId"] = used_pid
                if used_model:
                    draft["model"] = used_model
                if on_failure_save is not None:
                    on_failure_save()
            if task:
                elapsed = round(time.time() - t0, 1)
                tm.update_task(task_id, status="succeeded", result={"videos": [result.video_url]}, elapsed=elapsed)
                tm.notify({
                    "task_id": task_id, "status": "succeeded", "kind": "video",
                    "draft_id": draft.get("id", ""),
                    "result": {"videos": [result.video_url]}, "elapsed": elapsed,
                })
                tm.record_gen_log(
                    media_type="video", status="succeeded", provider=used_pid, model=used_model,
                    prompt=eff_prompt, draft_id=draft.get("id", ""), result_url=result.video_url,
                    elapsed=elapsed, requested_size=size_note, source=source,
                    task_id=task_id,
                )
                writeback_if_complete(task_id)
        except Exception as e:  # 统一兑底，保证任务状态闭环
            draft["tag"] = prev_tag  # 失败时恢复原标签，避免卡片永远卡在"生成中"
            if on_failure_save is not None:
                on_failure_save()
            elapsed = round(time.time() - t0, 1)
            tm.update_task(task_id, status="failed", error=str(e), elapsed=elapsed)
            tm.notify({
                "task_id": task_id, "status": "failed", "kind": "video",
                "draft_id": draft.get("id", ""), "error": str(e), "elapsed": elapsed,
            })
            tm.record_gen_log(
                media_type="video", status="failed", provider=provider_id, model=model,
                prompt=eff_prompt, draft_id=draft.get("id", ""), error=str(e),
                elapsed=elapsed, requested_size=size_note, source=source,
                task_id=task_id,
            )
            logger.warning(f"[StudioActions] 视频生成失败 {draft.get('id')}: {e}")

    try:
        tm.track(_run())
    except RuntimeError:
        pass  # 无事件循环时跳过（单元测试场景）
    return task_id
