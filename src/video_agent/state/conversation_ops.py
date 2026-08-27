"""多对话与聊天消息域（自 manager.py 切出）。

职责：同一项目多对话窗口的结构维护（不变式：chatMessages 始终指向
活跃对话 messages 的同一引用）+ 聊天条目构建与追加（防抖落盘 +
尾部截断保留上限）。

本模块只依赖 StateManager 的既有接口/内部属性（同包受控访问），
不反向 import manager，无循环依赖。
"""
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.video_agent.utils import gen_id

from . import chat_tail_ops

if TYPE_CHECKING:  # 仅类型标注用，运行期不 import manager（防循环）
    from .manager import StateManager

# 聊天记录保留上限（超出后截断最旧的消息）
CHAT_HISTORY_LIMIT = 200


def ensure_conversations(svc: "StateManager") -> List[Dict[str, Any]]:
    """确保多对话结构存在并维护不变式：
    chatMessages 始终是活跃对话 messages 的同一引用，
    使 add_chat_message / 快照等既有路径无需改动。
    旧项目首次访问时把既有 chatMessages 迁入首个对话。
    """
    convs = svc._raw_state.get("conversations")
    if not isinstance(convs, list) or not convs:
        convs = [{
            "id": "conv-main",
            "title": "会话 1",
            "messages": svc._raw_state.get("chatMessages") or [],
        }]
        svc._raw_state["conversations"] = convs
        svc._raw_state["activeConversationId"] = "conv-main"
    active_id = svc._raw_state.get("activeConversationId") or ""
    active = next((c for c in convs if c.get("id") == active_id), None)
    if active is None:
        active = convs[0]
        svc._raw_state["activeConversationId"] = active["id"]
    msgs = active.setdefault("messages", [])
    if svc._raw_state.get("chatMessages") is not msgs:
        svc._raw_state["chatMessages"] = msgs
    return convs


def conversations_payload(svc: "StateManager") -> Dict[str, Any]:
    """多对话完整响应（含全部消息，供前端切换时直接装载）"""
    convs = ensure_conversations(svc)
    return {
        "conversations": [
            {"id": c.get("id", ""), "title": c.get("title", ""), "messages": c.get("messages", [])}
            for c in convs
        ],
        "active_conversation_id": svc._raw_state.get("activeConversationId", ""),
    }


def list_conversations(svc: "StateManager") -> Dict[str, Any]:
    """列出当前项目的全部对话（含消息）+ 活跃对话 ID。

    内部/兼容接口：HTTP 响应一律走 conversations_meta_payload（不含消息，
    消息单一来源）；快照创建等后端内部路径仍可读本接口取活跃消息。
    """
    return conversations_payload(svc)


def conversations_meta_payload(svc: "StateManager") -> Dict[str, Any]:
    """多对话元信息响应（仅 id/title 等元信息，不含消息副本）。

    消息单一来源：前端 convState 不再持有消息副本，
    消息装载一律走 get_conversation_messages（GET /conversations/{id}/messages）。
    """
    payload = conversations_payload(svc)
    payload["conversations"] = [
        {k: v for k, v in c.items() if k != "messages" and not str(k).startswith("_")}
        for c in payload["conversations"]
    ]
    return payload


def get_conversation_messages(svc: "StateManager", conversation_id: str) -> Optional[List[Dict[str, Any]]]:
    """按会话 ID 取消息（消息单一来源装载接口）；会话不存在返回 None。"""
    convs = ensure_conversations(svc)
    target = next((c for c in convs if c.get("id") == conversation_id), None)
    if target is None:
        return None
    return list(target.get("messages") or [])


def create_conversation(svc: "StateManager", title: str = "") -> Dict[str, Any]:
    """新建对话并设为活跃（chatMessages 重新绑定到空列表）"""
    convs = ensure_conversations(svc)
    cid = gen_id("conv")
    conv = {"id": cid, "title": title.strip() or f"新会话 {len(convs) + 1}", "messages": []}
    convs.append(conv)
    svc._raw_state["activeConversationId"] = cid
    svc._raw_state["chatMessages"] = conv["messages"]
    svc.save()
    return conversations_payload(svc)


def switch_conversation(svc: "StateManager", conversation_id: str) -> Optional[Dict[str, Any]]:
    """切换活跃对话；不存在返回 None"""
    convs = ensure_conversations(svc)
    target = next((c for c in convs if c.get("id") == conversation_id), None)
    if target is None:
        return None
    svc._raw_state["activeConversationId"] = conversation_id
    svc._raw_state["chatMessages"] = target.setdefault("messages", [])
    svc.save()
    return conversations_payload(svc)


def delete_conversation(svc: "StateManager", conversation_id: str) -> Optional[Dict[str, Any]]:
    """删除对话；仅剩一个时不允许删除；不存在返回 None"""
    convs = ensure_conversations(svc)
    if len(convs) <= 1:
        return None
    target = next((c for c in convs if c.get("id") == conversation_id), None)
    if target is None:
        return None
    convs.remove(target)
    if svc._raw_state.get("activeConversationId") == conversation_id:
        return switch_conversation(svc, convs[0]["id"])
    svc.save()
    return conversations_payload(svc)


def build_chat_entry(
    sender: str,
    text: str,
    model_name: str = "",
    image_urls: Optional[List[str]] = None,
    meta: str = "",
    confirm: str = "",
    applied_actions: int = 0,
    action_log: Optional[List[str]] = None,
    doc_card: str = "",
    trace: Optional[Dict[str, Any]] = None,
    doc_blocks: Optional[List[str]] = None,
    skill_blocks: Optional[List[str]] = None,
    confirm_options: Optional[List[Dict[str, Any]]] = None,
    turn_id: str = "",
    error_detail: str = "",
    pause_id: str = "",
    pause_answered: Optional[Dict[str, str]] = None,
    kind: str = "",
    video_items: Optional[List[Dict[str, Any]]] = None,
    suggested_actions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """构建单条聊天记录条目（纯函数，不落盘）。

    产生时刻（epoch ms）：随消息落盘，历史装载透传带回，
    前端悬停工具条显示 HH:MM；存量旧消息无此字段则前端不显示时间。
    """
    entry: Dict[str, Any] = {"sender": sender, "text": text, "ts": int(time.time() * 1000)}
    if model_name:
        entry["modelName"] = model_name
    if image_urls:
        entry["imageCard"] = {"image_urls": list(image_urls)}
    if video_items:
        items: List[Dict[str, Any]] = []
        for it in video_items:
            url = str((it or {}).get("url") or "")
            if not url:
                continue
            item: Dict[str, Any] = {"url": url}
            if str((it or {}).get("name") or ""):
                item["name"] = str(it["name"])
            if str((it or {}).get("thumb") or ""):
                item["thumb"] = str(it["thumb"])
            items.append(item)
        if items:
            entry["videoCard"] = {"items": items}
    if meta:
        entry["meta"] = meta
    if confirm:
        entry["confirm"] = confirm
    if applied_actions:
        entry["appliedActions"] = applied_actions
    if action_log:
        entry["actionLog"] = list(action_log)
    if doc_card:
        entry["docCard"] = doc_card
    if trace and trace.get("steps"):
        entry["trace"] = trace
    if doc_blocks:
        entry["docBlocks"] = list(doc_blocks)
    if skill_blocks:
        entry["skillBlocks"] = list(skill_blocks)
    if confirm_options:
        entry["confirmOptions"] = list(confirm_options)
    if turn_id:
        entry["turnId"] = turn_id
    if pause_id:
        entry["pauseId"] = pause_id
    if pause_answered:
        entry["pauseAnsweredId"] = str(pause_answered.get("pause_id") or "")
        entry["pauseAnsweredValue"] = str(pause_answered.get("value") or "")
        # 三态消费决策（ADR-0006）：accept/decline 随标记落盘，
        # 前端「当时所选」对勾与拒绝态同源可重建（缺省不产生空字段）
        if pause_answered.get("decision"):
            entry["pauseAnsweredDecision"] = str(pause_answered.get("decision"))
    if kind:
        entry["kind"] = kind
    if error_detail:
        # 错误气泡的技术详情（上游原始报文），前端折叠展示
        entry["errorDetail"] = error_detail
    if suggested_actions:
        # 建议动作按钮消毒（实现见 chat_tail_ops）
        acts = chat_tail_ops.sanitize_suggested_actions(suggested_actions)
        if acts:
            entry["suggestedActions"] = acts
    return entry


def add_chat_message(
    svc: "StateManager",
    sender: str,
    text: str,
    model_name: str = "",
    image_urls: Optional[List[str]] = None,
    meta: str = "",
    confirm: str = "",
    applied_actions: int = 0,
    action_log: Optional[List[str]] = None,
    doc_card: str = "",
    trace: Optional[Dict[str, Any]] = None,
    doc_blocks: Optional[List[str]] = None,
    skill_blocks: Optional[List[str]] = None,
    confirm_options: Optional[List[Dict[str, Any]]] = None,
    turn_id: str = "",
    error_detail: str = "",
    pause_id: str = "",
    pause_answered: Optional[Dict[str, str]] = None,
    kind: str = "",
    video_items: Optional[List[Dict[str, Any]]] = None,
    suggested_actions: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """追加聊天记录并持久化（防抖合并落盘）。截断保留最近 200 条，
    防止状态文件无上限增长。各附加字段语义见 StateManager.add_chat_message。"""
    ensure_conversations(svc)
    msgs = svc._raw_state["chatMessages"]
    entry = build_chat_entry(
        sender, text, model_name, image_urls, meta, confirm,
        applied_actions, action_log, doc_card, trace, doc_blocks,
        skill_blocks, confirm_options, turn_id, error_detail, pause_id,
        pause_answered, kind, video_items, suggested_actions,
    )
    msgs.append(entry)
    if len(msgs) > CHAT_HISTORY_LIMIT:
        del msgs[: len(msgs) - CHAT_HISTORY_LIMIT]
    svc.save_debounced()
