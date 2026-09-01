# -*- coding: utf-8 -*-
"""二期子对话批 1：对象删除级联清线程。

钉死契约：
1. cleanup_scoped_threads_for_removed 只硬删 scope.draft_id 命中的隐藏线程，
   主对话与未命中线程不动；
2. 分组删除先展开全部草稿 id 再级联（delete_group 返回被删草稿 id 列表）；
3. 整板 PUT 写面：新旧草稿 id diff 触发级联（前端删元素主路径）；
4. 撤销原子恢复：删除 + 级联同帧，Ctrl+Z 后元素、线程与历史消息一起回来；
5. 在途任务先掐：级联前对绑定被删线程的运行中任务走既有停止通道
   （request_stop + tm.stop，经调用方注入），防 target_chat_messages
   静默回落污染主对话；掐停不可得不阻断级联；tools 层经 core/ports 端口取实现。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state import conversation_ops, storyboard_ops as ops
from src.video_agent.state.manager import StateManager


def _scope(draft_id: str, group_id: str = "grp-1") -> dict:
    return {
        "kind": "adjust", "cat": "shotGroups",
        "group_id": group_id, "draft_id": draft_id, "label": f"分镜 {draft_id}",
    }


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
    import src.video_agent.web.routes.project as proj_mod
    from src.video_agent.exceptions import VideoAgentError
    from src.video_agent.web.app import video_agent_error_handler

    app = FastAPI()
    app.include_router(proj_mod.router, prefix="/api")
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


def _thread_ids(svc) -> list:
    """当前全部隐藏线程对话 id（scope 对话）"""
    return [
        c.get("id") for c in (svc._raw_state.get("conversations") or [])
        if isinstance(c, dict) and isinstance(c.get("scope"), dict)
    ]


# ---------- 1. 级联只删命中线程 ----------

def test_cleanup_removes_only_matching_scoped_threads(svc):
    t1 = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    t2 = conversation_ops.create_scoped_conversation(svc, _scope("draft-2"))
    main_ids = [
        c.get("id") for c in svc._raw_state["conversations"]
        if not isinstance(c.get("scope"), dict)
    ]

    removed = conversation_ops.cleanup_scoped_threads_for_removed(svc, {"draft-1"})

    assert removed == [t1["id"]]
    assert _thread_ids(svc) == [t2["id"]]
    # 主对话与未命中线程不受影响
    cur = svc._raw_state["conversations"]
    assert all(any(c.get("id") == mid for c in cur) for mid in main_ids)


def test_cleanup_noop_when_no_thread_hits(svc):
    conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    before = list(svc._raw_state["conversations"])
    assert conversation_ops.cleanup_scoped_threads_for_removed(svc, {"no-such-draft"}) == []
    assert svc._raw_state["conversations"] == before


# ---------- 2. 分组删除展开全部草稿 ----------

def test_delete_group_expands_drafts_and_cascades(svc):
    svc.state_dict["shots"] = [{
        "id": "grp-1", "title": "G1",
        "drafts": [{"id": "draft-1", "label": "a"}, {"id": "draft-2", "label": "b"}],
    }]
    conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    conversation_ops.create_scoped_conversation(svc, _scope("draft-2"))

    removed_draft_ids = ops.delete_group(svc.state_dict, "grp-1", "shot")
    assert sorted(removed_draft_ids) == ["draft-1", "draft-2"]
    removed = conversation_ops.cleanup_scoped_threads_for_removed(svc, removed_draft_ids)

    assert len(removed) == 2
    assert _thread_ids(svc) == []


# ---------- 3. 整板 PUT 写面 diff 级联 ----------

def test_put_state_diff_cascades_removed_drafts(svc, client):
    svc.state_dict["shots"] = [{
        "id": "grp-1", "title": "G1",
        "drafts": [{"id": "draft-1", "label": "a"}, {"id": "draft-2", "label": "b"}],
    }]
    conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    conversation_ops.create_scoped_conversation(svc, _scope("draft-2"))

    # 前端删 draft-1：整板 PUT 只留 draft-2
    resp = client.put("/api/project/state", json={
        "shots": [{"id": "grp-1", "title": "G1", "drafts": [{"id": "draft-2", "label": "b"}]}],
    })
    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert _thread_ids(svc) != []  # draft-2 线程仍在
    payload = conversation_ops.scoped_threads_payload(svc)
    assert [t["scope"]["draft_id"] for t in payload["threads"]] == ["draft-2"]


def test_put_state_without_lists_does_not_cascade(svc, client):
    """未提交的列表不参与 diff（部分保存不误删线程）"""
    conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    resp = client.put("/api/project/state", json={"chatMessages": []})
    assert resp.status_code == 200
    assert len(_thread_ids(svc)) == 1


# ---------- 4. 撤销原子恢复 ----------

def test_undo_restores_element_thread_and_messages_atomically(svc):
    svc.state_dict["shots"] = [{
        "id": "grp-1", "title": "G1",
        "drafts": [{"id": "draft-1", "label": "a"}],
    }]
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    thread.setdefault("messages", []).append({"role": "user", "text": "改亮一点"})

    svc.push_undo()
    removed = ops.delete_draft(svc.state_dict, "draft-1", "shot")
    conversation_ops.cleanup_scoped_threads_for_removed(svc, removed)
    assert _thread_ids(svc) == []
    assert svc.state_dict["shots"][0]["drafts"] == []

    assert svc.undo() is True
    # 元素、线程、线程历史一起原子恢复（快照栈含 conversations 全态）
    assert [d["id"] for d in svc.state_dict["shots"][0]["drafts"]] == ["draft-1"]
    assert _thread_ids(svc) == [thread["id"]]
    assert svc.get_conversation_messages(thread["id"]) == [{"role": "user", "text": "改亮一点"}]


# ---------- 5. 在途任务先掐再删线程 ----------

class _FakeTaskManager:
    """只登记停止调用的任务台账桩（真台账需要事件循环，单测口径隔离）"""

    def __init__(self, running):
        self._running = running
        self.stopped = []

    def list_running(self, project_id: str = ""):
        return list(self._running)

    def stop(self, task_id: str) -> bool:
        self.stopped.append(task_id)
        return True


def test_inflight_task_stopped_before_thread_removed(svc, monkeypatch):
    import src.video_agent.web.agent_task_manager as atm

    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    fake = _FakeTaskManager([
        {"task_id": "t-hit", "conversation_id": thread["id"]},
        {"task_id": "t-other", "conversation_id": "conv-elsewhere"},
    ])
    stopped_requests = []
    monkeypatch.setattr(atm, "get_agent_task_manager", lambda: fake)
    monkeypatch.setattr(
        atm, "request_stop", lambda scope="chat": stopped_requests.append(scope) or 1)

    # 写面注入口径：级联前把掐停实现注入，命中线程的在途任务先掐再删
    removed = conversation_ops.cleanup_scoped_threads_for_removed(
        svc, {"draft-1"}, stop_tasks=atm.stop_tasks_bound_to_conversations)

    assert stopped_requests == ["t-hit"]  # 只有命中被删线程的任务被掐（既有停止通道两步）
    assert fake.stopped == ["t-hit"]
    assert removed == [thread["id"]]
    assert _thread_ids(svc) == []


def test_cascade_survives_stop_tasks_unavailable(svc):
    """任务台账不可用时尽力而为：掐停异常不阻断线程删除级联"""
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))

    def _boom(ids):
        raise RuntimeError("任务台账不可用")

    removed = conversation_ops.cleanup_scoped_threads_for_removed(
        svc, {"draft-1"}, stop_tasks=_boom)
    assert removed == [thread["id"]]
    assert _thread_ids(svc) == []


def test_task_stop_port_wired_to_agent_task_manager(svc, monkeypatch):
    """tools 层（禁 import web）经 core/ports 端口取掐停实现：
    端口装配后转发到 stop_tasks_bound_to_conversations（D-01 端口先例）"""
    from src.video_agent.core import ports
    from src.video_agent.web import agent_task_manager as atm
    from src.video_agent.web.port_wiring import install_core_ports

    install_core_ports()
    calls = []
    monkeypatch.setattr(
        atm, "stop_tasks_bound_to_conversations",
        lambda ids: calls.append(list(ids)) or ["t-x"])

    got = ports.task_stop_port().stop_bound_tasks(["conv-a"])
    assert got == ["t-x"]
    assert calls == [["conv-a"]]
