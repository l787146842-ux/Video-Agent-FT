# -*- coding: utf-8 -*-
"""批 6-1 多会话并行：任务-会话定向契约钉死。

钉死契约：
1. 聊天写入定向单点（conversation_ops.target_chat_messages）：
   绑定会话优先、无绑定回落活跃对话；绑定会话不存在静默回落不阻断；
2. 任务级实例绑定（bound_conversation_id）：add_chat_message /
   attach_snapshot_to_last_agent_message 定向到绑定对话，活跃对话不受影响；
   两实例各绑各的并行写互不串话；
3. start_agent_task 定向：请求显式 project_id/conversation_id 优先，
   空参回落全局活跃项目/活跃对话（旧前端零破坏）；
4. 截断重答对话级：显式对话定向截断/起任务；忙碌判定仅目标对话口径，
   别的对话任务在跑不阻断；目标对话不存在 → 400；
5. 删忙对话保护：绑定任务运行中的对话拒删（400）。
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state import conversation_ops
from src.video_agent.state.manager import StateManager


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
def two_convs(svc):
    """活跃对话 + 第二个对话；返回第二个对话 id。"""
    payload = svc.create_conversation("会话2")
    # create_conversation 会把新对话设为活跃；切回首个保持活跃语义稳定
    first_id = payload["conversations"][0]["id"]
    svc.switch_conversation(first_id)
    return payload["active_conversation_id"] if payload["active_conversation_id"] != first_id \
        else next(c["id"] for c in payload["conversations"] if c["id"] != first_id)


# ---------- 1. 写入定向单点 ----------

def test_target_falls_back_to_active_when_unbound(svc):
    msgs = conversation_ops.target_chat_messages(svc)
    assert msgs is svc.state_dict["chatMessages"]


def test_target_prefers_bound_conversation(svc, two_convs):
    svc.bound_conversation_id = two_convs
    msgs = conversation_ops.target_chat_messages(svc)
    bound_ref = next(c for c in svc.state_dict["conversations"]
                     if c["id"] == two_convs)["messages"]
    assert msgs is bound_ref
    assert msgs is not svc.state_dict["chatMessages"]


def test_target_missing_bound_falls_back_silently(svc, two_convs):
    svc.bound_conversation_id = "conv-nonexistent"
    msgs = conversation_ops.target_chat_messages(svc)
    assert msgs is svc.state_dict["chatMessages"]


# ---------- 2. 绑定写入与并行不串话 ----------

def test_add_chat_message_goes_to_bound_conversation(svc, two_convs):
    svc.bound_conversation_id = two_convs
    svc.add_chat_message("agent", "绑定对话的消息")
    bound_texts = [m["text"] for m in svc.get_conversation_messages(two_convs)]
    assert bound_texts == ["绑定对话的消息"]
    assert svc.get_chat_messages() == []  # 活跃对话不受影响


def test_snapshot_attach_targets_bound_conversation(svc, two_convs):
    svc.bound_conversation_id = two_convs
    svc.add_chat_message("agent", "绑定对话的回复")
    snap_id = svc.attach_snapshot_to_last_agent_message(label="t")
    bound = svc.get_conversation_messages(two_convs)
    assert bound[-1].get("snapshotId") == snap_id
    assert svc.get_chat_messages() == []


def test_two_instances_parallel_no_cross_write(tmp_path):
    """两个任务级实例各绑各的对话并行写：消息各归各，互不串话（内存隔离契约）。
    跨实例落盘的版本闸语义（旧写放弃/后写生效）由既有版本闸测试覆盖。"""
    ws = str(tmp_path / "ws")
    base = StateManager(ws)
    del base.get_chat_messages()[:]
    payload = base.create_conversation("会话2")
    conv2 = payload["active_conversation_id"]
    # 切回首个对话：无绑定实例（b）的写入目标 = 活跃对话 = 首对话，与 conv2 隔离
    first = next(c["id"] for c in payload["conversations"] if c["id"] != conv2)
    base.switch_conversation(first)
    base.save()

    a = StateManager(ws)
    b = StateManager(ws)
    a.bound_conversation_id = conv2
    b.bound_conversation_id = ""  # 活跃对话
    a.add_chat_message("agent", "A 的消息")
    b.add_chat_message("agent", "B 的消息")

    assert [m["text"] for m in a.get_conversation_messages(conv2)] == ["A 的消息"]
    assert [m["text"] for m in a.get_chat_messages()] == []
    assert [m["text"] for m in b.get_chat_messages()] == ["B 的消息"]
    assert [m["text"] for m in b.get_conversation_messages(conv2)] == []


# ---------- 3. start_agent_task 定向 ----------

class _StubTM:
    def __init__(self):
        self.created = []

    def list_running(self, project_id=""):
        return []

    def create(self, project_id, worker_factory, task_id="", model="", conversation_id=""):
        record = {
            "task_id": task_id or "agt-stub",
            "project_id": project_id,
            "conversation_id": conversation_id,
            "status": "running",
        }
        self.created.append(record)
        return record


def test_start_agent_task_explicit_target(svc, two_convs, monkeypatch):
    import src.video_agent.web.chat_service as cs
    import src.video_agent.web.agent_task_manager as atm_mod

    stub = _StubTM()
    monkeypatch.setattr(atm_mod, "get_agent_task_manager", lambda: stub)
    from src.video_agent.web.routes.agent import ChatRequest

    result = cs.start_agent_task(ChatRequest(
        message="x", project_id="proj-other", conversation_id=two_convs))
    assert result["project_id"] == "proj-other"
    assert stub.created[0]["conversation_id"] == two_convs
    assert stub.created[0]["project_id"] == "proj-other"


def test_start_agent_task_empty_falls_back_to_active(svc, two_convs, monkeypatch):
    import src.video_agent.web.chat_service as cs
    import src.video_agent.web.agent_task_manager as atm_mod

    stub = _StubTM()
    monkeypatch.setattr(atm_mod, "get_agent_task_manager", lambda: stub)
    from src.video_agent.web.routes.agent import ChatRequest

    result = cs.start_agent_task(ChatRequest(message="x"))
    assert result["project_id"] == svc.active_project_id
    active_conv = str(svc.state_dict.get("activeConversationId") or "")
    assert stub.created[0]["conversation_id"] == active_conv


def test_run_agent_task_binds_conversation(svc, two_convs, monkeypatch):
    """worker 启动后任务专属实例的 bound_conversation_id = 提交时的对话。"""
    import asyncio
    import src.video_agent.web.chat_service as cs
    import src.video_agent.web.agent_task_manager as atm_mod

    monkeypatch.setattr(atm_mod, "get_agent_task_manager", lambda: SimpleNamespace(
        emit=lambda *a, **k: None, drain_pending_guidance=lambda *a: [],
        clear_pending_guidance=lambda *a: None, get=lambda *a: {},
    ))

    seen = {}

    async def fake_impl(body, svc_, emit, pending_injector=None, stop_scope=""):
        seen["bound"] = svc_.bound_conversation_id

    monkeypatch.setattr(cs, "_stream_worker_impl", fake_impl)
    from src.video_agent.web.routes.agent import ChatRequest

    asyncio.run(cs._run_agent_task(
        ChatRequest(message="x"), svc.active_project_id, "agt-t",
        str(svc._workspace_dir), two_convs))
    assert seen["bound"] == two_convs


# ---------- 4. 截断重答对话级定向 ----------

@pytest.fixture
def chat_client(svc, monkeypatch):
    import src.video_agent.web.routes.chat as chat_mod
    import src.video_agent.web.agent_task_manager as atm_mod

    monkeypatch.setattr(
        atm_mod, "get_agent_task_manager",
        lambda: SimpleNamespace(list_running=lambda project_id="": []),
    )
    monkeypatch.setattr(chat_mod, "_resolve_chat_target", lambda: ("prov-x", "model-x"))
    import src.video_agent.core.provider_config as pc
    monkeypatch.setattr(
        pc, "load_merged_providers",
        lambda: [{"id": "prov-x", "enabled": True, "chat_models": ["model-x"]}],
    )
    app = FastAPI()
    app.include_router(chat_mod.router, prefix="/api")
    return TestClient(app)


def test_truncate_resend_targets_explicit_conversation(chat_client, svc, two_convs, monkeypatch):
    import src.video_agent.web.chat_service as cs

    captured = {}

    def fake_start(body):
        captured["body"] = body
        return {"task_id": "agt-t", "project_id": body.project_id}

    monkeypatch.setattr(cs, "start_agent_task", fake_start)

    # 活跃对话与目标对话各有历史
    svc.add_chat_message("user", "活跃对话的问题")
    svc.add_chat_message("agent", "活跃对话的回答")
    svc.bound_conversation_id = two_convs
    svc.add_chat_message("user", "目标对话的问题")
    svc.add_chat_message("agent", "目标对话的回答")
    svc.bound_conversation_id = ""

    r = chat_client.post("/api/chat/truncate-resend",
                         json={"text": "改过的问题", "conversation_id": two_convs})
    assert r.status_code == 200, r.text
    # 目标对话被截断替换；活跃对话原样
    assert [m["text"] for m in svc.get_conversation_messages(two_convs)] == ["改过的问题"]
    assert [m["text"] for m in svc.get_chat_messages()] == ["活跃对话的问题", "活跃对话的回答"]
    # 起的任务携带定向
    assert captured["body"].conversation_id == two_convs
    assert captured["body"].project_id == svc.active_project_id


def test_truncate_resend_unknown_conversation_400(chat_client, svc):
    svc.add_chat_message("user", "问题")
    r = chat_client.post("/api/chat/truncate-resend",
                         json={"conversation_id": "conv-nope"})
    assert r.status_code == 400
    assert [m["text"] for m in svc.get_chat_messages()] == ["问题"]


def test_truncate_resend_busy_only_same_conversation(chat_client, svc, two_convs, monkeypatch):
    """别的对话有任务在跑 → 本对话截断重答放行（多会话并行）；
    同对话有任务在跑 → 409。"""
    import src.video_agent.web.agent_task_manager as atm_mod
    import src.video_agent.web.chat_service as cs

    # 放行路径会真正起任务：拦截为桁（本用例只钉忙判定口径）
    monkeypatch.setattr(cs, "start_agent_task",
                        lambda body: {"task_id": "agt-t", "project_id": body.project_id})

    svc.add_chat_message("user", "问题")

    monkeypatch.setattr(atm_mod, "get_agent_task_manager", lambda: SimpleNamespace(
        list_running=lambda project_id="": [
            {"task_id": "agt-1", "conversation_id": two_convs, "status": "running"},
        ]))
    r = chat_client.post("/api/chat/truncate-resend", json={})
    assert r.status_code == 200  # 忙的是另一个对话，不阻断

    active_conv = str(svc.state_dict.get("activeConversationId") or "")
    monkeypatch.setattr(atm_mod, "get_agent_task_manager", lambda: SimpleNamespace(
        list_running=lambda project_id="": [
            {"task_id": "agt-2", "conversation_id": active_conv, "status": "running"},
        ]))
    r = chat_client.post("/api/chat/truncate-resend", json={})
    assert r.status_code == 409
    assert r.json()["error_code"] == "AGENT_BUSY"


# ---------- 5. 删忙对话保护 ----------

def test_delete_busy_conversation_400(svc, two_convs, tmp_path, monkeypatch):
    import src.video_agent.web.routes.conversations as conv_mod
    from src.video_agent.exceptions import VideoAgentError
    from src.video_agent.web.app import video_agent_error_handler

    # 模块级导入：直接 patch 路由模块内已固化的引用名（对齐承重壳纪律）
    monkeypatch.setattr(conv_mod, "get_agent_task_manager", lambda: SimpleNamespace(
        list_running=lambda project_id="": [
            {"task_id": "agt-1", "conversation_id": two_convs, "status": "running"},
        ]))
    app = FastAPI()
    app.include_router(conv_mod.router, prefix="/api")
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    client = TestClient(app)

    r = client.delete(f"/api/conversations/{two_convs}")
    assert r.status_code == 400
    # 无任务绑定的对话可正常关闭
    other = next(c["id"] for c in svc.conversations_meta_payload()["conversations"]
                 if c["id"] != two_convs)
    r = client.delete(f"/api/conversations/{other}")
    assert r.status_code == 200
