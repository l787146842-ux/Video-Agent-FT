# -*- coding: utf-8 -*-
"""消息单一来源（任务 #8 E-2）：conversations HTTP 响应裁剪 + 按会话拉消息。

钉死契约：
1. GET/POST/DELETE/activate /api/conversations 响应只含元信息
   （id/title，无 messages 键），消息副本不再随响应下发；
2. GET /api/conversations/{id}/messages 返回该会话消息（切会话装载唯一通道），
   会话不存在 404；
3. get_full_snapshot（刷新/SSE done 快照源）中 conversations 只留元信息，
   活跃对话消息仍由顶层 chatMessages 携带（刷新/重连读回路径不断）；
4. 快照分支响应同样只含元信息，分支消息经 messages 接口装载。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    # 清空 demo 预置消息，保证用例从空对话起步
    del instance.get_chat_messages()[:]
    instance.save()
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def client(svc, tmp_path, monkeypatch):
    import src.video_agent.web.routes.conversations as conv_mod
    import src.video_agent.web.routes.snapshots as snapshots_mod

    monkeypatch.setattr(snapshots_mod, "WORKSPACE_DIR", tmp_path / "snaps")
    app = FastAPI()
    # 注册顺序与生产 app.py 一致（conversations 先于 snapshots）
    app.include_router(conv_mod.router, prefix="/api")
    app.include_router(snapshots_mod.router, prefix="/api")
    # P9：standalone 应用需注册统一转译 handler（与生产 app.py 同源）
    from src.video_agent.exceptions import VideoAgentError
    from src.video_agent.web.app import video_agent_error_handler
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


def _assert_meta_only(payload):
    """响应契约：对话项只含元信息，绝无消息副本"""
    assert "conversations" in payload
    assert payload.get("active_conversation_id")
    for c in payload["conversations"]:
        assert "messages" not in c, "E-2：conversations 响应不得携带消息副本"
        assert c.get("id")
        assert "title" in c


def _new_conversation(client, title):
    r = client.post("/api/conversations", json={"title": title})
    assert r.status_code == 200
    return r.json()


# ---------- 1. 列表/新建/切换/关闭响应一律只含元信息 ----------

def test_list_conversations_meta_only(client, svc):
    svc.add_chat_message("user", "你好")
    _new_conversation(client, "会话2")
    payload = client.get("/api/conversations").json()
    _assert_meta_only(payload)
    assert len(payload["conversations"]) == 2


def test_create_activate_delete_responses_meta_only(client, svc):
    payload = _new_conversation(client, "会话2")
    _assert_meta_only(payload)
    other_id = next(
        c["id"] for c in payload["conversations"]
        if c["id"] != payload["active_conversation_id"]
    )
    r = client.post(f"/api/conversations/{other_id}/activate")
    assert r.status_code == 200
    _assert_meta_only(r.json())
    assert r.json()["active_conversation_id"] == other_id
    r = client.delete(f"/api/conversations/{other_id}")
    assert r.status_code == 200
    _assert_meta_only(r.json())


def test_activate_unknown_conversation_404(client):
    assert client.post("/api/conversations/ghost/activate").status_code == 404


# ---------- 2. 按会话拉消息（切会话装载唯一通道） ----------

def test_get_conversation_messages_returns_history(client, svc):
    svc.add_chat_message("user", "第一问")
    svc.add_chat_message("agent", "第一答")
    active_id = svc.conversations_meta_payload()["active_conversation_id"]
    r = client.get(f"/api/conversations/{active_id}/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == active_id
    assert [m["text"] for m in body["messages"]] == ["第一问", "第一答"]


def test_get_conversation_messages_switch_roundtrip(client, svc):
    """切会话后完整历史仍可从 messages 接口读回（持久化读回路径不断）。"""
    svc.add_chat_message("user", "会话1的消息")
    payload = _new_conversation(client, "会话2")
    origin_id = next(
        c["id"] for c in payload["conversations"]
        if c["id"] != payload["active_conversation_id"]
    )
    # 新对话为空
    assert client.get(
        f"/api/conversations/{payload['active_conversation_id']}/messages"
    ).json()["messages"] == []
    # 切回原对话：历史完整读回
    client.post(f"/api/conversations/{origin_id}/activate")
    msgs = client.get(f"/api/conversations/{origin_id}/messages").json()["messages"]
    assert [m["text"] for m in msgs] == ["会话1的消息"]


def test_get_conversation_messages_unknown_404(client):
    assert client.get("/api/conversations/ghost/messages").status_code == 404


# ---------- 3. 状态快照（刷新/SSE done 源）对话去副本 ----------

def test_full_snapshot_trims_conversation_messages_but_keeps_chat_messages(svc):
    svc.add_chat_message("user", "活跃消息")
    svc.create_conversation("会话2")  # 活跃切到新对话
    snap = svc.get_full_snapshot()
    for c in snap.get("conversations") or []:
        assert "messages" not in c, "E-2：快照 conversations 不得携带消息副本"
    # 活跃对话消息仍由顶层 chatMessages 承载（刷新/重连读回不变）
    assert snap["chatMessages"] == []  # 新活跃对话为空
    svc.switch_conversation(snap["conversations"][0]["id"])
    snap2 = svc.get_full_snapshot()
    assert [m["text"] for m in snap2["chatMessages"]] == ["活跃消息"]
    # 裁剪不得回写污染内部状态（消息仍在原对话内）
    assert any(
        [m["text"] for m in (c.get("messages") or [])] == ["活跃消息"]
        for c in svc.state_dict["conversations"]
    )


# ---------- 4. 快照分支响应同样只含元信息 ----------

def test_branch_response_meta_only_messages_via_endpoint(client, svc):
    for i in range(2):
        svc.add_chat_message("user" if i % 2 == 0 else "agent", f"消息{i}")
    r = client.post("/api/conversations/snapshot")
    snap_id = r.json()["snap_id"]
    rb = client.post(f"/api/conversations/snapshots/{snap_id}/branch", json={"title": "分支"})
    assert rb.status_code == 200
    payload = rb.json()
    _assert_meta_only(payload)
    # 分支消息经按会话拉消息接口装载（单一来源）
    msgs = client.get(
        f"/api/conversations/{payload['active_conversation_id']}/messages"
    ).json()["messages"]
    assert [m["text"] for m in msgs] == ["消息0", "消息1"]
