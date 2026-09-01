"""
/api/conversations — 同一项目的多对话管理（新建 / 切换 / 删除 / 列表）

规则：
- 每个项目至少保留一个对话（仅剩一个时删除请求返回 400）；
- 所有响应统一返回 {conversations, active_conversation_id}，但对话项
  只含 id/title 等元信息（E-2 消息单一来源）：消息装载走
  GET /conversations/{id}/messages，前端不再持有消息副本；
- 写入走 StateManager（Rule3 唯一写入点）+ svc.lock 临界区。
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

from src.video_agent.exceptions import VideoAgentError
from src.video_agent.state.manager import StateManager
from src.video_agent.web.agent_task_manager import get_agent_task_manager
from src.video_agent.web.error_payload import LEGACY_NOT_FOUND, LEGACY_VALIDATION_ERROR

router = APIRouter()


class CreateConversationRequest(BaseModel):
    title: str = ""


class ConversationMeta(BaseModel):
    """对话元信息（E-2 消息单一来源：不含消息副本；后端多余键静默过滤）"""
    id: str
    title: str


class ConversationsMetaResponse(BaseModel):
    conversations: List[ConversationMeta]
    active_conversation_id: str


@router.get("/conversations", response_model=ConversationsMetaResponse)
async def list_conversations():
    """列出当前项目的全部对话（元信息，不含消息）+ 活跃对话 ID"""
    return StateManager.get_instance().conversations_meta_payload()


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str):
    """按会话 ID 拉消息（消息单一来源装载接口；会话不存在 404）。

    切会话/新建/关闭/分支后前端据此把目标对话历史装载进 chat store；
    刷新/重连路径仍由 /api/project/state 顶层 chatMessages 与
    SSE replay 快照承载（均为活跃对话消息）。
    """
    svc = StateManager.get_instance()
    msgs = svc.get_conversation_messages(conversation_id)
    if msgs is None:
        raise VideoAgentError("对话不存在", status_code=404, error_code=LEGACY_NOT_FOUND)
    return {"conversation_id": conversation_id, "messages": msgs}


@router.post("/conversations", response_model=ConversationsMetaResponse)
async def create_conversation(body: CreateConversationRequest):
    """新建对话并设为活跃（响应只含元信息，新对话消息为空列表）"""
    svc = StateManager.get_instance()
    async with svc.lock:
        svc.create_conversation(body.title)
    return svc.conversations_meta_payload()


@router.post("/conversations/{conversation_id}/activate", response_model=ConversationsMetaResponse)
async def activate_conversation(conversation_id: str):
    """切换活跃对话（响应只含元信息；目标对话消息经 messages 接口装载）"""
    svc = StateManager.get_instance()
    async with svc.lock:
        payload = svc.switch_conversation(conversation_id)
    if payload is None:
        raise VideoAgentError("对话不存在", status_code=404, error_code=LEGACY_NOT_FOUND)
    return svc.conversations_meta_payload()


@router.delete("/conversations/{conversation_id}", response_model=ConversationsMetaResponse)
async def delete_conversation(conversation_id: str):
    """删除对话（仅剩一个时拒绝；批 6-1：有绑定任务运行中时拒绝）"""
    svc = StateManager.get_instance()
    convs = svc.conversations_meta_payload()["conversations"]
    exists = any(c["id"] == conversation_id for c in convs)
    if not exists:
        raise VideoAgentError("对话不存在", status_code=404, error_code=LEGACY_NOT_FOUND)
    if len(convs) <= 1:
        raise VideoAgentError(
            "仅剩一个对话，不能关闭", status_code=400, error_code=LEGACY_VALIDATION_ERROR
        )
    # 删忙对话保护（批 6-1）：绑定任务运行中拒删（任务恢复后消息写入无主对话）；
    # 无绑定记录的旧任务（空会话字段）视为绑定活跃对话，同口径保守只拦活跃对话
    running = get_agent_task_manager().list_running(svc.active_project_id or "")
    active_id = str(svc._raw_state.get("activeConversationId") or "")
    bound = any(
        (str(t.get("conversation_id") or "") or active_id) == conversation_id
        for t in running
    )
    if bound:
        raise VideoAgentError(
            "该对话有 Agent 任务运行中，不能关闭", status_code=400,
            error_code=LEGACY_VALIDATION_ERROR
        )
    async with svc.lock:
        payload = svc.delete_conversation(conversation_id)
    if payload is None:
        raise VideoAgentError(
            "仅剩一个对话，不能关闭", status_code=400, error_code=LEGACY_VALIDATION_ERROR
        )
    return svc.conversations_meta_payload()

