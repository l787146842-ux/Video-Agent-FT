"""
/api/workflow — 工作流控制端点

由修复后的 WorkflowEngine 驱动真实执行：
- story / storyboard：真实 LLM 调用（未配置真实供应商 → 诚实标记 skipped）
- image：对缺图草稿走真实生图管线（上限 4 张）
- video / audio / edit：尚未接入真实生成 → 诚实标记 skipped

进度通过 SSE 实时推送；不再有 sleep(2) 的假进度。
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.web.generation import (
    GenerationError,
    call_chat_completion,
    generate_image_via_provider,
)
from src.video_agent.web.provider_config import is_mock_provider
from src.video_agent.web.routes.agent import STUDIO_ACTION_PROTOCOL_PROMPT
from src.video_agent.web.state_service import StudioStateService
from src.video_agent.workflows.engine import WorkflowEngine
from src.video_agent.workflows.models import (
    PhaseDefinition,
    PhaseExecution,
    RetryPolicy,
    WorkflowContextConfig,
    WorkflowDefinition,
)

router = APIRouter()

# 工作流阶段定义（phase_id 与前端 WF_PHASES 的 name 一致）
WORKFLOW_PHASES = [
    {"name": "story", "label": "编剧", "icon": "pen-tool"},
    {"name": "storyboard", "label": "分镜拆解", "icon": "layout-grid"},
    {"name": "image", "label": "关键帧生成", "icon": "image"},
    {"name": "video", "label": "视频生成", "icon": "film"},
    {"name": "audio", "label": "音频合成", "icon": "music"},
    {"name": "edit", "label": "剪辑合成", "icon": "scissors"},
]

# 每次工作流最多真实生成的图片数，防止失控消耗
MAX_IMAGES_PER_RUN = 4

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
    """六阶段流水线：story → storyboard → (image, audio) → video → edit"""
    def phase(pid: str, name: str, deps: List[str]) -> PhaseDefinition:
        return PhaseDefinition(
            phase_id=pid,
            name=name,
            depends_on=deps,
            execution=PhaseExecution(skill=pid),
            timeout_seconds=600,
        )

    return WorkflowDefinition(
        workflow_id="wf_studio_pipeline",
        name="Studio Production Pipeline",
        context=WorkflowContextConfig(
            max_parallel_tasks=2,
            timeout_seconds=1800,
            # LLM/生图失败重试一次即可，避免反复烧钱
            retry_policy=RetryPolicy(max_retries=1, backoff="linear", base_delay_seconds=2),
        ),
        phases=[
            phase("story", "编剧", []),
            phase("storyboard", "分镜拆解", ["story"]),
            phase("image", "关键帧生成", ["storyboard"]),
            phase("audio", "音频合成", ["storyboard"]),
            phase("video", "视频生成", ["image"]),
            phase("edit", "剪辑合成", ["video", "audio"]),
        ],
    )


async def _execute_workflow(req: WorkflowRunRequest):
    svc = StudioStateService.get_instance()
    executor = StudioActionExecutor(svc)
    run_ctx: Dict[str, Any] = {"outline": ""}

    has_llm = not is_mock_provider(req.provider, req.model)
    has_image = not is_mock_provider(req.image_provider, req.image_model)

    # ---------- 各 phase 的真实执行逻辑 ----------

    async def exec_story(_: PhaseDefinition) -> Dict[str, Any]:
        if not has_llm:
            return {"skipped": True, "detail": "未配置真实 LLM 供应商，编剧阶段跳过"}
        content, _finish = await call_chat_completion(
            req.provider, req.model,
            [
                {"role": "system", "content": (
                    "你是专业影视编剧。根据用户目标输出一份简洁的故事大纲："
                    "包含主题、3-6 个场景（每个场景一句话描述 + 时长建议）、整体情绪曲线。"
                    "只输出大纲文本，不要输出 JSON。"
                )},
                {"role": "user", "content": f"创作目标：{req.goal}\n\n当前工作台状态：\n{svc.build_agent_context('bound')}"},
            ],
            max_tokens=2048,
        )
        run_ctx["outline"] = content.strip()
        svc.add_chat_message("agent", f"【工作流·编剧】故事大纲：\n\n{run_ctx['outline']}")
        return {"detail": f"故事大纲已生成（{len(run_ctx['outline'])} 字）"}

    async def exec_storyboard(_: PhaseDefinition) -> Dict[str, Any]:
        if not has_llm:
            return {"skipped": True, "detail": "未配置真实 LLM 供应商，分镜拆解跳过"}
        system = (
            STUDIO_ACTION_PROTOCOL_PROMPT.strip()
            + "\n\n当前工作台状态 JSON：\n" + svc.build_agent_context("bound")
        )
        user = (
            f"请根据以下故事大纲拆解关键元素与分镜，用 add_group 创建分组，"
            f"每个分组携带含可执行 prompt 的 draft。目标：{req.goal}\n\n大纲：\n"
            + (run_ctx["outline"] or "（无大纲，请直接根据目标拆解）")
        )
        content, _finish = await call_chat_completion(
            req.provider, req.model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=8192,
        )
        actions = executor.parse_actions_from_reply(content)
        actions = [a for a in actions if str(a.get("action", "")).lower() != "continue"]
        applied = executor.execute(actions)
        if applied == 0:
            raise GenerationError("LLM 未产出有效的 studio-actions（可能被截断或格式错误）")
        return {"detail": f"已新增 {applied} 个故事板分组/草稿"}

    async def exec_image(_: PhaseDefinition) -> Dict[str, Any]:
        if not has_image:
            return {"skipped": True, "detail": "未配置真实生图供应商，关键帧生成跳过"}
        # 找出有 prompt 但还没有图的草稿
        targets = []
        groups = svc.get_groups()
        for cat in ("keyElements", "shots"):
            for group in groups.get(cat, []):
                for draft in group.get("drafts", []):
                    if draft.get("prompt") and not draft.get("imgUrl") and draft.get("mediaType") == "image":
                        targets.append(draft)
        targets = targets[:MAX_IMAGES_PER_RUN]
        if not targets:
            return {"detail": "没有待生成的关键帧（所有草稿已有图片）"}

        ok, failed_msgs = 0, []
        for draft in targets:
            try:
                url = await generate_image_via_provider(
                    req.image_provider, req.image_model, draft["prompt"],
                    size=draft.get("size", "1280x720"),
                    aspect_ratio=draft.get("aspectRatio", "16:9"),
                )
                draft["imgUrl"] = url
                draft["tag"] = "已生成"
                svc.save()
                ok += 1
            except GenerationError as e:
                failed_msgs.append(str(e))
        if ok == 0:
            raise GenerationError("全部关键帧生成失败：" + "；".join(failed_msgs[:2]))
        detail = f"已真实生成 {ok}/{len(targets)} 张关键帧"
        if failed_msgs:
            detail += f"（{len(failed_msgs)} 张失败）"
        return {"detail": detail}

    async def exec_not_implemented(phase: PhaseDefinition) -> Dict[str, Any]:
        reasons = {
            "video": "真实视频供应商尚未接入服务端",
            "audio": "音频合成尚未接入服务端",
            "edit": "剪辑合成尚未接入服务端",
        }
        return {"skipped": True, "detail": reasons.get(phase.phase_id, "尚未实现") + "，跳过"}

    executors = {
        "story": exec_story,
        "storyboard": exec_storyboard,
        "image": exec_image,
        "video": exec_not_implemented,
        "audio": exec_not_implemented,
        "edit": exec_not_implemented,
    }

    async def phase_executor(phase: PhaseDefinition):
        return await executors[phase.phase_id](phase)

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
