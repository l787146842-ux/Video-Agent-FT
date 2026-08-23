"""任务式传输回归（D 批 / 7777 停止与刷新恢复）：

- 任务 worker 使用任务级 StateManager，切项目/刷新不串写；
- 提交即返回 task_id，worker 后台运行；
- 订阅先回放 replay，再增量推送，终态必有 done/error；
- 停止按钮真正取消后台任务。
"""

import asyncio
from types import SimpleNamespace

import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.web.agent_task_manager import get_agent_task_manager


def _mock_body(**overrides):
    base = dict(
        request_id="req-test",
        message="你好",
        attachments=[],
        provider="mock",
        model="mock-x",
        context_mode="studio",
        selected_draft_id="",
        selected_type="",
        skill_slug="",
        skill_name="",
        images=[],
        videos=[],
        content_parts=None,
        doc_blocks=[],
        skill_blocks=[],
        asset_mode="bound",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_task_bound_state_isolation(tmp_path):
    """任务级 StateManager：context 内 get_instance 命中任务实例，释放后恢复。"""
    ws = str(tmp_path / "ws")
    global_svc = StateManager(ws)
    pid = global_svc.active_project_id

    bound, token = StateManager.create_task_bound(pid, ws)
    try:
        assert bound is not global_svc
        assert StateManager.get_instance() is bound
        assert bound.active_project_id == pid
    finally:
        StateManager.release_task_bound(token)
    assert StateManager.get_instance() is not bound


@pytest.mark.asyncio
async def test_agent_task_mock_runs_to_done(tmp_path, monkeypatch):
    """提交 mock 任务 → worker 后台跑完 → 状态 done，订阅收到 replay+done。"""
    ws = str(tmp_path / "ws")
    submission_svc = StateManager(ws)
    monkeypatch.setattr(
        StateManager, "get_instance",
        classmethod(lambda cls: submission_svc),
    )

    from src.video_agent.web.chat_service import start_agent_task

    result = start_agent_task(_mock_body())
    task_id = result["task_id"]
    assert result["project_id"] == submission_svc.active_project_id

    tm = get_agent_task_manager()
    for _ in range(200):
        rec = tm.get(task_id)
        if rec and rec.get("status") in ("done", "error", "cancelled"):
            break
        await asyncio.sleep(0.02)
    rec = tm.get(task_id)
    assert rec is not None
    assert rec["status"] == "done", f"task status={rec['status']} error={rec.get('error')}"
    assert rec["done_payload"] is not None

    q = tm.subscribe(task_id)
    assert q is not None
    first = await asyncio.wait_for(q.get(), timeout=2)
    assert first["type"] == "replay"
    assert first["payload"]["status"] == "done"
    tm.unsubscribe(task_id, q)


@pytest.mark.asyncio
async def test_agent_task_stop_cancels_worker(tmp_path, monkeypatch):
    """停止按钮：manager.stop 取消后台任务，状态转 cancelled。"""
    ws = str(tmp_path / "ws")
    submission_svc = StateManager(ws)
    monkeypatch.setattr(
        StateManager, "get_instance",
        classmethod(lambda cls: submission_svc),
    )

    tm = get_agent_task_manager()

    async def hang():
        await asyncio.sleep(30)

    record = tm.create(submission_svc.active_project_id, hang, model="m")
    assert tm.stop(record["task_id"]) is True
    for _ in range(100):
        if tm.get(record["task_id"])["status"] == "cancelled":
            break
        await asyncio.sleep(0.02)
    assert tm.get(record["task_id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_agent_task_events_replay_then_delta_then_done():
    """订阅语义：replay 先行，增量推送，done 收尾。"""
    tm = get_agent_task_manager()

    async def worker():
        await asyncio.sleep(0.05)
        tm.emit(task_id, {"type": "status", "text": "处理中"})
        tm.emit(task_id, {"type": "delta", "text": "你好"})
        tm.emit(task_id, {"type": "done", "payload": {"text": "你好", "applied_actions": 0}})

    task_id = "agt-test-events"
    tm.create("p1", worker, task_id=task_id)
    q = tm.subscribe(task_id)
    types = []
    try:
        for _ in range(10):
            ev = await asyncio.wait_for(q.get(), timeout=3)
            types.append(ev["type"])
            if ev["type"] == "done":
                break
    finally:
        tm.unsubscribe(task_id, q)
    assert types[0] == "replay"
    assert "status" in types and "delta" in types
    assert types[-1] == "done"


@pytest.mark.asyncio
async def test_agent_task_replay_carries_workflow_projection():
    """任务 #3：done 载荷的 workflow 投影（含 pending_decision_payload）入账，
    重连 replay 同源携带——刷新后结构化决策表单可重建。"""
    tm = get_agent_task_manager()
    wf = {
        "run_id": "run_x", "status": "waiting_user", "current_node": "review_spec",
        "completed_nodes": ["write_spec"], "event_sequence": 3,
        "pending_decision": True,
        "pending_decision_payload": {
            "token": "review:run_x", "node_id": "review_spec",
            "message": "请审阅规格文档",
            "schema": {"type": "decision", "fields": [
                {"key": "shots", "label": "几个分镜？", "type": "number"},
            ]},
            "options": [],
        },
    }

    async def worker():
        tm.emit(task_id, {"type": "done", "payload": {
            "text": "完成", "applied_actions": 0, "workflow": wf}})

    task_id = "agt-test-wf-replay"
    tm.create("p1", worker, task_id=task_id)
    # 等 worker 跑完再订阅：断言对象是 replay 快照（非增量事件），不引入时序竞态
    for _ in range(100):
        rec = tm.get(task_id)
        if rec and rec.get("status") == "done":
            break
        await asyncio.sleep(0.02)
    q = tm.subscribe(task_id)
    try:
        first = await asyncio.wait_for(q.get(), timeout=3)
        assert first["type"] == "replay"
        assert first["payload"]["workflow"] == wf
        assert first["payload"]["wf_event_sequence"] == 3
    finally:
        tm.unsubscribe(task_id, q)
