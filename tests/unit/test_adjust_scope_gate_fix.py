# -*- coding: utf-8 -*-
"""附带缺陷修复（二期子对话批 1）：scope 任务并发闸计数真生效。

既有缺陷：`web/adjust_scope.py::_scope_task_limit_exceeded` 按
`list_running()` 输出统计 `adjust_scope` 标记，但 AgentTaskManager.list_running
输出字典缺该键 → 计数恒 0，4 并发闸永远不触发。
本测试用真实台账（非桩）钉死：输出补键、只计 scope 任务、阈值可配。
"""
from src.video_agent.config import settings
from src.video_agent.web.adjust_scope import _scope_task_limit_exceeded
from src.video_agent.web.agent_task_manager import AgentTaskManager

_SCOPE_A = {
    "kind": "adjust", "cat": "shotGroups",
    "group_id": "grp-1", "draft_id": "draft-1", "label": "分镜 1-1",
}


class _NullStore:
    """kv 落盘桩（测试隔离：不触真实 sqlite）"""

    def exists(self, key):
        return False

    def load(self, key):
        return None

    def save(self, key, payload):
        pass


def _record(task_id, conversation_id="", adjust_scope=None):
    rec = {
        "task_id": task_id,
        "project_id": "proj-x",
        "conversation_id": conversation_id,
        "status": "running",
        "created_at": 0.0,
        "status_text": "正在连接…",
    }
    if adjust_scope is not None:
        rec["adjust_scope"] = adjust_scope
    return rec


def test_list_running_output_carries_adjust_scope_key():
    tm = AgentTaskManager(store=_NullStore())
    tm._tasks["t-scope"] = _record("t-scope", "conv-thread", _SCOPE_A)
    tm._tasks["t-plain"] = _record("t-plain")
    out = {t["task_id"]: t for t in tm.list_running()}
    # 契约：scope 标记随输出透传（并发闸统计口径），非 scope 任务缺省空
    assert out["t-scope"]["adjust_scope"] == _SCOPE_A
    assert out["t-plain"]["adjust_scope"] == {}


def test_scope_concurrency_gate_counts_real_records(monkeypatch):
    import src.video_agent.web.agent_task_manager as atm_mod

    tm = AgentTaskManager(store=_NullStore())
    tm._tasks["t-scope"] = _record("t-scope", "conv-thread", _SCOPE_A)
    tm._tasks["t-plain"] = _record("t-plain")  # 非 scope 不计入
    monkeypatch.setattr(atm_mod, "get_agent_task_manager", lambda: tm)

    object.__setattr__(settings, "adjust_task_concurrency", 1)
    try:
        # 1 个 scope 运行中任务即达闸（修复前计数恒 0 永不触发）
        assert _scope_task_limit_exceeded("proj-x") is True
        tm._tasks.pop("t-scope")
        assert _scope_task_limit_exceeded("proj-x") is False
    finally:
        object.__setattr__(settings, "adjust_task_concurrency", 4)
