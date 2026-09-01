# -*- coding: utf-8 -*-
"""批 S1 微调真子对话：后端线程实体与契约。

钉死契约：
1. create_scoped_conversation：不设活跃、不重绑 chatMessages（主对话写入
   目标不变），对话元信息携带 scope；
2. conversations_meta_payload 单点过滤：带 scope 的隐藏线程不出主清单，
   scoped_threads_payload 另面暴露（角标/浮窗重开）；
3. POST /api/conversations/thread 幂等：同 kind+cat+group_id+draft_id
   重复提交返回同一线程（label 等附加键不参与匹配），历史随响应装载；
4. 任务实例绑定线程后 add_chat_message 落线程、不落主对话；
5. scope 任务并发上限判定（adjust_task_concurrency）与总开关回落。
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.config import settings
from src.video_agent.state import conversation_ops
from src.video_agent.state.manager import StateManager

_SCOPE_A = {
    "kind": "adjust", "cat": "shotGroups",
    "group_id": "grp-1", "draft_id": "draft-1", "label": "分镜 1-2",
}


# ---------- 夹具 ----------

@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    del instance.get_chat_messages()[:]
    instance.save()
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def client(svc):
    import src.video_agent.web.routes.conversations as conv_mod
    from src.video_agent.exceptions import VideoAgentError
    from src.video_agent.web.app import video_agent_error_handler

    app = FastAPI()
    app.include_router(conv_mod.router, prefix="/api")
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


# ---------- 1. 线程实体：不设活跃、不重绑 ----------

def test_create_scoped_conversation_does_not_activate(svc):
    active_before = str(svc.state_dict.get("activeConversationId") or "")
    chat_ref_before = svc.state_dict["chatMessages"]
    conv = conversation_ops.create_scoped_conversation(svc, _SCOPE_A, title="微调 | 分镜 1-2")
    assert conv["scope"] == _SCOPE_A
    assert conv["title"] == "微调 | 分镜 1-2"
    # 不设活跃、不重绑 chatMessages（区别于 create_conversation）
    assert str(svc.state_dict.get("activeConversationId") or "") == active_before
    assert svc.state_dict["chatMessages"] is chat_ref_before


def test_scoped_thread_isolated_from_main_writes(svc):
    conv = conversation_ops.create_scoped_conversation(svc, _SCOPE_A)
    svc.add_chat_message("user", "主对话的消息")
    assert [m["text"] for m in svc.get_chat_messages()] == ["主对话的消息"]
    assert svc.get_conversation_messages(conv["id"]) == []


# ---------- 2. meta 单点过滤 ----------

def test_meta_filters_scoped_threads_list_payload(svc):
    conv = conversation_ops.create_scoped_conversation(svc, _SCOPE_A)
    meta = svc.conversations_meta_payload()
    assert conv["id"] not in [c["id"] for c in meta["conversations"]]
    threads = svc.scoped_threads_payload()["threads"]
    assert len(threads) == 1
    assert threads[0]["conversation_id"] == conv["id"]
    assert threads[0]["scope"] == _SCOPE_A


def test_list_endpoint_hides_scoped_threads(client, svc):
    conv = conversation_ops.create_scoped_conversation(svc, _SCOPE_A)
    payload = client.get("/api/conversations").json()
    assert conv["id"] not in [c["id"] for c in payload["conversations"]]
    assert payload.get("active_conversation_id")


# ---------- 3. 幂等取/建线程接口 ----------

def test_thread_endpoint_idempotent(client, svc):
    r1 = client.post("/api/conversations/thread", json={"scope": _SCOPE_A})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["conversation_id"]
    assert b1["messages"] == []
    # 同 kind+cat+group_id+draft_id 重复提交 → 同一线程（label 不参与匹配）
    scope2 = dict(_SCOPE_A, label="改名后的标签")
    r2 = client.post("/api/conversations/thread", json={"scope": scope2})
    assert r2.json()["conversation_id"] == b1["conversation_id"]
    # 主清单仍不见线程
    assert b1["conversation_id"] not in [
        c["id"] for c in client.get("/api/conversations").json()["conversations"]
    ]


def test_thread_endpoint_different_targets_distinct(client, svc):
    a = client.post("/api/conversations/thread", json={"scope": _SCOPE_A}).json()
    b = client.post("/api/conversations/thread", json={
        "scope": dict(_SCOPE_A, draft_id="draft-2")}).json()
    assert a["conversation_id"] != b["conversation_id"]


def test_thread_endpoint_returns_persisted_history(client, svc):
    b1 = client.post("/api/conversations/thread", json={"scope": _SCOPE_A}).json()
    svc.bound_conversation_id = b1["conversation_id"]
    svc.add_chat_message("user", "微调第一问")
    svc.add_chat_message("agent", "微调第一答")
    svc.bound_conversation_id = ""
    r2 = client.post("/api/conversations/thread", json={"scope": _SCOPE_A})
    assert [m["text"] for m in r2.json()["messages"]] == ["微调第一问", "微调第一答"]


# ---------- 4. 绑定线程写入定向 ----------

def test_bound_thread_writes_do_not_touch_main(svc):
    conv = conversation_ops.create_scoped_conversation(svc, _SCOPE_A)
    svc.bound_conversation_id = conv["id"]
    svc.add_chat_message("user", "线程消息")
    svc.add_chat_message("agent", "线程回复")
    svc.bound_conversation_id = ""
    assert [m["text"] for m in svc.get_conversation_messages(conv["id"])] \
        == ["线程消息", "线程回复"]
    assert svc.get_chat_messages() == []


# ---------- 5. 并发上限判定与总开关回落 ----------

def _stub_tm(running):
    import src.video_agent.web.agent_task_manager as atm_mod
    return lambda: SimpleNamespace(list_running=lambda project_id="": running)


def test_scope_concurrency_limit(svc, monkeypatch):
    import src.video_agent.web.chat_service as cs
    import src.video_agent.web.agent_task_manager as atm_mod

    scope_tasks = [{"task_id": f"agt-{i}", "status": "running",
                    "adjust_scope": _SCOPE_A} for i in range(4)]
    monkeypatch.setattr(atm_mod, "get_agent_task_manager", _stub_tm(scope_tasks))
    assert cs._scope_task_limit_exceeded("proj-x") is True

    monkeypatch.setattr(atm_mod, "get_agent_task_manager", _stub_tm(scope_tasks[:3]))
    assert cs._scope_task_limit_exceeded("proj-x") is False

    # 非 scope 运行中任务不计入
    plain = [{"task_id": "agt-p", "status": "running"} for _ in range(8)]
    monkeypatch.setattr(atm_mod, "get_agent_task_manager", _stub_tm(plain))
    assert cs._scope_task_limit_exceeded("proj-x") is False


def test_scope_concurrency_limit_configurable(svc, monkeypatch):
    import src.video_agent.web.chat_service as cs
    import src.video_agent.web.agent_task_manager as atm_mod

    one = [{"task_id": "agt-0", "status": "running", "adjust_scope": _SCOPE_A}]
    monkeypatch.setattr(atm_mod, "get_agent_task_manager", _stub_tm(one))
    object.__setattr__(settings, "adjust_task_concurrency", 1)
    try:
        assert cs._scope_task_limit_exceeded("proj-x") is True
    finally:
        object.__setattr__(settings, "adjust_task_concurrency", 4)


# ---------- 6. 批 S2：scope 任务全链路写入与 history 服务端装载 ----------

def test_scope_task_full_chain_main_chat_stays_empty(svc):
    """scope 任务全链路（任务绑定写入模拟 _run_agent_task 路径）跑完后：
    消息全部落线程，主对话 get_chat_messages() 为空。"""
    conv = conversation_ops.create_scoped_conversation(svc, _SCOPE_A)
    # worker 绑定线程（_run_agent_task: svc.bound_conversation_id = conversation_id）
    svc.bound_conversation_id = conv["id"]
    svc.add_chat_message("user", "把这一卡改成夜景")
    svc.add_chat_message("agent", "已按夜景调整目标分组提示词")
    svc.bound_conversation_id = ""
    # 主对话零污染（写入定向到线程）
    assert svc.get_chat_messages() == []
    # 线程内历史完整，且主清单仍不见线程（隐藏载体）
    assert [m["text"] for m in svc.get_conversation_messages(conv["id"])] \
        == ["把这一卡改成夜景", "已按夜景调整目标分组提示词"]
    assert conv["id"] not in [c["id"] for c in svc.conversations_meta_payload()["conversations"]]


def test_scope_history_server_side_loading(svc):
    """history 服务端装载（_scope_history_from_thread）：线程落盘消息转
    role/content，sender==user → user，其余 → assistant，空白条目剔除。"""
    import src.video_agent.web.chat_service as cs
    conv = conversation_ops.create_scoped_conversation(svc, _SCOPE_A)
    svc.bound_conversation_id = conv["id"]
    svc.add_chat_message("user", "第一轮问")
    svc.add_chat_message("agent", "第一轮答")
    svc.add_chat_message("user", "   ")  # 空白条目不进 history
    svc.bound_conversation_id = ""
    history = cs._scope_history_from_thread(svc, conv["id"])
    assert history == [
        {"role": "user", "content": "第一轮问"},
        {"role": "assistant", "content": "第一轮答"},
    ]
    # 空线程/不存在线程返回空窗口（不抛错，回落重建语义）
    assert cs._scope_history_from_thread(svc, "conv-ghost") == []


def test_active_adjust_scope_switch(svc):
    import src.video_agent.web.chat_service as cs
    from src.video_agent.web.routes.agent import ChatRequest

    body = ChatRequest(message="x", adjust_scope=_SCOPE_A)
    assert cs._active_adjust_scope(body) == _SCOPE_A
    # 未携带 / 空 / 非法形态回落旧行为
    assert cs._active_adjust_scope(ChatRequest(message="x")) is None
    assert cs._active_adjust_scope(ChatRequest(message="x", adjust_scope={})) is None
    # 总开关关闭 → 忽略回落旧行为（一键回滚）
    object.__setattr__(settings, "adjust_subdialog_enabled", False)
    try:
        assert cs._active_adjust_scope(body) is None
    finally:
        object.__setattr__(settings, "adjust_subdialog_enabled", True)
