"""
/api/conversations — 同一项目的多对话管理（新建 / 切换 / 删除 / 列表）

规则：
- 每个项目至少保留一个对话（仅剩一个时删除请求返回 400）；
- 所有响应统一返回完整 {conversations, active_conversation_id}，
  前端据此整体刷新标签栏并装载目标对话的消息；
- 写入走 StateManager（Rule3 唯一写入点）+ svc.lock 临界区。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.video_agent.state.manager import StateManager

router = APIRouter()


class CreateConversationRequest(BaseModel):
    title: str = ""


@router.get("/conversations")
async def list_conversations():
    """列出当前项目的全部对话（含消息）+ 活跃对话 ID"""
    return StateManager.get_instance().list_conversations()


@router.post("/conversations")
async def create_conversation(body: CreateConversationRequest):
    """新建对话并设为活跃"""
    svc = StateManager.get_instance()
    async with svc.lock:
        return svc.create_conversation(body.title)


@router.post("/conversations/{conversation_id}/activate")
async def activate_conversation(conversation_id: str):
    """切换活跃对话"""
    svc = StateManager.get_instance()
    async with svc.lock:
        payload = svc.switch_conversation(conversation_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return payload


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """删除对话（仅剩一个时拒绝）"""
    svc = StateManager.get_instance()
    convs = svc.list_conversations()["conversations"]
    exists = any(c["id"] == conversation_id for c in convs)
    if not exists:
        raise HTTPException(status_code=404, detail="对话不存在")
    if len(convs) <= 1:
        raise HTTPException(status_code=400, detail="仅剩一个对话，不能关闭")
    async with svc.lock:
        payload = svc.delete_conversation(conversation_id)
    if payload is None:
        raise HTTPException(status_code=400, detail="仅剩一个对话，不能关闭")
    return payload
