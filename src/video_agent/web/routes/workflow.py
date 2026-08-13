"""
/api/workflow — 工作流控制端点（定位见下方「定位声明」）

【定位声明（4.6 收敛）】本端点是早期「一键六阶段流水线」的遗留路径，
已进入冻结态（只维护不新增能力）：
- 主路径是对话式 Agent（Rule 1 Planner 多步循环 + Skill 阶段纪律），
  新能力一律在主路径上迭代；
- CLI 批处理（cli.py）继续使用 workflows.engine 的 DAG 调度，那是引擎的
  唯一积极使用方；
- 交互模式（step/advance）与前端步骤条已随新版 UI 移除，不再投入。

由修复后的 WorkflowEngine 驱动真实执行：
- story / storyboard：真实 LLM 调用（未配置真实供应商 → 诚实标记 skipped）
- image：对缺图草稿走真实生图管线（上限 4 张）
- video / audio / edit：尚未接入真实生成 → 诚实标记 skipped

进度通过 SSE 实时推送；不再有 sleep(2) 的假进度。
"""
import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.state.manager import StateManager
from src.video_agent.workflows.engine import WorkflowEngine
from src.video_agent.workflows.interactive import (
    build_executors,
    build_workflow_definition,
    get_interactive_engine,
)
from src.video_agent.workflows.models import PhaseDefinition, WorkflowDefinition

router = APIRouter()

# 工作流阶段定义（phase_id 为后端契约；前端步骤条已随新版 UI 移除，icon 字段保留仅为 API 兼容）
WORKFLOW_PHASES = [
    {"name": "story", "label": "编剧", "icon": "pen-tool"},
    {"name": "storyboard", "label": "分镜拆解", "icon": "layout-grid"},
    {"name": "image", "label": "关键帧生成", "icon": "image"},
    {"name": "video", "label": "视频生成", "icon": "film"},
    {"name": "audio", "label": "音频合成", "icon": "music"},
    {"name": "edit", "label": "剪辑合成", "icon": "scissors"},
]

# 工作流运行状态（/workflow/status 查询用）
_workflow_state: Dict[str, Any] = {
    "running": False,
    "current_phase": None,
    "phases": [{**p, "status": "pending", "detail": ""} for p in WORKFLOW_PHASES],
}

# SSE 订阅者队列列表
_sse_subscribers: List[asyncio.Queue] = []


class WorkflowRunRequest(BaseModel):
    goal: str
    provider: str = ""        # chat LLM 供应商（story/storyboard 阶段）
    model: str = ""
    image_provider: str = ""  # 生图供应商（image 阶段）
    image_model: str = ""
    workflow_config: str = ""
    phase_configs: Dict[str, Dict[str, str]] = {}  # 阶段级模型配置 {"story": {"provider": "...", "model": "..."}}


@router.get("/workflow/status")
async def get_workflow_status():
    """查询工作流执行状态"""
    return _workflow_state


@router.post("/workflow/run")
async def run_workflow(body: WorkflowRunRequest):
    """启动工作流（异步执行，通过 SSE 推送进度）"""
    if _workflow_state["running"]:
        return {"ok": False, "message": "工作流正在执行中，请等待完成"}

    _workflow_state["running"] = True
    _workflow_state["current_phase"] = None
    for p in _workflow_state["phases"]:
        p["status"] = "pending"
        p["detail"] = ""

    asyncio.create_task(_execute_workflow(body))
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
                    if data.get("event") in ("workflow_done", "workflow_failed"):
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
    for q in list(_sse_subscribers):
        await q.put(event)


def _phase_state(name: str) -> Optional[Dict[str, Any]]:
    for p in _workflow_state["phases"]:
        if p["name"] == name:
            return p
    return None


def _build_definition() -> WorkflowDefinition:
    """六阶段流水线（委托给 workflows.interactive 统一实现）"""
    return build_workflow_definition()


def _build_executors(
    svc: StateManager,
    executor: StudioActionExecutor,
    run_ctx: Dict[str, Any],
    chat_provider: str,
    chat_model: str,
    image_provider: str,
    image_model: str,
    goal_getter: Callable[[], str],
    phase_configs: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Callable]:
    """构建六阶段执行器字典（委托给 workflows.interactive 统一实现）"""
    return build_executors(
        svc, executor, run_ctx,
        chat_provider=chat_provider,
        chat_model=chat_model,
        image_provider=image_provider,
        image_model=image_model,
        goal_getter=goal_getter,
        phase_configs=phase_configs,
    )


async def _execute_workflow(req: WorkflowRunRequest):
    svc = StateManager.get_instance()
    executor = StudioActionExecutor(svc)
    run_ctx: Dict[str, Any] = {"outline": ""}

    executors = _build_executors(
        svc, executor, run_ctx,
        chat_provider=req.provider,
        chat_model=req.model,
        image_provider=req.image_provider,
        image_model=req.image_model,
        goal_getter=lambda: req.goal,
        phase_configs=req.phase_configs,
    )

    async def phase_executor(phase: PhaseDefinition, context: Dict[str, Any]):
        return await executors[phase.phase_id](phase, context)

    # ---------- 引擎事件 → 状态表 + SSE ----------

    async def on_event(event: Dict[str, Any]):
        name = event.get("phase", "")
        ps = _phase_state(name)
        if event["event"] == "phase_started":
            _workflow_state["current_phase"] = name
            if ps:
                ps["status"] = "running"
            await _broadcast({"event": "phase_started", "phase": name, "label": event.get("label", "")})
        elif event["event"] == "phase_completed":
            if ps:
                ps["status"] = "skipped" if event.get("skipped") else "completed"
                ps["detail"] = event.get("detail", "")
            await _broadcast({
                "event": "phase_completed",
                "phase": name,
                "label": event.get("label", ""),
                "detail": event.get("detail", ""),
                "skipped": bool(event.get("skipped")),
            })
        elif event["event"] == "phase_failed":
            if ps:
                ps["status"] = "failed"
                ps["detail"] = event.get("error", "")
            await _broadcast({
                "event": "phase_failed",
                "phase": name,
                "label": event.get("label", ""),
                "error": event.get("error", ""),
            })

    # ---------- 运行 ----------
    try:
        engine = WorkflowEngine(_build_definition(), phase_executor=phase_executor, on_event=on_event)
        success = await engine.run()

        _workflow_state["running"] = False
        _workflow_state["current_phase"] = None

        if success:
            skipped = len(engine.skipped_phases)
            msg = "工作流执行完成"
            if skipped:
                msg += f"（{skipped} 个阶段因未接入/未配置而跳过）"
            await _broadcast({"event": "workflow_done", "message": msg})
            logger.info(f"[Workflow] {msg}")
        else:
            errors = [
                r.get("error", "") for r in engine.phase_results.values()
                if r.get("status") == "failed"
            ]
            await _broadcast({"event": "workflow_failed", "error": "；".join(e for e in errors if e) or "未知错误"})
    except Exception as e:
        logger.error(f"[Workflow] Execution error: {e}")
        _workflow_state["running"] = False
        _workflow_state["current_phase"] = None
        await _broadcast({"event": "workflow_failed", "error": str(e)})


# ---------- 交互模式端点（Phase 4/5: step/advance） ----------
# get_interactive_engine 已从 workflows.interactive 导入（消除 tools→routes 循环依赖）


@router.post("/workflow/step")
async def workflow_step():
    """交互模式：执行当前阶段的下一步，完成后暂停等待确认"""
    engine = get_interactive_engine()
    result = await engine.step()
    return {"ok": True, **result}


@router.post("/workflow/advance")
async def workflow_advance():
    """交互模式：用户确认后推进到下一阶段"""
    engine = get_interactive_engine()
    if not engine.is_awaiting_confirmation:
        return {"ok": False, "message": "当前不在等待确认状态"}
    engine.advance()
    return {
        "ok": True,
        "message": "已确认，推进到下一阶段",
        "current_phase": engine.current_phase,
    }


@router.get("/workflow/interactive-status")
async def workflow_interactive_status():
    """交互模式：查询当前阶段和确认状态"""
    engine = get_interactive_engine()
    return {
        "current_phase": engine.current_phase,
        "awaiting_confirmation": engine.is_awaiting_confirmation,
        "completed_phases": list(engine.completed_phases),
        "skipped_phases": list(engine.skipped_phases),
        "failed_phases": list(engine.failed_phases),
        "phase_results": engine.phase_results,
    }
