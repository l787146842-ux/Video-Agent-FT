"""多对话与聊天消息域（自 manager.py 切出）。

职责：同一项目多对话窗口的结构维护（不变式：chatMessages 始终指向
活跃对话 messages 的同一引用）+ 聊天条目构建与追加（防抖落盘 +
尾部截断保留上限）。

本模块只依赖 StateManager 的既有接口/内部属性（同包受控访问），
不反向 import manager，无循环依赖。
"""
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.video_agent.config import settings
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
    单点过滤（微调真子对话）：带 scope 的隐藏线程对话不出主清单，
    仅供 scoped_threads_payload 另面暴露（前端标签栏不再见微调线程）。
    """
    ensure_conversations(svc)
    convs = svc._raw_state.get("conversations") or []
    return {
        "conversations": [
            {k: v for k, v in conv.items() if k != "messages" and not str(k).startswith("_")}
            for conv in convs
            if not conv.get("scope")
        ],
        "active_conversation_id": svc._raw_state.get("activeConversationId", ""),
    }


def find_scoped_conversation(
    svc: "StateManager", scope: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """按 scope 的 kind+cat+group_id+draft_id 查已有隐藏线程对话；无则 None。
    幂等取/建线程的查找单点（POST /api/conversations/thread）。"""
    ensure_conversations(svc)
    keys = ("kind", "cat", "group_id", "draft_id")
    for c in svc._raw_state.get("conversations") or []:
        if not isinstance(c, dict) or not isinstance(c.get("scope"), dict):
            continue
        if all(str((c["scope"] or {}).get(k) or "") == str(scope.get(k) or "") for k in keys):
            return c
    return None


def create_scoped_conversation(
    svc: "StateManager", scope: Dict[str, Any], title: str = "",
) -> Dict[str, Any]:
    """新建隐藏线程对话（微调真子对话的线程载体）。

    与 create_conversation 的两点本质区别：不设活跃对话、不重绑
    chatMessages（主对话写入目标不变，线程靠任务实例绑定定向）；
    对话元信息携带 scope（kind/cat/group_id/draft_id/label 等），
    供 conversations_meta_payload 单点过滤与前端角标/浮窗重开识别。"""
    convs = ensure_conversations(svc)
    cid = gen_id("conv")
    conv = {
        "id": cid,
        "title": (title.strip() or "微调线程"),
        "messages": [],
        "scope": dict(scope or {}),
    }
    convs.append(conv)
    svc.save()
    return conv


def scoped_threads_payload(svc: "StateManager") -> Dict[str, Any]:
    """隐藏线程清单（供前端角标/浮窗重开）：仅元信息 + scope，
    消息装载仍走 get_conversation_messages（消息单一来源）。"""
    ensure_conversations(svc)
    return {
        "threads": [
            {
                "conversation_id": c.get("id", ""),
                "title": c.get("title", ""),
                "scope": dict(c.get("scope") or {}),
            }
            for c in svc._raw_state.get("conversations") or []
            if isinstance(c, dict) and isinstance(c.get("scope"), dict)
        ],
    }


def get_conversation_scope(svc: "StateManager", conversation_id: str) -> Dict[str, Any]:
    """按会话 ID 取其 scope 字典（隐藏线程判定用）；非线程/不存在返回空。"""
    for c in ensure_conversations(svc):
        if isinstance(c, dict) and c.get("id") == conversation_id:
            return dict(c.get("scope") or {})
    return {}


def subagent_threads(svc: "StateManager") -> List[Dict[str, Any]]:
    """子代理隐藏线程清单（B3 左栏子任务卡数据源，state 层不读事件流）：
    筛 scope.kind == 'subagent'，返回元信息（运行态/步骤数由 web 层经 session_log 补）。"""
    ensure_conversations(svc)
    out: List[Dict[str, Any]] = []
    for c in svc._raw_state.get("conversations") or []:
        if not isinstance(c, dict):
            continue
        scope = c.get("scope") or {}
        if str(scope.get("kind") or "") != "subagent":
            continue
        out.append({
            "conversation_id": str(c.get("id") or ""),
            "title": str(c.get("title") or ""),
            "label": str(scope.get("label") or ""),
            "parent_conversation": str(scope.get("parent_conversation") or ""),
        })
    return out


def board_draft_ids(groups: List[Dict[str, Any]]) -> set:
    """分组列表内草稿 id 集合（对象删除级联的新旧 id diff 口径）。"""
    ids = set()
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for d in g.get("drafts") or []:
            if isinstance(d, dict) and str(d.get("id") or ""):
                ids.add(str(d["id"]))
    return ids


def asset_pool_draft_ids(assets: List[Dict[str, Any]]) -> set:
    """未归类素材池内来源草稿 id 集合（评审修补批）：「移入素材池」是
    可还原的非破坏移动，其来源草稿（sourceDraft）仍属存活实体，
    删除级联的新旧 id diff 须计入 _new_ids，不得误删其微调线程。"""
    ids = set()
    for a in assets or []:
        if not isinstance(a, dict):
            continue
        src = a.get("sourceDraft")
        if isinstance(src, dict) and str(src.get("id") or ""):
            ids.add(str(src["id"]))
    return ids


def cleanup_scoped_threads_for_removed(
    svc: "StateManager", removed_draft_ids, save: bool = True,
    stop_tasks: Optional[Any] = None,
) -> List[str]:
    """对象删除级联：硬删 scope.draft_id 命中的隐藏线程（二期子对话批 1）。

    三写面同帧挂载（Agent FC 删除 / 整板 PUT / 三向合并）：删除与级联同帧，
    撤销快照栈含 conversations 全态，元素与线程历史随 Ctrl+Z 原子恢复。
    stop_tasks 由调用方注入在途任务掐停实现（web 层，先掐再删，防
    target_chat_messages 静默回落把在途写入污染主对话）；state 层不反向
    import web（依赖方向合宪，实现见 agent_task_manager.stop_tasks_bound_to_conversations）。
    save=False 供写面自带落盘的路径使用（避免重复写盘）。返回被删线程对话 id 列表。"""
    ids = {str(i) for i in (removed_draft_ids or set()) if str(i or "")}
    if not ids:
        return []
    ensure_conversations(svc)
    convs = svc._raw_state.get("conversations") or []
    hit_ids = sorted({
        str(c.get("id") or "") for c in convs
        if isinstance(c, dict) and isinstance(c.get("scope"), dict)
        and str((c.get("scope") or {}).get("draft_id") or "") in ids
        and str(c.get("id") or "")
    })
    if not hit_ids:
        return []
    # 在途任务先掐（调用方注入）：元素已不存在，任务失去目标；不掐则后续写入回落活跃对话
    if stop_tasks is not None:
        try:
            stop_tasks(hit_ids)
        except Exception:
            pass  # 任务台账不可用时尽力而为，不阻断线程删除级联
    svc._raw_state["conversations"] = [
        c for c in convs
        if not (isinstance(c, dict) and str(c.get("id") or "") in hit_ids)
    ]
    if save:
        svc.save()
    return hit_ids


def bind_thread_scope_refs(
    svc: "StateManager", conversation_id: str, attachments: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """子对话参考素材绑线程（二期子对话批 3）：把 scope 请求携带的引用追加到
    conversations[i][\"scopeRefs\"]（对话级绑定；不进全局 assets/uploadedDocs，
    主对话零污染）。素材随重生成持续生效；线程级联删除时引用随对话体消失；
    撤销/快照栈含 conversations，引用同口径原子恢复。按 url 去重，数量上限读
    settings.max_attachments（与主链路同口径）。须在 svc.lock 临界区内调用。
    返回本次新增的引用条目（线程不存在时不登记任何引用，返回空）。"""
    conv_id = str(conversation_id or "")
    added: List[Dict[str, str]] = []
    if not conv_id or not attachments:
        return added
    ensure_conversations(svc)
    conv = next(
        (c for c in svc._raw_state.get("conversations") or []
         if isinstance(c, dict) and str(c.get("id") or "") == conv_id), None)
    if conv is None:
        return added
    refs = conv.setdefault("scopeRefs", [])
    seen = {str(r.get("url") or "") for r in refs if isinstance(r, dict)}
    # 总量口径截断（评审修补批）：上限限的是线程引用总量而非单批，
    # 防直连 API 逐批发送绕过前端总量守卫无限膨胀（上下文全量注入）。
    room = max(0, int(settings.max_attachments) - len(refs))
    for att in list(attachments or [])[:room]:
        url = str((att or {}).get("url") or "")
        if not url or url in seen:
            continue
        entry = {
            "id": att.get("id") or gen_id("sref"),
            "name": att.get("name") or url,
            "kind": att.get("kind") or "file",
            "url": url,
        }
        refs.append(entry)
        seen.add(url)
        added.append(entry)
    if added:
        # 状态面变化：清上下文缓存，同请求后续轮次的 scopeRefs 注入即时刷新
        svc._context_cache.clear()
        svc.save()
    return added


def remove_thread_scope_ref(svc: "StateManager", conversation_id: str, ref_id: str) -> bool:
    """从线程 scopeRefs 移除一条引用（二期子对话批 3 浮窗清单移除通道）：
    只解逻辑绑定，物理文件不删（与主对话素材删除同口径，系统无素材 GC）。
    命中移除返回 True；线程不存在返回 False；线程存在但引用本就不存在
    幂等成功返回 True（评审修补批：前端同 url 去重后幽灵 id 解绑不得误报失败）。"""
    conv_id = str(conversation_id or "")
    rid = str(ref_id or "")
    if not conv_id or not rid:
        return False
    ensure_conversations(svc)
    conv = next(
        (c for c in svc._raw_state.get("conversations") or []
         if isinstance(c, dict) and str(c.get("id") or "") == conv_id), None)
    if conv is None:
        return False
    refs = conv.get("scopeRefs") or []
    kept = [r for r in refs
            if not (isinstance(r, dict) and str(r.get("id") or "") == rid)]
    if len(kept) == len(refs):
        return True  # 线程存在但引用本就不存在：幂等成功（无状态变化不落盘）
    conv["scopeRefs"] = kept
    svc._context_cache.clear()
    svc.save()
    return True


def target_chat_messages(svc: "StateManager", conversation_id: str = "") -> List[Dict[str, Any]]:
    """聊天写入目标消息列表单点（批 6-1 多会话并行）：
    显式 conversation_id 优先 → 实例绑定会话（svc.bound_conversation_id）
    → 回落活跃对话（chatMessages 不变式）。返回对话 messages 的同一引用，
    绑定会话不存在时静默回落（任务恢复/对话被删不得阻断写入）。"""
    ensure_conversations(svc)
    conv_id = str(conversation_id or getattr(svc, "bound_conversation_id", "") or "")
    if conv_id:
        convs = svc._raw_state.get("conversations") or []
        target = next((c for c in convs if isinstance(c, dict) and c.get("id") == conv_id), None)
        if target is not None:
            return target.setdefault("messages", [])
    return svc._raw_state["chatMessages"]


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
    reasoning_content: str = "",
) -> Dict[str, Any]:
    """构建单条聊天记录条目（纯函数，不落盘）。

    产生时刻（epoch ms）：随消息落盘，历史装载透传带回，
    前端悬停工具条显示 HH:MM；存量旧消息无此字段则前端不显示时间。
    """
    entry: Dict[str, Any] = {"sender": sender, "text": text, "ts": int(time.time() * 1000)}
    if model_name:
        entry["modelName"] = model_name
    # 推理模型思考内容（五项修法批 4，default-off 闸门在上游）：非空才落字段，
    # 供下轮历史组装回传（truncate_history 透传）；前端按未知键忽略
    if str(reasoning_content or "").strip():
        entry["reasoning_content"] = str(reasoning_content)
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
        # 三态消费决策（问即停，决策史见 git tag adr-archive-20260901）：accept/decline 随标记落盘，
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
    reasoning_content: str = "",
) -> None:
    """追加聊天记录并持久化（防抖合并落盘）。截断保留最近 200 条，
    防止状态文件无上限增长。写入目标：绑定会话优先、无绑定回落活跃对话
    （批 6-1，定向单点见 target_chat_messages）。各附加字段语义见 StateManager.add_chat_message。"""
    msgs = target_chat_messages(svc)
    entry = build_chat_entry(
        sender, text, model_name, image_urls, meta, confirm,
        applied_actions, action_log, doc_card, trace, doc_blocks,
        skill_blocks, confirm_options, turn_id, error_detail, pause_id,
        pause_answered, kind, video_items, suggested_actions,
        reasoning_content=reasoning_content,
    )
    msgs.append(entry)
    if len(msgs) > CHAT_HISTORY_LIMIT:
        del msgs[: len(msgs) - CHAT_HISTORY_LIMIT]
    svc.save_debounced()
