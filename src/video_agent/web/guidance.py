# -*- coding: utf-8 -*-
"""引导消息轮间注入队列（7777 三轮：不打断执行，操作间隙送达）。

Agent 任务执行期间用户点「引导」发送的消息不打断当前操作：
前端调插入 API 登记到本项目级队列，agent_loop 在轮间边界
（上一轮操作完成、本轮 LLM 调用之前）drain 取出，以 user 消息
注入上下文，由模型自行判断：与任务相关 → 按引导调整执行；
是提问 → 先回答再继续。

队列为内存态（按项目隔离）：任务恰在注入前结束时消息不会被消费，
前端排队区兜底会在任务结束后按普通消息自动发出，不丢消息。
"""
from collections import defaultdict
from typing import Any, Dict, List

# project_id → 待注入消息列表（每项 {"id": ..., "text": ...}）
_PENDING: Dict[str, List[Dict[str, Any]]] = defaultdict(list)


def enqueue_guidance(project_id: str, msg_id: str, text: str) -> bool:
    """登记一条待注入引导消息；空项目/空文本拒绝，返回是否受理。"""
    pid = str(project_id or "").strip()
    body = str(text or "").strip()
    if not pid or not body:
        return False
    _PENDING[pid].append({"id": str(msg_id or ""), "text": body})
    return True


def drain_guidance(project_id: str) -> List[Dict[str, Any]]:
    """取走该项目全部待注入消息（轮间边界调用；无积压返回空列表）。"""
    pid = str(project_id or "").strip()
    if not pid:
        return []
    items = _PENDING.pop(pid, [])
    return [i for i in items if str(i.get("text") or "").strip()]
