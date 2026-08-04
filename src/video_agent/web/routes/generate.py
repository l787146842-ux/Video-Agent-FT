"""
/api/generate — 生成任务端点

原则：
- 只有用户显式选择 mock 供应商（或 provider 为空）才走 mock，且结果会标注 mock=True；
- 真实供应商失败 → 返回真实错误（HTTP 4xx/5xx + detail），绝不回退假图；
- 视频生成尚未接入真实供应商 → 非 mock 一律 501，明确告知。
"""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete
from src.video_agent.exceptions import GenerationError
from src.video_agent.web.generation import generate_image_via_provider, image_size_for
from src.video_agent.web.provider_config import is_mock_provider
from src.video_agent.web.providers import resolve_adapter_name
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ALL_CATEGORIES_TUPLE
from src.video_agent.utils import gen_id
from src.video_agent.config import settings

router = APIRouter()

# 任务管理：委托给 GenerationTaskManager 单例
from src.video_agent.web.task_manager import (
    get_task_manager,
    writeback_if_complete as _writeback_if_complete,
)
_tm = get_task_manager()

# 向后兼容别名（供 actions.py 等模块导入）
_tasks = _tm.tasks


def _notify_sse(event_data: Dict[str, Any]) -> None:
    """向所有 SSE 订阅者推送任务完成事件"""
    _tm.notify(event_data)


def _track_task(coro) -> None:
    """创建并追踪后台任务"""
    _tm.track(coro)


def _log_task_exception(task: asyncio.Task) -> None:
    """兼容别名"""
    pass

# 任务保留时长（秒）：超过后在下一次写入时清理，防止内存无限增长
_TASK_TTL_SECONDS = settings.task_ttl_seconds
_TASK_MAX = settings.task_max

# mock 视频用可播放的示例视频，而不是死链
MOCK_VIDEO_URL = "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"


def _new_task(task_id: str, **fields: Any) -> Dict[str, Any]:
    return _tm.create_task(task_id, **fields)


class ImageGenRequest(BaseModel):
    prompt: str
    provider_id: str = ""
    model: str = ""
    size: str = "1280x720"
    aspect_ratio: str = "16:9"
    # 分辨率档位（1K/2K/4K）：CLI 类供应商无 size 参数，靠提示词感知
    resolution: str = ""
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
    task_id = gen_id("img")
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
        # 提取参考素材 URL（@ 引用的素材），随请求发送给多模态模型
        ref_urls = [r.get("url", "") for r in (body.reference_images or []) if r.get("url")]
        try:
            image_url = await generate_image_via_provider(
                body.provider_id,
                body.model,
                body.prompt,
                size=body.size or "1024x1024",
                aspect_ratio=body.aspect_ratio,
                resolution=body.resolution,
                reference_images=ref_urls,
            )
            if task is None:
                return
            task["status"] = "succeeded"
            task["result"] = {"images": [image_url]}
            task["elapsed"] = round(time.monotonic() - t0, 1)
            _writeback_if_complete(task_id)
            _notify_sse({"task_id": task_id, "status": "succeeded", "kind": "image",
                         "draft_id": body.draft_id, "result": task["result"], "elapsed": task["elapsed"]})
            _tm.record_gen_log(
                media_type="image", status="succeeded", provider=body.provider_id, model=body.model,
                prompt=body.prompt, draft_id=body.draft_id, result_url=image_url,
                elapsed=task["elapsed"], requested_size=f"{body.size} ({body.aspect_ratio})", source="manual",
                task_id=task_id,
            )
            logger.info(f"[Generate] 图片生成成功({task['elapsed']}s): {image_url[:80]}")
        except GenerationError as e:
            if task is not None:
                task["status"] = "failed"
                task["error"] = str(e)
                task["elapsed"] = round(time.monotonic() - t0, 1)
                _notify_sse({"task_id": task_id, "status": "failed", "kind": "image",
                             "draft_id": body.draft_id, "error": str(e), "elapsed": task["elapsed"]})
                _tm.record_gen_log(
                    media_type="image", status="failed", provider=body.provider_id, model=body.model,
                    prompt=body.prompt, draft_id=body.draft_id, error=str(e),
                    elapsed=task["elapsed"], requested_size=f"{body.size} ({body.aspect_ratio})", source="manual",
                    task_id=task_id,
                )
            logger.warning(f"[Generate] 图片生成失败: {e}")
        except Exception as e:
            if task is not None:
                task["status"] = "failed"
                task["error"] = f"服务端异常: {e}"
                task["elapsed"] = round(time.monotonic() - t0, 1)
                _notify_sse({"task_id": task_id, "status": "failed", "kind": "image",
                             "draft_id": body.draft_id, "error": str(e), "elapsed": task["elapsed"]})
                _tm.record_gen_log(
                    media_type="image", status="failed", provider=body.provider_id, model=body.model,
                    prompt=body.prompt, draft_id=body.draft_id, error=str(e),
                    elapsed=task["elapsed"], requested_size=f"{body.size} ({body.aspect_ratio})", source="manual",
                    task_id=task_id,
                )
            logger.exception(f"[Generate] 图片生成异常: {e}")

    # 生成日志：提交即记录 started；SSE 同步通知前端点亮转圈
    _tm.record_gen_log(
        media_type="image", status="started", provider=body.provider_id, model=body.model,
        prompt=body.prompt, draft_id=body.draft_id,
        requested_size=f"{body.size} ({body.aspect_ratio})", source="manual",
        task_id=task_id,
    )
    _notify_sse({"task_id": task_id, "status": "started", "kind": "image", "draft_id": body.draft_id})
    _track_task(_run_generation())
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


class BatchImageGenRequest(BaseModel):
    target: str = "all_shots"  # "all_keyElements" / "all_shots" / 逗号分隔的 draft_id
    provider_id: str = ""
    model: str = ""
    size: str = "1280x720"
    aspect_ratio: str = "16:9"


@router.post("/generate/batch-image")
async def batch_generate_image(body: BatchImageGenRequest):
    """批量提交图片生成（前端“批量生成”按钮 + Agent action 共用）"""
    svc = StateManager.get_instance()
    state = svc.state_dict

    # 确定目标 drafts
    targets: List[tuple] = []  # (group, draft)
    if body.target in ("all_keyElements", "all_keyelements"):
        for g in state.get(CAT_KEY_ELEMENTS, []):
            for d in g.get("drafts", []):
                if (d.get("prompt") or "").strip():
                    targets.append((g, d))
    elif body.target in ("all_shots", "all_shot"):
        for g in state.get(CAT_SHOTS, []):
            for d in g.get("drafts", []):
                if (d.get("prompt") or "").strip():
                    targets.append((g, d))
    else:
        # 逗号分隔的 draft_id
        ids = [x.strip() for x in body.target.split(",") if x.strip()]
        for cat in ALL_CATEGORIES_TUPLE:
            for g in state.get(cat, []):
                for d in g.get("drafts", []):
                    if d.get("id") in ids and (d.get("prompt") or "").strip():
                        targets.append((g, d))

    if not targets:
        return {"task_ids": [], "count": 0, "detail": "未找到有提示词的草稿"}

    if is_mock_provider(body.provider_id, body.model):
        return {"task_ids": [], "count": 0, "detail": "mock 供应商不支持批量生成，请逐个操作"}

    task_ids: List[str] = []
    for group, draft in targets:
        # 自动注入 sceneRefs 参考图
        refs: List[Dict[str, str]] = []
        for ref_title in (group.get("sceneRefs") or []):
            for ke in state.get(CAT_KEY_ELEMENTS, []):
                if ke.get("title") == ref_title:
                    for kd in ke.get("drafts", []):
                        if kd.get("imgUrl"):
                            refs.append({"url": kd["imgUrl"], "role": "reference"})
                            break
                    break

        task_id = gen_id("img")
        _new_task(
            task_id,
            status="processing",
            draft_id=draft.get("id", ""),
            draft_type="shot" if group in state.get(CAT_SHOTS, []) else "keyElement",
            prompt=draft.get("prompt", ""),
            model=body.model,
            result=None,
        )
        task_ids.append(task_id)
        draft["tag"] = "生成中"

        # 异步执行
        prompt_text = draft["prompt"]
        provider_id = body.provider_id
        model_name = body.model
        # 按草稿自身 比例 + 分辨率档位 计算尺寸（缺失时回退请求参数）
        aspect_ratio = (draft.get("aspectRatio") or "").strip() or body.aspect_ratio
        resolution = (draft.get("imageResolution") or "").strip().upper()
        if resolution not in ("1K", "2K", "4K"):
            resolution = "1K"
        size = image_size_for(aspect_ratio, resolution)
        size_note = f"{size} ({aspect_ratio}, {resolution})"

        async def _run(tid=task_id, p=prompt_text, pid=provider_id, m=model_name, s=size, ar=aspect_ratio, res=resolution, sn=size_note, did=draft.get("id", "")):
            t0 = time.monotonic()
            task = _tasks.get(tid)
            try:
                url = await generate_image_via_provider(pid, m, p, size=s, aspect_ratio=ar, resolution=res)
                if task:
                    task["status"] = "succeeded"
                    task["result"] = {"images": [url]}
                    task["elapsed"] = round(time.monotonic() - t0, 1)
                    _writeback_if_complete(tid)
                    _notify_sse({"task_id": tid, "status": "succeeded", "kind": "image",
                                 "draft_id": did, "result": {"images": [url]}, "elapsed": task["elapsed"]})
                    _tm.record_gen_log(
                        media_type="image", status="succeeded", provider=pid, model=m, prompt=p,
                        draft_id=did, result_url=url, elapsed=task["elapsed"],
                        requested_size=sn, source="batch",
                        task_id=tid,
                    )
            except Exception as e:  # 统一兜底（GenerationError 是 Exception 子类），保证任务状态闭环
                if task:
                    task["status"] = "failed"
                    task["error"] = str(e)
                    task["elapsed"] = round(time.monotonic() - t0, 1)
                    _notify_sse({"task_id": tid, "status": "failed", "kind": "image",
                                 "draft_id": did, "error": str(e), "elapsed": task["elapsed"]})
                    _tm.record_gen_log(
                        media_type="image", status="failed", provider=pid, model=m, prompt=p,
                        draft_id=did, error=str(e), elapsed=task["elapsed"],
                        requested_size=sn, source="batch",
                        task_id=tid,
                    )

        # 批量提交即记录 started 并通知前端点亮转圈
        _tm.record_gen_log(
            media_type="image", status="started", provider=provider_id, model=model_name,
            prompt=prompt_text, draft_id=draft.get("id", ""),
            requested_size=size_note, source="batch",
            task_id=task_id,
        )
        _notify_sse({"task_id": task_id, "status": "started", "kind": "image", "draft_id": draft.get("id", "")})
        _track_task(_run())

    svc.save()
    return {"task_ids": task_ids, "count": len(task_ids)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """通用任务状态查询"""
    return await _poll_task(task_id)


@router.get("/generate/active")
async def get_active_tasks():
    """查询仍在处理中的生成任务（前端刷新页面后恢复卡片/预览框读秒用）。

    activeGenerations 仅存于前端内存，刷新即丢；本端点返回后端权威的
    processing 任务列表，前端据此重新点亮转圈（并按 created_at 恢复已耗时）。
    """
    active = []
    for tid, t in _tm.tasks.items():
        if t.get("status") in ("processing", "pending"):
            active.append({
                "task_id": tid,
                "draft_id": t.get("draft_id", ""),
                "kind": "video" if tid.startswith("vid") else "image",
                "created_at": t.get("created_at", time.time()),
            })
    return {"tasks": active}


# ---------- 生成日志（顶部导航「生成日志」面板数据源） ----------

class GenLogRequest(BaseModel):
    media_type: str  # image | video | audio
    status: str      # started | succeeded | failed
    provider: str = ""
    model: str = ""
    prompt: str = ""
    draft_id: str = ""
    error: str = ""
    result_url: str = ""
    elapsed: float = 0.0
    requested_size: str = ""
    source: str = "manual"


@router.get("/generation-logs")
async def get_generation_logs(limit: int = 100):
    """生成日志查询：图/视频/音频每次生成的成败记录（时间倒序）"""
    return {"logs": _tm.get_gen_logs(limit)}


@router.post("/generation-logs")
async def add_generation_log(body: GenLogRequest):
    """前端补录生成日志（如音频规划等未走后绔任务通道的生成行为）"""
    if body.media_type not in ("image", "video", "audio"):
        raise HTTPException(status_code=400, detail="media_type 必须为 image/video/audio")
    entry = _tm.record_gen_log(
        media_type=body.media_type, status=body.status, provider=body.provider,
        model=body.model, prompt=body.prompt, draft_id=body.draft_id,
        error=body.error, result_url=body.result_url, elapsed=body.elapsed,
        requested_size=body.requested_size, source=body.source,
    )
    return {"ok": True, "log": entry}


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
                # result 可能是 VideoGenerationResponse 或 ImageGenerationResponse，
                # 两者字段不重叠，getattr 是跨类型的合理探测（非冗余防御）
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


# _writeback_if_complete 已下沉至 web/task_manager.py（此处为别名导入）


@router.get("/generate/events")
async def generate_events():
    """生成任务 SSE 事件流：任务完成/失败时即时推送，替代前端 2s 轮询"""
    queue = _tm.subscribe()

    async def event_stream():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    # 心跳保活
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _tm.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
