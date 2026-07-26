"""
/api/workflow — 工作流控制端点
查询工作流状态、启动工作流执行、SSE 实时推送进度。
"""
import asyncio
import json
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.state_service import StudioStateService
from src.video_agent.web.actions import StudioActionExecutor

router = APIRouter()

# 工作流阶段定义
WORKFLOW_PHASES = [
    {"name": "story", "label": "编剧", "icon": "pen-tool"},
    {"name": "storyboard", "label": "分镜拆解", "icon": "layout-grid"},
    {"name": "image", "label": "关键帧生成", "icon": "image"},
    {"name": "video", "label": "视频生成", "icon": "film"},
    {"name": "audio", "label": "音频合成", "icon": "music"},
    {"name": "edit", "label": "剪辑合成", "icon": "scissors"},
]

# 工作流运行状态
_workflow_state: Dict[str, Any] = {
    "running": False,
    "current_phase": None,
    "phases": [{**p, "status": "pending", "detail": ""} for p in WORKFLOW_PHASES],
}

# SSE 订阅者队列列表
_sse_subscribers: List[asyncio.Queue] = []


class WorkflowRunRequest(BaseModel):
    goal: str
    workflow_config: str = "config/default_workflow.json"


@router.get("/workflow/status")
async def get_workflow_status():
    """查询工作流执行状态"""
    return _workflow_state


@router.post("/workflow/run")
async def run_workflow(body: WorkflowRunRequest):
    """启动工作流（异步执行，通过 SSE 推送进度）"""
    if _workflow_state["running"]:
        return {"ok": False, "message": "工作流正在执行中，请等待完成"}

    # 重置状态
    _workflow_state["running"] = True
    _workflow_state["current_phase"] = None
    for p in _workflow_state["phases"]:
        p["status"] = "pending"
        p["detail"] = ""

    # 异步启动工作流执行
    asyncio.create_task(_execute_workflow(body.goal))

    return {"ok": True, "message": f"工作流已启动，目标：{body.goal}"}


@router.get("/workflow/events")
async def workflow_events():
    """SSE 端点 — 实时推送工作流进度"""
    queue: asyncio.Queue = asyncio.Queue()
    _sse_subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    if data.get("event") == "workflow_done":
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
        finally:
            if queue in _sse_subscribers:
                _sse_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------- 内部执行逻辑 ----------

async def _broadcast(event: Dict[str, Any]):
    """向所有 SSE 订阅者广播事件"""
    for q in list(_sse_subscribers):
        await q.put(event)


async def _execute_workflow(goal: str):
    """
    模拟工作流执行（后续接入真实 WorkflowEngine + Skills）。
    每个阶段完成后通过 SSE 推送 + StudioActionExecutor 更新故事板。
    """
    svc = StudioStateService.get_instance()
    executor = StudioActionExecutor(svc)

    try:
        for phase in _workflow_state["phases"]:
            phase_name = phase["name"]
            _workflow_state["current_phase"] = phase_name
            phase["status"] = "running"
            await _broadcast({"event": "phase_started", "phase": phase_name, "label": phase["label"]})

            # 模拟执行耗时
            await asyncio.sleep(2)

            # 阶段完成后的副作用
            if phase_name == "story":
                phase["detail"] = f"已根据目标生成故事大纲：{goal[:30]}..."
            elif phase_name == "storyboard":
                phase["detail"] = "已拆解为 2 个关键元素 + 2 个分镜"
            elif phase_name == "image":
                phase["detail"] = "已生成 3 张关键帧概念图"
                # 自动给第一个关键元素添加一个 draft
                actions = [{
                    "action": "add_draft",
                    "group_type": "keyElement",
                    "group_id": "current",
                    "draft": {
                        "label": "工作流生成",
                        "tag": "工作流",
                        "mediaType": "image",
                        "imgUrl": "https://picsum.photos/seed/wf-img/1280/720",
                        "prompt": "工作流自动生成的关键帧概念图",
                    },
                }]
                executor.execute(actions)
            elif phase_name == "video":
                phase["detail"] = "已提交 2 段视频生成任务"
            elif phase_name == "audio":
                phase["detail"] = "已生成音频规划"
            elif phase_name == "edit":
                phase["detail"] = "剪辑时间线已组装"

            phase["status"] = "completed"
            await _broadcast({
                "event": "phase_completed",
                "phase": phase_name,
                "label": phase["label"],
                "detail": phase["detail"],
            })

        _workflow_state["running"] = False
        _workflow_state["current_phase"] = None
        await _broadcast({"event": "workflow_done", "message": "工作流全部完成！"})
        logger.info("[Workflow] All phases completed")

    except Exception as e:
        logger.error(f"[Workflow] Execution error: {e}")
        if _workflow_state["current_phase"]:
            for p in _workflow_state["phases"]:
                if p["name"] == _workflow_state["current_phase"]:
                    p["status"] = "failed"
                    p["detail"] = str(e)
        _workflow_state["running"] = False
        await _broadcast({"event": "workflow_failed", "error": str(e)})
