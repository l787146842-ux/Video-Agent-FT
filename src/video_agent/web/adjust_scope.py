# -*- coding: utf-8 -*-
"""
微调真子对话（对齐 Flova，批 S2）— 作用域辅助函数。

从 chat_service.py 抽出的内聚一组（file_lines 棘轮 900 行只降不升）：
- 生效判定（总开关/形态校验回落）
- scope 任务并发上限判定
- history 服务端装载（线程为单一事实源）

chat_service 侧 re-import 同名函数，既有调用点与测试引用不变。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # 仅类型收窄，防循环导入
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.routes.agent import ChatRequest

from src.video_agent.config import settings
from src.video_agent.web import agent_task_manager as _atm


def _active_adjust_scope(body: "ChatRequest") -> Optional[Dict[str, Any]]:
    """本请求生效的 adjust_scope（微调真子对话）：总开关关闭/未携带/
    非法形态一律回落 None（旧行为，一键回滚不失约束）。"""
    if not settings.adjust_subdialog_enabled:
        return None
    scope = getattr(body, "adjust_scope", None)
    return dict(scope) if isinstance(scope, dict) and scope else None


def _scope_task_limit_exceeded(project_id: str) -> bool:
    """scope 任务并发上限判定（防线程膨胀）：按运行中任务记录的
    adjust_scope 标记统计，达 settings.adjust_task_concurrency 即超限。
    （调用期属性访问：测试可 monkeypatch agent_task_manager.get_agent_task_manager）"""
    running = _atm.get_agent_task_manager().list_running(project_id)
    count = sum(1 for t in running if t.get("adjust_scope"))
    return count >= int(settings.adjust_task_concurrency)


def _scope_history_from_thread(svc: "StateManager", conversation_id: str) -> List[Dict[str, str]]:
    """history 服务端装载（微调真子对话的单一事实源）：线程落盘消息转
    role/content 序列，不再信前端 body.messages 窗口（刷新/多端同口径）。"""
    msgs = svc.get_conversation_messages(conversation_id) or []
    return [
        {"role": "user" if m.get("sender") == "user" else "assistant",
         "content": str(m.get("text") or "")}
        for m in msgs if str(m.get("text") or "").strip()
    ]
