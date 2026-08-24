# -*- coding: utf-8 -*-
"""分叉点快照（任务 #16）：POST /api/conversations/snapshot 的 up_to_index。

钉死契约：
- 不提供 up_to_index → 全量快照（既有调用零行为变化）；
- up_to_index=0/末位 → 截取 messages[:up_to_index+1]（含该条）；
- 越界/为负 → 400 结构化错误（ErrorPayload：error_code/code/kind/detail）；
- 派生分支接口不变：分支装载快照内的全部消息（截断快照 → 分支只含截断后消息）；
- E-2：分支响应只含对话元信息，分支消息经 GET /conversations/{id}/messages 读回。
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

    # 快照文件落测试目录，不污染生产 workspace/snapshots
    monkeypatch.setattr(snapshots_mod, "WORKSPACE_DIR", tmp_path / "snaps")
    app = FastAPI()
    # 分支消息经按会话拉消息接口读回（E-2），需同时注册 conversations 路由
    app.include_router(conv_mod.router, prefix="/api")
    app.include_router(snapshots_mod.router, prefix="/api")
    # P9：standalone 应用需注册统一转译 handler（与生产 app.py 同源）
    from src.video_agent.exceptions import VideoAgentError
    from src.video_agent.web.app import video_agent_error_handler
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


def _seed_messages(svc, n=4):
    for i in range(n):
        sender = "user" if i % 2 == 0 else "agent"
        svc.add_chat_message(sender, f"消息{i}")
    return svc.get_chat_messages()


def _snapshot_messages(client, snap_id):
    r = client.get(f"/api/conversations/snapshots/{snap_id}")
    assert r.status_code == 200
    return r.json()["messages"]


# ---------- 边界：0 / 末位 / 越界 / 负数 / 缺省 ----------

def test_snapshot_without_index_keeps_full_messages(client, svc):
    """不传 up_to_index（空 body）→ 全量快照，兼容既有调用。"""
    _seed_messages(svc, 4)
    r = client.post("/api/conversations/snapshot")
    assert r.status_code == 200
    msgs = _snapshot_messages(client, r.json()["snap_id"])
    assert [m["text"] for m in msgs] == ["消息0", "消息1", "消息2", "消息3"]


def test_snapshot_up_to_index_zero_keeps_first_only(client, svc):
    _seed_messages(svc, 4)
    r = client.post("/api/conversations/snapshot", json={"up_to_index": 0})
    assert r.status_code == 200
    msgs = _snapshot_messages(client, r.json()["snap_id"])
    assert [m["text"] for m in msgs] == ["消息0"]


def test_snapshot_up_to_index_last_equals_full(client, svc):
    _seed_messages(svc, 4)
    r = client.post("/api/conversations/snapshot", json={"up_to_index": 3})
    assert r.status_code == 200
    msgs = _snapshot_messages(client, r.json()["snap_id"])
    assert len(msgs) == 4


def test_snapshot_up_to_index_middle_truncates_inclusive(client, svc):
    """截断含该条：up_to_index=2 → 前 3 条。"""
    _seed_messages(svc, 4)
    r = client.post("/api/conversations/snapshot", json={"up_to_index": 2})
    assert r.status_code == 200
    msgs = _snapshot_messages(client, r.json()["snap_id"])
    assert [m["text"] for m in msgs] == ["消息0", "消息1", "消息2"]


def test_snapshot_up_to_index_out_of_range_400_structured(client, svc):
    _seed_messages(svc, 2)
    r = client.post("/api/conversations/snapshot", json={"up_to_index": 2})
    assert r.status_code == 400
    body = r.json()
    assert body["error_code"] == "SNAPSHOT_INDEX_OUT_OF_RANGE"
    assert body["code"].startswith("err.")
    assert body["kind"] == "unknown"
    assert body["detail"]  # 人话消息非空


def test_snapshot_up_to_index_negative_400(client, svc):
    _seed_messages(svc, 2)
    r = client.post("/api/conversations/snapshot", json={"up_to_index": -1})
    assert r.status_code == 400
    assert r.json()["error_code"] == "SNAPSHOT_INDEX_OUT_OF_RANGE"


def test_snapshot_up_to_index_on_empty_conversation_400(client, svc):
    """空对话时任何索引都越界（含 0）。"""
    r = client.post("/api/conversations/snapshot", json={"up_to_index": 0})
    assert r.status_code == 400


# ---------- 派生分支接口不变（E-2：响应只含元信息，消息经 messages 接口读回） ----------

def test_branch_loads_all_messages_of_truncated_snapshot(client, svc):
    """分支 = 装载快照全部消息：截断快照派生的分支只含截断后消息，
    分支接口本身行为不变。"""
    _seed_messages(svc, 4)
    r = client.post("/api/conversations/snapshot", json={"up_to_index": 1})
    snap_id = r.json()["snap_id"]
    rb = client.post(f"/api/conversations/snapshots/{snap_id}/branch", json={"title": "分支"})
    assert rb.status_code == 200
    payload = rb.json()
    active_id = payload["active_conversation_id"]
    # 响应只含元信息（E-2）
    assert all("messages" not in c for c in payload["conversations"])
    # 分支消息经按会话拉消息接口读回：只含截断后消息
    msgs = client.get(f"/api/conversations/{active_id}/messages").json()["messages"]
    assert [m["text"] for m in msgs] == ["消息0", "消息1"]
    # 原对话不受分支影响（非破坏性）：消息仍为全量 4 条
    origin_id = next(
        c["id"] for c in payload["conversations"] if c["id"] != active_id
    )
    origin_msgs = client.get(f"/api/conversations/{origin_id}/messages").json()["messages"]
    assert len(origin_msgs) == 4
