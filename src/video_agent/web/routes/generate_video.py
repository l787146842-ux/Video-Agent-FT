"""/api/generate 视频生成端点（批次5 从 generate.py 拆出）。

真实供应商：通过 OpenAICompatVideoAdapter 调用异步视频生成 API。
mock 供应商：走 mock 适配器（结果带 mock 标记）。
"""
import time

from fastapi import APIRouter, HTTPException

from loguru import logger

from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete
from src.video_agent.utils import gen_id
from src.video_agent.web.provider_config import is_mock_provider
from src.video_agent.web.providers import resolve_adapter_name

from .generate_common import (
    VideoGenRequest,
    _new_task,
    _notify_sse,
    _tasks,
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
    mock 供应商：走 mock 适配器（结果带 mock 标记）。
    """
    if is_mock_provider(body.provider_id, body.model):
        adapter_name = resolve_adapter_name(body.provider_id, "video")
        try:
            adapter = AdapterFactory.get_adapter("video_generation", adapter_name)
        except ValueError:
            raise HTTPException(status_code=500, detail=f"mock 适配器 '{adapter_name}' 未注册")

        image_url = body.images[0]["url"] if body.images else ""
        result = await adapter.generate(image_url=image_url, prompt=body.prompt)
        _new_task(
            result.task_id,
            status=result.status,
            adapter_type="video_generation",
            adapter_name=adapter_name,
            draft_id=body.draft_id,
            draft_type=body.draft_type,
            mock=True,
            video_url=None,
        )
        _tm.record_gen_log(
            media_type="video", status="succeeded", provider=body.provider_id, model=body.model or "mock-video",
            prompt=body.prompt, draft_id=body.draft_id, mock=True, source="manual",
            task_id=result.task_id,
        )
        logger.info(f"[Generate] [MOCK] 视频任务已提交: {result.task_id}")
        return {"task_id": result.task_id, "mock": True}

    # ---------- 真实供应商：异步任务 ----------
    adapter_name = body.provider_id or "modelscope"
    try:
        adapter = AdapterFactory.get_adapter("video_generation", adapter_name)
    except ValueError:
        raise HTTPException(
            status_code=501,
            detail=(
                f"供应商 '{adapter_name}' 的视频生成尚未配置。"
                "请在 API 设置中为该供应商添加 video_models。"
            ),
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

    image_url = body.images[0]["url"] if body.images else ""

    async def _run_video_generation():
        t0 = time.monotonic()
        task = _tasks.get(task_id)
        size_note = f"{body.resolution} ({body.aspect_ratio}, {body.duration}s)"
        try:
            result = await adapter.generate(
                image_url=image_url,
                prompt=body.prompt,
                model=body.model or None,
                duration=body.duration,
                resolution=body.resolution,
                aspect_ratio=body.aspect_ratio,
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

            # 异步任务：轮询等待结果
            completed = await wait_until_complete(adapter, result.task_id, timeout=600)
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
