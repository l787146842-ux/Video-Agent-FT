"""
生成任务提交与等待（generation.py 三段之三）。

职责：生图/生视频异步任务的统一提交管线（GenerationTaskManager 登记 +
@引用解析 + 参考素材挂接 + 同模型跨厂商降级 + 生成日志/SSE 闭环），
以及分镜视频参考素材收集与任务等待。
供 routes/、core（经 ports.generation 端口）、tools/ 共用。
"""
import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.exceptions import GenerationError
from src.video_agent.config import settings
from src.video_agent.web.task_manager import get_task_manager
from src.video_agent.core.provider_config import (
    get_provider_config,
    resolve_provider_ref,
)
from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete
from src.video_agent.state import storyboard_ops as ops
# 批次E：生成侧降级链直连实现体 core/generation_fallback，保私有别名使
# 本模块内用法零改动。
from src.video_agent.core.generation_fallback import (
    gen_fallback_candidates as _gen_fallback_candidates,
    is_retryable_gen_error as _is_retryable_gen_error,
)
from src.video_agent.web.generation_dispatch import (
    image_size_for,
)
from src.video_agent.web.generation_channel import (
    IMAGE_CIRCUIT_ERROR,
    VIDEO_CIRCUIT_ERROR,
    _gen_image_throttled,
    image_circuit_open,
    video_channel,
)


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

    从 action_executor 下沉：Agent 与路由层共用的生图提交管线。
    尺寸由 比例 + 分辨率档位（1K/2K/4K）计算，确保生图模型感知分辨率。
    提示词中的 @引用会被解析为位置标记，被引用的素材（refAssets +
    sceneRefs 参考图）随请求发送给多模态生图模型。
    on_failure_save: 失败时调用的持久化回调（通常为 svc.save_debounced）。
    返回 task_id。
    """
    import time

    from src.video_agent.utils import gen_id
    from src.video_agent.core.prompt_refs import (
        build_storyboard_media_map,
        resolve_prompt_mentions,
    )
    from src.video_agent.web.task_manager import get_task_manager, writeback_if_complete

    tm = get_task_manager()
    task_id = f"{gen_id('img')}-{draft.get('id', 'x')[-4:]}"
    size = image_size_for(aspect_ratio, resolution)
    size_note = f"{size} ({aspect_ratio}, {resolution})"

    # 连败熔断：上游持续限流时新提交直接报错，不再起整批任务
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
        pass  # 无事件循环（单元测试）时不可等待，靠任务状态轮询兜底
    prev_tag = draft.get("tag") or ""
    draft["tag"] = "生成中"
    # 生成日志：提交即记录 started；前端据此立即点亮卡片转圈
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
        # 同模型跨厂商降级：仅当主厂商失败且为可重试故障时，
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
    # 兜底：提交时无事件循环（无 Future），轮询任务状态
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
    2. 草稿 refAssets / audioUrl 中的音色参考音频（role=reference_audio）；
    3. 批 6 · A3：sceneRefs 引用元素的 audioUrl（元素自带音色锚点，
       外部标杆「按引用自动挂声音锚点」形态）同轴自动挂为 reference_audio。

    返回 (image_refs, audio_refs)，均已去重；限额取 settings（C3：Seedance 2.5 口径）。
    """
    image_refs: List[Dict[str, str]] = ops.resolve_scene_refs(
        state_dict, group, limit=settings.video_ref_limit_image
    )

    audio_refs: List[Dict[str, str]] = []
    seen_audio: set = set()
    scene_audio = ops.resolve_scene_audio_refs(state_dict, group)
    for url in ([r["url"] for r in scene_audio]
                + list(draft.get("refAssets") or [])
                + [draft.get("audioUrl") or ""]):
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
    from src.video_agent.core.prompt_refs import (
        build_storyboard_media_map,
        resolve_prompt_mentions,
    )
    from src.video_agent.web.task_manager import get_task_manager, writeback_if_complete

    provider_id = resolve_provider_ref(provider_id)

    # 空供应商：明确报错（演示兜底已删除）
    if not (provider_id or "").strip():
        raise GenerationError("尚未配置生成供应商，请先到「设置」中配置生成供应商")

    # 连败熔断：上游持续限流时新提交直接报错，不再起整批任务（与生图同口径）
    if video_channel.circuit_open(provider_id):
        raise GenerationError(VIDEO_CIRCUIT_ERROR)

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

    # 供应商适配器：从启动注册的适配器表取
    adapter_name = provider_id or "modelscope"
    try:
        adapter = AdapterFactory.get_adapter("video_generation", adapter_name)
    except ValueError as e:
        raise GenerationError(
            f"供应商 '{adapter_name}' 的视频生成尚未配置，请先在 API 设置中添加 video_models"
        ) from e

    # 空模型兜底：供应商配置的第一个视频模型
    if not model:
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
        # 同模型跨厂商降级：仅当主厂商失败且为可重试故障时，
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
                        adapter_name_c = pid or "modelscope"
                        adapter_c = AdapterFactory.get_adapter("video_generation", adapter_name_c)
                    # 有界并发：供应商提交调用经 video 通道节流
                    # （信号量 + 429 退避 + 连败熔断）；异步任务的长轮询等待
                    # 不占并发位，避免长任务饿死保守并发上限
                    result = await video_channel.run(
                        pid, adapter_c.generate,
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
        except Exception as e:  # 统一兜底，保证任务状态闭环
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
