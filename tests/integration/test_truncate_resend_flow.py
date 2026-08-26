"""集成测试：截断重答走真实 app 的全链路（任务式传输 + 桩 Planner）。

覆盖（Daniel S3）：截断 → 任务受理 → 用户消息不翻倍 → SSE 接续点可读。
与单测的差异：不拦截 start_agent_task，真实后台 worker 跑完桩流式，
事件经 agent_task_manager 的 replay/订阅通道验证。

注：httpx ASGITransport 整段缓冲响应体，SSE 订阅须在任务仍 running 时发起，
生成器随 done 事件转发而终结，响应方可完整返回。
"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from src.video_agent.state.manager import StateManager
from src.video_agent.web.agent_task_manager import get_agent_task_manager
from src.video_agent.web.app import app


class _Evt:
    def __init__(self, type_: str, payload=None, text: str = ""):
        self.type = type_
        self.payload = payload
        self.text = text


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """每个测试使用独立的临时工作区；桩掉供应商/Planner，不触网。"""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))

    import src.video_agent.core.provider_config as pc
    monkeypatch.setattr(
        pc, "load_merged_providers",
        lambda: [{"id": "prov-x", "enabled": True, "chat_models": ["model-x"]}],
    )

    import src.video_agent.web.chat_service as cs
    monkeypatch.setattr(cs, "_create_chat_adapter", lambda p, m: object())
    monkeypatch.setattr(cs, "_resolve_summary_adapter", lambda body, cands: None)

    async def fake_stream(self, content, ctx):
        yield _Evt("done", {"text": "桩回答"})

    monkeypatch.setattr(cs.Planner, "handle_message_stream", fake_stream)

    async def fake_handle_message(self, content, ctx, on_event=None):  # noqa: ARG001
        return SimpleNamespace(
            text="桩回答", applied_actions=0, steps=1, warnings=[],
            confirmation="", action_log=[], confirmation_options=[],
            pause_id="", pause_kind="", image_urls=[], documents_written=[],
            suggested_actions=None,
        )

    monkeypatch.setattr(cs.Planner, "handle_message", fake_handle_message)

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path))
    # 清空 demo 预置消息，保证用例从空对话起步
    del svc.get_chat_messages()[:]
    svc.save()
    StateManager._instance = svc
    yield svc
    StateManager.reset_instance()


def _parse_sse(raw: str) -> list:
    events = []
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


async def test_truncate_resend_full_flow(reset_state):
    svc = reset_state
    # 历史：一条用户消息 + 两条待丢弃的尾部回复
    svc.add_chat_message("user", "原问题")
    svc.add_chat_message("agent", "旧回答")
    svc.add_chat_message("agent", "更旧回答")

    tm = get_agent_task_manager()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1) 截断 → 任务受理（显式供应商，响应体携带实际解析模型）
        r = await client.post("/api/chat/truncate-resend", json={
            "text": "改过的问题",
            "provider": "prov-x",
            "model": "model-x",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"]
        assert data["project_id"] == svc.active_project_id
        assert data["model"] == "model-x"
        task_id = data["task_id"]

        # 截断即时生效：尾部丢弃 + 正文替换（任务完成前即可见）
        assert [m["text"] for m in svc.get_chat_messages()] == ["改过的问题"]

        # 2) SSE 接续点可读：任务 running 时订阅，先回放 replay（累计状态），
        #    随 worker 推进增量转发，done 终态事件后流自然终结
        sse_events = None
        if (tm.get(task_id) or {}).get("status") == "running":
            resp = await client.get(f"/api/agent/tasks/{task_id}/events")
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            sse_events = _parse_sse(resp.text)
            assert sse_events and sse_events[0]["type"] == "replay"
            assert sse_events[0]["payload"]["task_id"] == task_id
            assert any(e.get("type") == "done" for e in sse_events)
        else:
            # 防御分支：订阅时任务已终态，replay 仍应即刻可读（订阅通道契约）
            q = tm.subscribe(task_id)
            assert q is not None
            replay = q.get_nowait()
            assert replay["type"] == "replay"
            assert replay["payload"]["task_id"] == task_id

        # 3) 任务跑完（桩 Planner 本地回复）
        rec = None
        for _ in range(400):
            rec = tm.get(task_id)
            if rec and rec["status"] in ("done", "error", "stopped", "cancelled"):
                break
            await asyncio.sleep(0.05)
        assert rec is not None and rec["status"] == "done", (rec or {}).get("error")

        # 4) 用户消息不翻倍：done 快照里恰有一条该用户消息
        state = (rec.get("done_payload") or {}).get("state") or {}
        msgs = state.get("chatMessages") or []
        user_texts = [m.get("text") for m in msgs if m.get("sender") == "user"]
        assert user_texts == ["改过的问题"]
        # agent 回复在场（桩 Planner 生成）
        assert any(m.get("sender") == "agent" for m in msgs)

        # 5) 磁盘终态（防抖结算后）：用户消息同样不翻倍
        await asyncio.sleep(0.8)
        reloaded = StateManager(str(svc._workspace_dir))
        disk_users = [
            m for m in reloaded.get_chat_messages() if m.get("sender") == "user"
        ]
        assert len(disk_users) == 1
        assert disk_users[0]["text"] == "改过的问题"
