"""会话投影（D2 批 commit2）：事件账本纯折叠出客户端读模型。

蓝图 = dsh session-projection（docs/subsystems/session-projection.zh.md，用户
2026-09-18 裁决记住、2026-09-19 认可 state/view 分离）的同构精简版：

- 每个投影单元 = init/apply/view 三纯函数：apply 只读事件产新 state（plain dict），
  view 把 state 翻成客户端 wire 值；**渲染不归本层**（前端组件自便）。
- snapshot = 全量事件折到账尾的一致切（asOfSeq + 各单元 view），pull 模型
  （dsh coldSnapshot 同构）；live 增量仍走既有任务流 SSE，本层不推变更帧
  （开工前修正④：done 帧已携暂停/决策表单，变更推送无消费方，不私设通道）。
- 双跑对比：snapshot 时把 interaction_pause 单元 view 与 StateManager 权威
  interaction 三态对拍，不一致打 [ProjDiff] 警告——对比干净前前端不切消费方
  （计划书 §七风险 B）。
- 只读不写：本层绝不改 StateManager（宪法 Rule 3 唯一写入点不动）。

四单元：interaction_pause（暂停卡账本物化）/ subagent_catalog（子代理目录）/
storyboard_progress（故事板进度计数）/ chat_tail（聊天尾摘要）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.core import session_log

# 聊天尾摘要保留条数上限（防长会话 snapshot 膨胀）
_CHAT_TAIL_CAP = 20
# 故事板最近标题保留条数
_TITLE_CAP = 5


# ------------------------------------------------------------ 单元：交互暂停


def _pause_init() -> Dict[str, Any]:
    return {"active": None, "pause_count": 0}


def _pause_apply(state: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    etype = ev.get("type")
    if etype == "assistant/message":
        for tc in ev.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            if fn.get("name") != "workflow_pause":
                continue
            import json as _json
            try:
                args = _json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            state = dict(state)
            state["active"] = {
                "seq": ev.get("seq"),
                "message": str(args.get("message") or ""),
                "options": list(args.get("options") or []),
            }
            state["pause_count"] = int(state.get("pause_count") or 0) + 1
    elif etype == "user/message" and str(ev.get("source") or "user") == "user":
        # 真人用户消息 = 暂停被消费（合成事件 source=state/checkpoint 不算）
        if state.get("active") is not None:
            state = dict(state)
            state["active"] = None
    return state


def _pause_view(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "active_pause": state.get("active"),
        "pause_count": int(state.get("pause_count") or 0),
    }


# ------------------------------------------------------------ 单元：子代理目录


def _sub_init() -> Dict[str, Any]:
    return {"pending": {}, "entries": []}


def _sub_apply(state: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    etype = ev.get("type")
    if etype == "assistant/message":
        for tc in ev.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            if fn.get("name") != "run_subagent":
                continue
            import json as _json
            try:
                args = _json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            state = dict(state)
            pending = dict(state["pending"])
            pending[str(tc.get("id") or "")] = len(state["entries"])
            state["pending"] = pending
            state["entries"] = list(state["entries"]) + [{
                "call_id": str(tc.get("id") or ""),
                "stage": str(args.get("stage") or ""),
                "label": str(args.get("task") or "")[:60],
                "status": "running",
                "seq": ev.get("seq"),
            }]
    elif etype == "tool/result" and ev.get("name") == "run_subagent":
        idx = state["pending"].get(str(ev.get("call_id") or ""))
        if idx is None:
            return state
        state = dict(state)
        entries = list(state["entries"])
        if 0 <= int(idx) < len(entries):
            entries[int(idx)] = dict(
                entries[int(idx)],
                status="completed" if ev.get("ok", True) else "failed",
            )
        state["entries"] = entries
    return state


def _sub_view(state: Dict[str, Any]) -> Dict[str, Any]:
    return {"subagents": list(state.get("entries") or [])}


# ------------------------------------------------------------ 单元：故事板进度


def _sb_init() -> Dict[str, Any]:
    return {"pending": {}, "counts": {"keyElement": 0, "shot": 0, "audio": 0},
            "titles": []}


def _sb_apply(state: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    etype = ev.get("type")
    if etype == "assistant/message":
        added = False
        pending = None
        for tc in ev.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            if fn.get("name") != "storyboard_create_group":
                continue
            import json as _json
            try:
                args = _json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            if pending is None:
                pending = dict(state["pending"])
            pending[str(tc.get("id") or "")] = {
                "group_type": str(args.get("group_type") or ""),
                "title": str(args.get("title") or "")[:40],
            }
            added = True
        if added:
            state = dict(state)
            state["pending"] = pending
    elif etype == "tool/result" and ev.get("name") == "storyboard_create_group":
        meta = state["pending"].get(str(ev.get("call_id") or ""))
        if not meta or not ev.get("ok", True):
            return state
        gt = str(meta.get("group_type") or "")
        key = {"keyElement": "keyElement", "shot": "shot",
               "audio": "audio"}.get(gt)
        if key is None:
            return state
        state = dict(state)
        counts = dict(state["counts"])
        counts[key] = int(counts.get(key) or 0) + 1
        state["counts"] = counts
        if meta.get("title"):
            state["titles"] = (
                list(state["titles"]) + [meta["title"]])[-_TITLE_CAP:]
    return state


def _sb_view(state: Dict[str, Any]) -> Dict[str, Any]:
    return {"counts": dict(state.get("counts") or {}),
            "recent_titles": list(state.get("titles") or [])}


# ------------------------------------------------------------ 单元：聊天尾摘要


def _tail_init() -> Dict[str, Any]:
    return {"tail": []}


def _tail_apply(state: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    etype = ev.get("type")
    item: Optional[Dict[str, Any]] = None
    if etype == "assistant/message":
        item = {"kind": "assistant", "seq": ev.get("seq"),
                "snippet": str(ev.get("content") or "")[:80]}
    elif etype == "tool/result":
        item = {"kind": "tool", "seq": ev.get("seq"),
                "name": str(ev.get("name") or ""),
                "ok": bool(ev.get("ok", True))}
    elif etype == "turn/end":
        item = {"kind": "turn_end", "seq": ev.get("seq"),
                "reason": str(ev.get("reason") or "")}
    if item is None:
        return state
    state = dict(state)
    state["tail"] = (list(state["tail"]) + [item])[-_CHAT_TAIL_CAP:]
    return state


def _tail_view(state: Dict[str, Any]) -> Dict[str, Any]:
    return {"tail": list(state.get("tail") or [])}


UNITS: Dict[str, Dict[str, Any]] = {
    "interaction_pause": {"init": _pause_init, "apply": _pause_apply,
                          "view": _pause_view},
    "subagent_catalog": {"init": _sub_init, "apply": _sub_apply,
                         "view": _sub_view},
    "storyboard_progress": {"init": _sb_init, "apply": _sb_apply,
                            "view": _sb_view},
    "chat_tail": {"init": _tail_init, "apply": _tail_apply, "view": _tail_view},
}


def fold_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """全量事件折到账尾（纯函数；单元测试直接打这里）。"""
    states = {name: spec["init"]() for name, spec in UNITS.items()}
    for ev in events or []:
        for name, spec in UNITS.items():
            states[name] = spec["apply"](states[name], ev)
    return states


def view_states(states: Dict[str, Any]) -> Dict[str, Any]:
    return {name: UNITS[name]["view"](states.get(name) or UNITS[name]["init"]())
            for name in UNITS}


def snapshot(svc: Any, conversation_id: str = "") -> Dict[str, Any]:
    """一致切：asOfSeq + 各单元 view；顺带与权威 interaction 双跑对拍留痕。"""
    events = session_log.load_events(svc, conversation_id)
    states = fold_events(events)
    values = view_states(states)
    as_of = int(events[-1].get("seq") or 0) if events else -1
    _dual_run_pause(svc, values.get("interaction_pause") or {})
    return {"asOfSeq": as_of, "values": values}


def _dual_run_pause(svc: Any, pause_view: Dict[str, Any]) -> None:
    """双跑对比（计划书 §七风险 B）：投影暂停态 vs StateManager 权威三态。

    只打日志不阻断、不修正——对比干净前前端不切消费方。权威侧读
    interaction.active_pause / awaiting_confirmation（workflow_runtime reducer 写）。
    """
    try:
        inter = (svc.state_dict or {}).get("interaction") or {}
        auth_active = bool(inter.get("active_pause")) or bool(
            inter.get("awaiting_confirmation"))
        proj_active = pause_view.get("active_pause") is not None
        if auth_active != proj_active:
            logger.warning(
                "[ProjDiff] pause 投影与权威不一致 auth={} proj={} pause_count={}",
                auth_active, proj_active, pause_view.get("pause_count"),
            )
    except Exception as e:  # 对拍绝不影响主流程
        logger.debug("[ProjDiff] 对拍异常忽略: {}", e)


__all__ = ["UNITS", "fold_events", "view_states", "snapshot"]
