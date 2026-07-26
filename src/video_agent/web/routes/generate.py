"""
/api/generate — 生成任务端点

原则：
- 只有用户显式选择 mock 供应商（或 provider 为空）才走 mock，且结果会标注 mock=True；
- 真实供应商失败 → 返回真实错误（HTTP 4xx/5xx + detail），绝不回退假图；
- 视频生成尚未接入真实供应商 → 非 mock 一律 501，明确告知。
"""
import asyncio
import time
import random
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from loguru import logger

from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.web.generation import GenerationError, generate_image_via_provider
from src.video_agent.web.provider_config import is_mock_provider
from src.video_agent.web.providers import resolve_adapter_name
from src.video_agent.web.state_service import StudioStateService

router = APIRouter()

# 任务存储：task_id → {status, adapter_type, adapter_name, draft_id, draft_type, created_at, ...}
_tasks: Dict[str, Dict[str, Any]] = {}

# 任务保留时长（秒）：超过后在下一次写入时清理，防止内存无限增长
_TASK_TTL_SECONDS = 24 * 3600
_TASK_MAX = 500

# mock 视频用可播放的示例视频，而不是死链
MOCK_VIDEO_URL = "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"


def _purge_stale_tasks() -> None:
    now = time.time()
    stale = [
        tid for tid, t in _tasks.items()
        if now - t.get("created_at", now) > _TASK_TTL_SECONDS
    ]
    for tid in stale:
        _tasks.pop(tid, None)
    # 兜底：即使没过期也不允许无限增长，按创建时间淘汰最旧的
    if len(_tasks) > _TASK_MAX:
        for tid in sorted(_tasks, key=lambda t: _tasks[t].get("created_at", 0))[: len(_tasks) - _TASK_MAX]:
            _tasks.pop(tid, None)


def _new_task(task_id: str, **fields: Any) -> Dict[str, Any]:
    _purge_stale_tasks()
    task = {"created_at": time.time(), **fields}
    _tasks[task_id] = task
    return task


class ImageGenRequest(BaseModel):
    prompt: str
    provider_id: str = ""
    model: str = ""
    size: str = "1280x720"
    aspect_ratio: str = "16:9"
    reference_images: List[Dict[str, str]] = []
    # 关联到哪个 draft（完成后服务端自动回写）
    draft_id: str = ""
    draft_type: str = "keyElement"


class VideoGenRequest(BaseModel):
    prompt: str
    provider_id: str = ""
    model: str = ""
    duration: int = 5
    resolution: str = "1080p"
    aspect_ratio: str = "16:9"
    images: List[Dict[str, str]] = []
    enhance_prompt: bool = False
    multimodal: bool = False
    draft_id: str = ""
    draft_type: str = "shot"


@router.post("/generate/image")
@router.post("/canvas-image-tasks")
async def generate_image(body: ImageGenRequest):
    """
    提交图片生成任务。
    真实供应商：OpenAI 兼容 /images/generations，失败回退 chat 生图；再失败 → 报错。
    mock 供应商：走 mock 适配器（结果标注 mock）。
    """
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="提示词不能为空")

    # ---------- mock 路径（仅显式选择） ----------
    if is_mock_provider(body.provider_id, body.model):
        return await _generate_image_mock(body)

    # ---------- 真实供应商：异步任务（立即返回 task_id，前端轮询进度与耗时） ----------
    task_id = f"img-{int(time.time())}-{random.randint(100, 999)}"
    _new_task(
        task_id,
        status="processing",
        draft_id=body.draft_id,
        draft_type=body.draft_type,
        prompt=body.prompt,
        model=body.model,
        result=None,
    )

    async def _run_generation():
        t0 = time.monotonic()
        task = _tasks.get(task_id)
        try:
            image_url = await generate_image_via_provider(
                body.provider_id,
                body.model,
                body.prompt,
                size=body.size or "1024x1024",
                aspect_ratio=body.aspect_ratio,
            )
            if task is None:
                return
            task["status"] = "succeeded"
            task["result"] = {"images": [image_url]}
            task["elapsed"] = round(time.monotonic() - t0, 1)
            _writeback_if_complete(task_id)
            logger.info(f"[Generate] 图片生成成功({task['elapsed']}s): {image_url[:80]}")
        except GenerationError as e:
            if task is not None:
                task["status"] = "failed"
                task["error"] = str(e)
                task["elapsed"] = round(time.monotonic() - t0, 1)
            logger.warning(f"[Generate] 图片生成失败: {e}")
        except Exception as e:
            if task is not None:
                task["status"] = "failed"
                task["error"] = f"服务端异常: {e}"
                task["elapsed"] = round(time.monotonic() - t0, 1)
            logger.exception(f"[Generate] 图片生成异常: {e}")

    asyncio.create_task(_run_generation())
    return {"task_id": task_id, "status": "processing"}


async def _generate_image_mock(body: ImageGenRequest):
    """mock 适配器路径——响应带 mock 标记，前端/用户能分辨"""
    adapter_name = resolve_adapter_name(body.provider_id, "image")
    try:
        adapter = AdapterFactory.get_adapter("image_generation", adapter_name)
    except ValueError:
        raise HTTPException(status_code=500, detail=f"mock 适配器 '{adapter_name}' 未注册")

    ref_url = body.reference_images[0]["url"] if body.reference_images else None
    result = await adapter.generate_image(prompt=body.prompt, reference_image=ref_url)

    _new_task(
        result.task_id,
        status=result.status,
        adapter_type="image_generation",
        adapter_name=adapter_name,
        draft_id=body.draft_id,
        draft_type=body.draft_type,
        prompt=body.prompt,
        model=body.model or "mock-image",
        mock=True,
        result=None,
    )
    logger.info(f"[Generate] [MOCK] 图片任务已提交: {result.task_id}")
    return {"task_id": result.task_id, "mock": True}


@router.get("/generate/image/{task_id}")
@router.get("/canvas-image-tasks/{task_id}")
async def poll_image_task(task_id: str):
    """轮询图片生成任务状态"""
    return await _poll_task(task_id)


@router.post("/generate/video")
@router.post("/canvas-video")
async def generate_video(body: VideoGenRequest):
    """
    提交视频生成任务。
    真实视频供应商尚未接入服务端 → 诚实返回 501，而不是假装生成成功。
    mock 供应商仍可用于流程演示（结果带 mock 标记）。
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
        logger.info(f"[Generate] [MOCK] 视频任务已提交: {result.task_id}")
        return {"task_id": result.task_id, "mock": True}

    raise HTTPException(
        status_code=501,
        detail=(
            f"供应商 '{body.provider_id}' 的视频生成尚未接入服务端。"
            "当前仅 mock 供应商可用于流程演示；真实视频适配器接入后此接口会自动生效。"
        ),
    )


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """通用任务状态查询"""
    return await _poll_task(task_id)


async def _poll_task(task_id: str) -> Dict[str, Any]:
    task = _tasks.get(task_id)
    if not task:
        return {"status": "not_found"}

    if task["status"] in ("succeeded", "completed", "failed"):
        return {**task, "elapsed": task.get("elapsed") or round(time.time() - task.get("created_at", time.time()), 1)}

    adapter_name = task.get("adapter_name", "")
    if adapter_name:
        try:
            adapter = AdapterFactory.get_adapter(task["adapter_type"], adapter_name)
            result = await adapter.fetch_result(task_id)
            if result.status == "completed":
                task["status"] = "succeeded"
                if getattr(result, "video_url", None):
                    # mock 视频适配器返回的是演示占位地址，替换为可播放的示例视频
                    task["video_url"] = MOCK_VIDEO_URL if task.get("mock") else result.video_url
                if getattr(result, "image_urls", None):
                    urls = result.image_urls
                    if task.get("mock"):
                        # mock 图片适配器的 mock-storage.local 是死链，换成可显示的占位图
                        urls = [f"https://picsum.photos/seed/{task_id}/1280/720"]
                    task["result"] = {"images": urls}
                _writeback_if_complete(task_id)
            elif result.status == "failed":
                task["status"] = "failed"
                task["error"] = result.error_msg
        except Exception as e:
            logger.warning(f"[Generate] Poll error for {task_id}: {e}")

    return {**task, "elapsed": task.get("elapsed") or round(time.time() - task.get("created_at", time.time()), 1)}


def _writeback_if_complete(task_id: str) -> None:
    """任务完成后，将结果回写到 StudioStateService（更新对应 draft 并持久化）"""
    task = _tasks.get(task_id)
    if not task or task["status"] not in ("succeeded", "completed"):
        return

    draft_id = task.get("draft_id", "")
    if not draft_id:
        return

    url = ""
    field = "imgUrl"
    if task.get("video_url"):
        url = task["video_url"]
        field = "videoUrl"
    elif task.get("result", {}) and task["result"].get("images"):
        url = task["result"]["images"][0]
        field = "imgUrl"
    if not url:
        return

    svc = StudioStateService.get_instance()
    for category in svc.get_groups().values():
        for group in category:
            for draft in group.get("drafts", []):
                if draft.get("id") == draft_id:
                    draft[field] = url
                    draft["tag"] = "mock 演示" if task.get("mock") else "已生成"
                    svc.save()
                    logger.info(f"[Generate] Writeback: draft {draft_id} → {field}={url[:60]}")
                    return
