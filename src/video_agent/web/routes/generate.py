"""
/api/generate — 生成任务端点

- 图片端点：generate_image.py（/generate/image、/canvas-image-tasks、/generate/batch-image）
- 视频端点：generate_video.py（/generate/video、/canvas-video）
- 本文件：任务查询 / 生成日志 / SSE 事件流 + 子路由聚合
- 共享设施：generate_common.py（任务管理、SSE 通知、请求模型、轮询）

原则：
- 未配置供应商 → 明确报错（演示兜底已删除）；
- 真实供应商失败 → 返回真实错误（HTTP 4xx/5xx + detail），绝不回退假图。
"""
from loguru import logger
import asyncio
import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List

from src.video_agent.exceptions import VideoAgentError
from src.video_agent.web.error_payload import LEGACY_VALIDATION_ERROR

from .generate_common import (
    GenLogRequest,
    _tm,
    poll_task,
)
from .generate_image import router as _image_router
from .generate_video import router as _video_router

router = APIRouter()
router.include_router(_image_router)
router.include_router(_video_router)


# ---------- 生成日志响应模型 ----------

class GenerationLogEntry(BaseModel):
    """生成日志条目（读形态；字段全带默认值容忍存量落盘缺键）"""
    id: str = ""
    task_id: str = ""
    # image/video/audio/error（error = 系统错误事件记录）
    media_type: str = ""
    # started/succeeded/failed
    status: str = ""
    provider: str = ""
    provider_name: str = ""
    model: str = ""
    prompt: str = ""
    draft_id: str = ""
    error: str = ""
    result_url: str = ""
    elapsed: float = 0.0
    requested_size: str = ""
    source: str = ""
    ts: str = ""


class GenerationLogsResponse(BaseModel):
    logs: List[GenerationLogEntry] = []


class AddGenerationLogResponse(BaseModel):
    ok: bool = True
    log: GenerationLogEntry = GenerationLogEntry()


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

@router.get("/generation-logs", response_model=GenerationLogsResponse)
async def get_generation_logs(limit: int = 100):
    """生成日志查询：图/视频/音频每次生成的成败记录（时间倒序）"""
    return {"logs": _tm.get_gen_logs(limit)}


@router.post("/generation-logs", response_model=AddGenerationLogResponse)
async def add_generation_log(body: GenLogRequest):
    """前端补录生成日志（如音频规划等未走后台任务通道的生成行为）"""
    if body.media_type not in ("image", "video", "audio"):
        raise VideoAgentError(
            "media_type 必须为 image/video/audio",
            status_code=400,
            error_code=LEGACY_VALIDATION_ERROR,
        )
    entry = _tm.record_gen_log(
        media_type=body.media_type, status=body.status, provider=body.provider,
        model=body.model, prompt=body.prompt, draft_id=body.draft_id,
        error=body.error, result_url=body.result_url, elapsed=body.elapsed,
        requested_size=body.requested_size, source=body.source,
    )
    return {"ok": True, "log": entry}


# 生成任务终态集合（SSE 回放快照与前端降级判定共用口径）
_TERMINAL_STATUSES = ("succeeded", "completed", "failed")


def _terminal_snapshot(task_id: str, task: dict) -> str:
    """终态任务 → SSE 回放帧（与 _notify_sse 终态事件同形，前端同一路径消费）"""
    payload = {
        "task_id": task_id,
        "status": task.get("status"),
        "kind": "video" if task.get("adapter_type") == "video_generation" else "image",
        "draft_id": task.get("draft_id", ""),
        "elapsed": task.get("elapsed") or round(time.time() - task.get("created_at", time.time()), 1),
    }
    if task.get("video_url"):
        payload["video_url"] = task["video_url"]
    if task.get("result"):
        payload["result"] = task["result"]
    if task.get("error"):
        payload["error"] = task["error"]
    return json.dumps(payload, ensure_ascii=False)


@router.get("/generate/events/{task_id}")
async def generate_events_for_task(task_id: str):
    """按任务定向的生成 SSE 事件流（任务7/P0：前端 generate-polling 唯一订阅口）。

    正向设计消除「连接前事件已发出」竞速：先订阅再探终态——
    任务已终态立即回放快照并关流；否则只转发本任务帧，
    晚到的订阅者由轮询降级兜底（前端 sseFirstThenPoll）。
    """
    queue = _tm.subscribe()

    async def event_stream():
        try:
            # 订阅后探终态：订阅 → 探测期间到达的 notify 已入队，不漏帧
            task = _tm.get_task(task_id)
            if task is None:
                # 任务不存在（已 TTL 清理/从未创建）：下发失败帧立即关流，
                # 前端降级轮询会拿到 not_found，不得挂死等
                yield f"data: {json.dumps({'task_id': task_id, 'status': 'failed', 'error': '任务不存在或已清理'}, ensure_ascii=False)}\n\n"
                return
            if task.get("status") in _TERMINAL_STATUSES:
                yield f"data: {_terminal_snapshot(task_id, task)}\n\n"
                return
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    # 心跳保活
                    yield ": heartbeat\n\n"
                    continue
                try:
                    data = json.loads(msg)
                except (TypeError, ValueError):
                    continue
                if data.get("task_id") != task_id:
                    continue
                yield f"data: {msg}\n\n"
                if data.get("status") in _TERMINAL_STATUSES:
                    return  # 终态即关流（按任务订阅不长期占用广播队列）
        except asyncio.CancelledError as _e:
            logger.debug("[generate] 忽略异常: {}", _e)
        finally:
            _tm.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/generate/events")
async def generate_events():
    """生成任务 SSE 全局广播流（待迁移，P3）。

    唯一消费方：前端全局生成事件总线（lib/generation-events.ts，卡片转圈/
    生成日志角标）。按任务定向链路（generate-polling）已全量切到
    /generate/events/{task_id}；待总线改造为按任务订阅后本端点退役。
    """
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
        except asyncio.CancelledError as _e:
            logger.debug("[generate] 忽略异常: {}", _e)
        finally:
            _tm.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
