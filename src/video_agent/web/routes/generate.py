"""
/api/generate — 生成任务端点（批次5 拆分后的聚合出口）

- 图片端点：generate_image.py（/generate/image、/canvas-image-tasks、/generate/batch-image）
- 视频端点：generate_video.py（/generate/video、/canvas-video）
- 本文件：任务查询 / 生成日志 / SSE 事件流 + 子路由聚合
- 共享设施：generate_common.py（任务管理、SSE 通知、请求模型、轮询）

原则：
- 只有用户显式选择 mock 供应商（或 provider 为空）才走 mock，且结果会标注 mock=True；
- 真实供应商失败 → 返回真实错误（HTTP 4xx/5xx + detail），绝不回退假图；
- 视频生成尚未接入真实供应商 → 非 mock 一律 501，明确告知。
"""
import asyncio
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .generate_common import (
    GenLogRequest,
    _log_task_exception,  # noqa: F401  向后兼容别名（供旧模块导入）
    _tasks,  # noqa: F401  向后兼容别名（供 actions.py 等模块导入）
    _tm,
    poll_task,
)
from .generate_image import router as _image_router
from .generate_video import router as _video_router

router = APIRouter()
router.include_router(_image_router)
router.include_router(_video_router)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """通用任务状态查询"""
    return await poll_task(task_id)


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
