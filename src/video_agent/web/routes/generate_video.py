"""/api/generate 视频生成端点。

真实供应商：通过 OpenAICompatVideoAdapter 调用异步视频生成 API。
未配置供应商：明确报错（演示兜底已删除）。
"""
import time
from typing import Dict, List

from fastapi import APIRouter

from loguru import logger

from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete
from src.video_agent.exceptions import VideoAgentError
from src.video_agent.state.manager import StateManager
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.utils import gen_id
from src.video_agent.web.generation import collect_shot_video_refs

from .generate_common import (
    VideoGenRequest,
    _new_task,
    _notify_sse,
    _tm,
    _track_task,
    _writeback_if_complete,
)

router = APIRouter()


@router.post("/generate/video")
@router.post("/canvas-video")
async def generate_video(body: VideoGenRequest):
    """
    提交视频生成任务。
    真实供应商：通过 OpenAICompatVideoAdapter 调用异步视频生成 API。
    未配置供应商：明确报错。
    """
    # 空供应商：明确报错（不再有演示兜底）
    if not (body.provider_id or "").strip():
        raise VideoAgentError(
            "尚未配置生成供应商，请先到「设置」中配置生成供应商",
            status_code=400, error_code="PROVIDER_NOT_CONFIGURED")

    # ---------- 真实供应商：异步任务 ----------
    adapter_name = body.provider_id or "modelscope"
    try:
        adapter = AdapterFactory.get_adapter("video_generation", adapter_name)
    except ValueError:
        raise VideoAgentError(
            (
                f"供应商 '{adapter_name}' 的视频生成尚未配置。"
                "请在 API 设置中为该供应商添加 video_models。"
            ),
            status_code=501,
        )

    task_id = gen_id("vid")
    _new_task(
        task_id,
        status="processing",
        adapter_type="video_generation",
        adapter_name=adapter_name,
        draft_id=body.draft_id,
        draft_type=body.draft_type,
        prompt=body.prompt,
        model=body.model,
        result=None,
    )

    # --- 参考素材汇总：显式传入 + 分镜自动挂接（shotRefs 元素图 + 音色参考音频）---
    image_refs: List[Dict[str, str]] = [
        {"url": i.get("url", ""), "role": i.get("role", "reference")}
        for i in body.images if i.get("url")
    ]
    video_refs: List[Dict[str, str]] = [
        {"url": v.get("url", ""), "role": v.get("role", "reference_video")}
        for v in body.videos if v.get("url")
    ]
    audio_refs: List[Dict[str, str]] = [
        {"url": a.get("url", ""), "role": "reference_audio"}
        for a in body.audios if a.get("url")
    ]
    if body.draft_id:
        try:
            svc = StateManager.get_instance()
            found = ops.find_draft(svc.state_dict, body.draft_id, body.draft_type)
            if found:
                group, draft = found
                auto_imgs, auto_audios = collect_shot_video_refs(svc.state_dict, group, draft)
                seen_img = {r["url"] for r in image_refs}
                for r in auto_imgs:
                    if r["url"] not in seen_img:
                        image_refs.append(r)
                        seen_img.add(r["url"])
                seen_aud = {r["url"] for r in audio_refs}
                for r in auto_audios:
                    if r["url"] not in seen_aud:
                        audio_refs.append(r)
                        seen_aud.add(r["url"])
        except Exception as e:  # 参考挂接失败不阻断生成主链路
            logger.warning(f"[Generate] 分镜参考自动挂接失败: {e}")
    # 按 Seedance 2.5 多模态参考能力收口（图片 ≤30 / 视频 ≤10 / 音频 ≤10，共 50）
    from src.video_agent.config import settings
    image_refs = image_refs[: settings.video_ref_limit_image]
    video_refs = video_refs[: settings.video_ref_limit_video]
    audio_refs = audio_refs[: settings.video_ref_limit_audio]
    media_refs = image_refs + video_refs + audio_refs

    # 首帧：显式 first_frame 标注优先，否则取第一张图（兼容旧行为）
    image_url = next(
        (r["url"] for r in image_refs if r.get("role") == "first_frame"),
        image_refs[0]["url"] if image_refs else "",
    )
    if media_refs:
        logger.info(
            f"[Generate] 视频任务参考素材: 图片 {len(image_refs)} 张 + 音频 {len(audio_refs)} 条"
        )

    async def _run_video_generation():
        t0 = time.monotonic()
        task = _tm.tasks.get(task_id)
        size_note = f"{body.resolution} ({body.aspect_ratio}, {body.duration}s)"
        try:
            result = await adapter.generate(
                image_url=image_url,
                prompt=body.prompt,
                model=body.model or None,
                duration=body.duration,
                resolution=body.resolution,
                aspect_ratio=body.aspect_ratio,
                media_refs=media_refs or None,
            )
            if result.status == "completed" and result.video_url:
                # 同步返回结果
                if task:
                    task["status"] = "succeeded"
                    task["video_url"] = result.video_url
                    task["elapsed"] = round(time.monotonic() - t0, 1)
                    _writeback_if_complete(task_id)
                    _notify_sse({"task_id": task_id, "status": "succeeded", "kind": "video",
                                 "draft_id": body.draft_id, "video_url": result.video_url, "elapsed": task["elapsed"]})
                    _tm.record_gen_log(
                        media_type="video", status="succeeded", provider=body.provider_id, model=body.model,
                        prompt=body.prompt, draft_id=body.draft_id, result_url=result.video_url,
                        elapsed=task["elapsed"], requested_size=size_note, source="manual",
                        task_id=task_id,
                    )
                return

            # 异步任务：轮询等待结果（MMG 文档建议整体预算至少 30 分钟）
            completed = await wait_until_complete(adapter, result.task_id, timeout=1800)
            if task:
                task["status"] = "succeeded"
                task["video_url"] = completed.video_url
                task["elapsed"] = round(time.monotonic() - t0, 1)
                _writeback_if_complete(task_id)
                _notify_sse({"task_id": task_id, "status": "succeeded", "kind": "video",
                             "draft_id": body.draft_id, "video_url": completed.video_url, "elapsed": task["elapsed"]})
                _tm.record_gen_log(
                    media_type="video", status="succeeded", provider=body.provider_id, model=body.model,
                    prompt=body.prompt, draft_id=body.draft_id, result_url=completed.video_url or "",
                    elapsed=task["elapsed"], requested_size=size_note, source="manual",
                    task_id=task_id,
                )
                logger.info(f"[Generate] 视频生成成功({task['elapsed']}s): {completed.video_url[:80] if completed.video_url else ''}")
        except Exception as e:
            if task:
                task["status"] = "failed"
                task["error"] = str(e)
                task["elapsed"] = round(time.monotonic() - t0, 1)
                _notify_sse({"task_id": task_id, "status": "failed", "kind": "video",
                             "draft_id": body.draft_id, "error": str(e), "elapsed": task["elapsed"]})
                _tm.record_gen_log(
                    media_type="video", status="failed", provider=body.provider_id, model=body.model,
                    prompt=body.prompt, draft_id=body.draft_id, error=str(e),
                    elapsed=task["elapsed"], requested_size=size_note, source="manual",
                    task_id=task_id,
                )
            logger.warning(f"[Generate] 视频生成失败: {e}")

    _tm.record_gen_log(
        media_type="video", status="started", provider=body.provider_id, model=body.model,
        prompt=body.prompt, draft_id=body.draft_id,
        requested_size=f"{body.resolution} ({body.aspect_ratio}, {body.duration}s)", source="manual",
        task_id=task_id,
    )
    _notify_sse({"task_id": task_id, "status": "started", "kind": "video", "draft_id": body.draft_id})
    _track_task(_run_video_generation())
    return {"task_id": task_id, "status": "processing"}
