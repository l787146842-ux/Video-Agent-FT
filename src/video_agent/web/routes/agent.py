"""
/api/agent — Agent 聊天端点（路由层，业务逻辑委托给 chat_service.py）

流程：服务端构建上下文 → 多步 LLM 循环（默认≤6 轮，AGENT_MAX_STEPS 可调）→ 解析并执行 studio-actions → 持久化 → 返回。

- 上下文注入在服务端完成（前端只发消息本体 + 选中态），服务端是唯一事实源；
- 仅当 provider 为空/mock 时走 mock；真实供应商失败返回 502 + 真实错误。
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.chat_service import stream_worker, non_stream_worker, sse_event_generator
from src.video_agent.exceptions import AdapterError, GenerationError
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.core.token_budget import context_window_for_model, estimate_tokens
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS

router = APIRouter()

# 后台聊天 worker 单槽注册表：客户端断连（刷新/关标签）后 worker 转后台跑完，
# 前端重载后轮询 /agent/running 同步结果；/agent/stop 显式取消（停止按钮专用）。
_CHAT_TASKS: Dict[str, asyncio.Task] = {}

# 空项目状态骨架的基线 token：新建项目即使没有任何内容，状态 JSON 也有固定骨架
# （空列表/interaction 节），这部分不计入「已用」，避免新项目一创建就显示 0.3K
_EMPTY_STATE_BASELINE_TOKENS: Optional[int] = None


def _empty_state_baseline() -> int:
    global _EMPTY_STATE_BASELINE_TOKENS
    if _EMPTY_STATE_BASELINE_TOKENS is None:
        empty = {
            CAT_KEY_ELEMENTS: [], CAT_SHOTS: [], CAT_AUDIO_ITEMS: [],
            "assets": [], "documents": [], "uploadedDocs": [],
            "interaction": {"awaiting_confirmation": False, "confirmation_message": ""},
        }
        _EMPTY_STATE_BASELINE_TOKENS = estimate_tokens(
            json.dumps(empty, ensure_ascii=False, separators=(",", ":"))
        )
    return _EMPTY_STATE_BASELINE_TOKENS


class ChatRequest(BaseModel):
    message: str
    # DEPRECATED：后端已不再使用（Skill 全文改由服务端按 skill_name 硬注入），
    # 仅为 legacy 前端兼容保留，新前端不再发送
    system_prompt: str = ""
    # 请求幂等键（P2）：前端每次发送生成唯一 id，同 id 处理中时拒绝重复提交
    request_id: str = ""
    provider: str = ""
    model: str = ""
    ms_model: str = ""
    messages: List[Dict[str, str]] = []
    images: List[str] = []
    videos: List[str] = []
    attachments: List[Dict[str, str]] = []
    # 有序富文本片段（文字/图片/视频/音频交错）：前端富文本输入框按用户排版顺序
    # 序列化而来，后端据此构建交错多模态内容，让 LLM 精确识别文字↔媒体对应关系。
    # 每项形如 {"type":"text","text":...} / {"type":"image|video|audio","url":...,"name":...}
    content_parts: List[Dict[str, str]] = []
    selected_draft_id: str = ""
    selected_type: str = ""
    context_mode: str = "studio"
    asset_mode: str = "bound"
    # 本次消息携带的 Skill slug（前端仅当消息中含 Skill 引用块时才传）：
    # 后端据此把该 Skill 记入当前项目的 usedSkills，文档面板只展示已发送过的 Skill 文档。
    skill_slug: str = ""
    # 前端当前选中的 Skill 名称（渐进式披露：system prompt 只注入 Skill 目录，
    # 选中项仅作相关性标注，不注入全文）
    skill_name: str = ""
    # 用户消息携带的引用块（展示用，随消息持久化，刷新后可重建）：
    # doc_blocks = 随消息发送的文档附件名称；skill_blocks = 随消息发送的 Skill 名称
    doc_blocks: List[str] = []
    skill_blocks: List[str] = []


class ChatResponse(BaseModel):
    text: str
    applied_actions: int = 0
    steps: int = 1
    warnings: List[str] = []
    confirmation: str = ""
    documents_written: List[str] = []
    # P0 修复：补齐 non_stream_worker 实际返回的字段，
    # 此前被 response_model 静默过滤导致非流式端点丢失生图结果
    image_urls: List[str] = []
    chat_inserts: List[Dict[str, Any]] = []
    action_log: List[str] = []
    state: Optional[Dict[str, Any]] = None


@router.post("/agent/chat", response_model=ChatResponse)
async def agent_chat(body: ChatRequest):
    """非流式聊天端点（业务逻辑委托给 chat_service.non_stream_worker）"""
    if not body.message.strip() and not body.attachments:
        raise HTTPException(status_code=400, detail="消息不能为空")
    try:
        result = await non_stream_worker(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (GenerationError, AdapterError) as e:
        logger.warning(f"[Agent] LLM 调用失败: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    return ChatResponse(**result)


@router.post("/agent/chat/stream")
async def agent_chat_stream(body: ChatRequest, request: Request):
    """流式聊天端点（SSE）。业务逻辑委托给 chat_service.stream_worker。"""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: Dict[str, Any]) -> None:
        await queue.put(event)

    task = asyncio.create_task(stream_worker(body, emit))
    _CHAT_TASKS["bound"] = task
    task.add_done_callback(lambda _t: _CHAT_TASKS.pop("bound", None))

    return StreamingResponse(
        sse_event_generator(queue, task, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/agent/traces")
async def get_agent_traces(limit: int = 50):
    """获取最近 N 条 Agent 执行链路追踪（调试用）"""
    tracer = AgentTracer.get_instance()
    return {"traces": tracer.get_recent_traces(min(limit, 50))}


@router.get("/agent/running")
async def agent_running():
    """是否有聊天 worker 仍在运行（含客户端断连后转后台的）。

    前端刷新/切换回来后轮询此端点：running=true 时显示忙态，
    转 false 后重拉项目快照同步 Agent 成果。
    """
    return {"running": any(not t.done() for t in _CHAT_TASKS.values())}


@router.post("/agent/stop")
async def agent_stop():
    """显式停止当前聊天 worker（停止按钮调用；刷新不触发此端点，worker 续跑）"""
    cancelled = 0
    for key in list(_CHAT_TASKS.keys()):
        t = _CHAT_TASKS.pop(key, None)
        if t is not None and not t.done():
            t.cancel()
            cancelled += 1
    logger.info(f"[Agent] stop 请求，取消 worker 数={cancelled}")
    return {"ok": True, "cancelled": cancelled}


@router.post("/agent/tasks")
async def create_agent_task(body: ChatRequest):
    """任务式传输：提交 Agent 聊天任务，立即返回 task_id（worker 后台运行）。"""
    from src.video_agent.web.chat_service import start_agent_task

    return start_agent_task(body)


@router.get("/agent/tasks")
async def list_agent_tasks(project_id: str = ""):
    """查询某项目仍在运行的后台 Agent 任务（刷新/切回后重连用）。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    return {"tasks": get_agent_task_manager().list_running(project_id)}


@router.get("/agent/tasks/{task_id}/events")
async def agent_task_events(task_id: str, request: Request):
    """订阅后台任务事件流：先回放累计状态（replay），再增量推送；断线只断订阅。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    tm = get_agent_task_manager()
    q = tm.subscribe(task_id)
    if q is None:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") in ("done", "error", "task_status"):
                    break
        finally:
            tm.unsubscribe(task_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/agent/tasks/{task_id}/stop")
async def stop_agent_task(task_id: str):
    """真正停止后台任务（停止按钮调用）；刷新/切项目不调用。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    ok = get_agent_task_manager().stop(task_id)
    return {"ok": ok, "cancelled": 1 if ok else 0}


@router.get("/agent/context-usage")
async def get_context_usage(model: str = ""):
    """估算当前会话将发送给 LLM 的上下文用量（Studio 状态上下文 + 聊天记录）。

    前端在发送按钮旁展示「已用多少K上下文」小圆圈：
    - chars: 上下文字符总数
    - est_tokens: 估算 token 数（与 token_budget 截断同口径：中文约1.5字/token）
    - window_tokens: 当前模型上下文窗口（供前端算圆环填充比）
    """
    svc = StateManager.get_instance()
    try:
        state_json = svc.build_agent_context("bound")
    except Exception as e:  # 上下文构建失败不应阻断用量展示
        logger.warning(f"[Agent] 上下文用量统计失败: {e}")
        state_json = ""
    history_json = json.dumps(svc.get_chat_messages(), ensure_ascii=False)
    # 状态段扣除空项目基线：新项目（无分组/无历史）显示 0，
    # 用量只随真实内容（分组/草稿/文档/聊天记录）增长
    state_tokens = max(0, estimate_tokens(state_json) - _empty_state_baseline())
    history_tokens = estimate_tokens(history_json)
    chars = len(state_json) + len(history_json)
    return {
        "chars": chars,
        "est_tokens": state_tokens + history_tokens,
        "state_chars": len(state_json),
        "history_chars": len(history_json),
        "window_tokens": context_window_for_model(model) if model else 0,
    }
