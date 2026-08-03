"""
/api/agent — Agent 聊天端点（路由层，业务逻辑委托给 chat_service.py）

流程：服务端构建上下文 → 多步 LLM 循环（≤3 轮）→ 解析并执行 studio-actions → 持久化 → 返回。

- 上下文注入在服务端完成（前端只发消息本体 + 选中态），服务端是唯一事实源；
- 仅当 provider 为空/mock 时走 mock；真实供应商失败返回 502 + 真实错误。
"""
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.chat_service import stream_worker, non_stream_worker, sse_event_generator
from src.video_agent.exceptions import AdapterError, GenerationError
from src.video_agent.core.tracer import AgentTracer

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    system_prompt: str = ""
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


class ChatResponse(BaseModel):
    text: str
    applied_actions: int = 0
    steps: int = 1
    warnings: List[str] = []
    confirmation: str = ""
    documents_written: List[str] = []
    state: Optional[Dict[str, Any]] = None


@router.post("/agent/chat", response_model=ChatResponse)
@router.post("/canvas-llm", response_model=ChatResponse)
@router.post("/chat", response_model=ChatResponse)
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
@router.post("/canvas-llm/stream")
@router.post("/chat/stream")
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
