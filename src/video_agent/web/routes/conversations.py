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
from typing import Dict, List

from src.video_agent.exceptions import VideoAgentError
from src.video_agent.core import session_log
from src.video_agent.state import conversation_ops
from src.video_agent.state.manager import StateManager
from src.video_agent.web.agent_task_manager import get_agent_task_manager
from src.video_agent.web.error_payload import LEGACY_NOT_FOUND, LEGACY_VALIDATION_ERROR

router = APIRouter()


class CreateConversationRequest(BaseModel):
    title: str = ""


class ThreadRequest(BaseModel):
    """幂等取/建隐藏线程（微调真子对话）：scope 形如
    {kind, cat, group_id, draft_id, label}；同目标重复提交返回同一线程。"""
    scope: Dict[str, str] = {}


class ThreadUnrefRequest(BaseModel):
    """移除线程参考素材引用（二期子对话批 3 浮窗清单移除通道）：
    只解逻辑绑定（从 scopeRefs 删引用），物理文件不删。"""
    conversation_id: str
    ref_id: str


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
    async with svc.lock:
        # 任务实例（后台 Agent 任务专属 StateManager）写过更新时从磁盘重载，
        # 防全局实例内存陈旧返回空历史（微调线程消息由任务实例落盘）
        svc.reload_if_stale()
    msgs = svc.get_conversation_messages(conversation_id)
    if msgs is None:
        raise VideoAgentError("对话不存在", status_code=404, error_code=LEGACY_NOT_FOUND)
    return {"conversation_id": conversation_id, "messages": msgs}


@router.get("/conversations/subagents")
async def list_subagent_threads():
    """子代理隐藏线程清单（B3 左栏子任务卡）：state 层元信息（id/标题/label/
    父会话）+ 事件流派生的运行态与步数。与主清单解耦（带 scope 的线程
    本就不出 conversations_meta_payload）。"""
    svc = StateManager.get_instance()
    async with svc.lock:
        svc.reload_if_stale()
        threads = svc.subagent_threads()
    for t in threads:
        st = session_log.thread_status(svc, str(t.get("conversation_id") or ""))
        t["status"] = st["status"]
        t["steps"] = st["steps"]
    return {"subagents": threads}


@router.get("/conversations/subagents/{conversation_id}/record")
async def get_subagent_record(conversation_id: str):
    """子代理只读执行记录：从其隐藏线程事件流派生（单一事实源，无消息副本）。
    非子代理线程（scope.kind≠subagent）一律 404，不暴露任意会话事件流。"""
    svc = StateManager.get_instance()
    async with svc.lock:
        svc.reload_if_stale()
        scope = svc.get_conversation_scope(conversation_id)
    if str(scope.get("kind") or "") != "subagent":
        raise VideoAgentError(
            "子代理线程不存在", status_code=404, error_code=LEGACY_NOT_FOUND)
    messages = session_log.project_readable_record(svc, conversation_id)
    return {"conversation_id": conversation_id, "messages": messages}


@router.post("/conversations/thread")
async def get_or_create_thread(body: ThreadRequest):
    """幂等取/建隐藏线程（微调真子对话）：按 scope 的 kind+cat+group_id+
    draft_id 查已有线程，有则直接返回；无则新建（不设活跃、不重绑
    chatMessages）。历史装载复用 get_conversation_messages 单一来源；
    再点微调入口/刷新页面后据此重开同一线程且保留全部历史。"""
    svc = StateManager.get_instance()
    scope = dict(body.scope or {})
    async with svc.lock:
        # 磁盘账本新于内存时重载：微调线程消息由后台任务专属实例落盘，
        # 不重载会返回陈旧空历史（重开浮窗丢历史根因，任务 #19）
        svc.reload_if_stale()
        conv = svc.find_scoped_conversation(scope)
        if conv is None:
            label = str(scope.get("label") or "")
            conv = svc.create_scoped_conversation(
                scope, title=f"微调 | {label}" if label else "")
    return {
        "conversation_id": conv["id"],
        "messages": svc.get_conversation_messages(conv["id"]) or [],
        "scope": conv.get("scope") or {},
        # 本线程参考素材（批 3）：浮窗「本线程参考素材：N 个」清单数据源，
        # 素材随重生成持续生效，重开浮窗清单可重建（不依赖前端内存）
        "scope_refs": conv.get("scopeRefs") or [],
    }


@router.post("/conversations/thread/unref")
async def unref_thread_material(body: ThreadUnrefRequest):
    """移除线程参考素材引用（二期子对话批 3）：移除 = 从线程对话的 scopeRefs
    删引用（下次生成不再注入），物理文件不删（与主对话素材删除同口径）。
    线程/引用不存在返 404（幂等友好：前端据此刷新清单）。"""
    svc = StateManager.get_instance()
    async with svc.lock:
        ok = conversation_ops.remove_thread_scope_ref(
            svc, body.conversation_id, body.ref_id)
    if not ok:
        raise VideoAgentError("线程或素材引用不存在", status_code=404, error_code=LEGACY_NOT_FOUND)
    return {"ok": True}


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

