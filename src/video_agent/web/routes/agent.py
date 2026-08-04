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
from src.video_agent.core.token_budget import estimate_tokens
from src.video_agent.state.manager import StateManager

router = APIRouter()


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


@router.get("/agent/context-usage")
async def get_context_usage():
    """估算当前会话将发送给 LLM 的上下文用量（Studio 状态上下文 + 聊天记录）。

    前端在发送按钮旁展示「已用多少K上下文」：
    - chars: 上下文字符总数
    - est_tokens: 估算 token 数（与 token_budget 截断同口径：中文约1.5字/token）
    """
    svc = StateManager.get_instance()
    try:
        state_json = svc.build_agent_context("bound")
    except Exception as e:  # 上下文构建失败不应阻断用量展示
        logger.warning(f"[Agent] 上下文用量统计失败: {e}")
        state_json = ""
    history_json = json.dumps(svc.get_chat_messages(), ensure_ascii=False)
    chars = len(state_json) + len(history_json)
    return {
        "chars": chars,
        "est_tokens": estimate_tokens(state_json) + estimate_tokens(history_json),
        "state_chars": len(state_json),
        "history_chars": len(history_json),
    }
