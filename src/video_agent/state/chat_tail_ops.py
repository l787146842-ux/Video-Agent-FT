"""对话尾部操作域：截断重答 + 建议动作消毒 + 防抖冲刷（自 manager.py 切出）。

本模块只依赖 StateManager 的既有接口/内部属性（同包受控访问），不被
manager 反向依赖之外的任何模块引用，无循环依赖。

截断写入语义：truncate_chat_tail 是破坏性写入，落盘被版本闸拒绝时不能
静默放行（内存已截断而磁盘未变会造成双态分裂）——抛 StateConflictError，
路由层以 409 冲突应答且不启动后续 agent 任务。
"""
import asyncio
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.exceptions import StateConflictError

from . import conversation_ops

# 截断重答内部标记（后端自用，不属公共请求契约）：/chat/truncate-resend
# 已把（编辑后的）用户消息落盘在历史尾部，路由置位后发送管线各落盘点
# 据此守卫不重复持久化，防用户气泡翻倍。asyncio.create_task 创建 worker
# 时拷贝当前上下文，标记随任务传播（contextvar 即内部参数通道）。
user_message_persisted: ContextVar[bool] = ContextVar(
    "user_message_persisted", default=False,
)


def sanitize_suggested_actions(actions: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """建议动作按钮消毒：仅保留 kind 非空项，三字段一律字符串化。"""
    out: List[Dict[str, Any]] = []
    for act in actions or []:
        kind = str((act or {}).get("kind") or "")
        if not kind:
            continue
        out.append({
            "kind": kind,
            "label": str((act or {}).get("label") or ""),
            "value": str((act or {}).get("value") or ""),
        })
    return out


async def flush_pending_saves(svc) -> None:
    """冲刷在途防抖写（破坏性写入前置步骤）。

    截断前先取消/等待在途防抖任务并把挂起脏变更同步落盘：防抖写与
    截断写同走 save 主通路，先冲刷保证截断落盘时的版本闸读到的磁盘
    账本已含此前全部变更，杜绝两者交错互盖。
    """
    task = svc._save_flush_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    svc._save_flush_task = None
    if svc._save_dirty:
        svc._save_dirty = False
        await asyncio.to_thread(svc.save)


def _resync_from_disk(svc) -> None:
    """冲突回滚：版本闸拒绝写入后，丢弃内存未落盘变更并从磁盘重载，
    保证被截断的内存态不残留（对快照/只读端点继续呈现磁盘事实）。"""
    svc._save_dirty = False
    task = svc._save_flush_task
    if task is not None and not task.done():
        task.cancel()
    svc._save_flush_task = None
    pid = svc.active_project_id
    loaded = svc._repo.load_project(pid) if pid else None
    if loaded is None:
        return
    svc._raw_state = loaded
    svc._known_version = svc._disk_board_version(pid)
    svc._state_dirty = True
    svc._context_cache.clear()
    svc._clear_undo_redo()
    svc._ensure_conversations()


def truncate_chat_tail(svc, keep_index: int, new_text: Optional[str] = None,
                       conversation_id: str = "") -> Optional[Dict[str, Any]]:
    """截断对话尾部（截断重答用）：真正丢弃 keep_index 之后的全部消息
    并立即落盘（版本账本闸与 save 主通路一致）。
    conversation_id 显式定向目标对话（批 6-1）；缺省走绑定/活跃对话单点。

    new_text 非 None → 替换 keep_index 处消息正文（turnId 等既有元数据
    原样保留）；该消息若含富文本 parts 则清空（编辑框只编辑纯文本，
    保留旧 parts 会与正文错位）。
    返回保留的 keep_index 处消息；keep_index 越界/为负返回 None（不写入）。
    落盘被版本闸拒绝（磁盘账本更新）→ 回滚内存态并抛 StateConflictError。
    """
    if not isinstance(keep_index, int):
        return None
    msgs = conversation_ops.target_chat_messages(svc, conversation_id)
    if keep_index < 0 or keep_index >= len(msgs):
        return None
    if keep_index + 1 < len(msgs):
        del msgs[keep_index + 1:]
    entry = msgs[keep_index]
    if new_text is not None:
        entry["text"] = new_text
        entry.pop("parts", None)
    svc._state_dirty = True
    svc._context_cache.clear()
    if not svc.save():
        _resync_from_disk(svc)
        raise StateConflictError(
            f"项目 {svc.active_project_id} 截断写入被版本闸拒绝"
            "（磁盘账本新于本实例，别的实例写过更新数据）",
        )
    return entry


def restore_chat_tail(svc, keep_index: int, tail_entries: List[Dict[str, Any]],
                      conversation_id: str = "") -> None:
    """截断重答回滚：把截断前取的尾部快照（自 keep_index 起）原样恢复并立即落盘。
    conversation_id 与对应截断同口径定向（批 6-1）。

    用于截断已生效而起任务失败的极小窗口：破坏性截断不得遗留半成品状态。
    临界区内无其他写者，版本闸拒绝理论不可达；真发生时只留告警不再抛
    （回滚失败不得遮盖原始 500）。
    """
    msgs = conversation_ops.target_chat_messages(svc, conversation_id)
    msgs[keep_index:] = tail_entries
    svc._state_dirty = True
    svc._context_cache.clear()
    if not svc.save():
        logger.warning(
            f"[ChatTail] 项目 {svc.active_project_id} 截断回滚落盘被版本闸拒绝（内存态已恢复）")
