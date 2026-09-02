# -*- coding: utf-8 -*-
"""截断重答 + 建议动作持久化。

钉死契约：
1. StateManager.truncate_chat_tail：尾部真正丢弃（持久化生效）/正文替换保留
   turnId 等元数据并清空富文本 parts/越界返回 None 不写入；
2. POST /api/chat/truncate-resend：
   - 无用户消息 → 400（NO_USER_MESSAGE）；忙碌 → 409（AGENT_BUSY）；
   - text 非空且与原文不同 → 替换正文；尾部丢弃持久化生效；
   - text 缺省/为 null → 不替换，仅丢弃尾部后按原文重答；
   - 复用 start_agent_task 通路：响应体 {task_id, project_id, model}，
     「用户消息已落盘」守卫经内部 contextvar 传递（非请求字段）；
3. _real_stream / 非流式轨对该 contextvar 不重复落盘用户消息；
4. suggestedActions 落盘与读回：add_chat_message 消毒写入、
   get_full_snapshot/历史装载原样带回、streamError 与停止收敛路径
   随错误/停止消息落「继续刚才的任务」（kind=retry）。
"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state import chat_tail_ops
from src.video_agent.state.manager import StateManager


# ---------- 夹具 ----------

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
def ws_dir(tmp_path):
    return tmp_path / "ws"


@pytest.fixture
def client(svc, monkeypatch):
    import src.video_agent.web.routes.chat as chat_mod
    import src.video_agent.web.agent_task_manager as atm_mod

    # 忙碌判定钉死为「不忙」（忙碌用例单独注入假任务）
    monkeypatch.setattr(
        atm_mod, "get_agent_task_manager",
        lambda: SimpleNamespace(list_running=lambda project_id="": []),
    )
    # 默认供应商/模型解析钉死（不读真实 data/api_providers.json）；
    # 供应商清单同步钉死（重答预检校验供应商存在且启用）
    monkeypatch.setattr(chat_mod, "_resolve_chat_target", lambda: ("prov-x", "model-x"))
    import src.video_agent.core.provider_config as pc
    monkeypatch.setattr(
        pc, "load_merged_providers",
        lambda: [{"id": "prov-x", "enabled": True, "chat_models": ["model-x"]}],
    )

    app = FastAPI()
    app.include_router(chat_mod.router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def capture_start(monkeypatch):
    """拦截 start_agent_task，记录请求体与内部守卫标记并返回任务式响应。"""
    import src.video_agent.web.chat_service as cs

    captured = {}

    def fake_start(body):
        captured["body"] = body
        # 内部守卫标记在路由置位后才起任务，此处读到的即路由传递的值
        captured["persisted_flag"] = chat_tail_ops.user_message_persisted.get()
        return {"task_id": "agt-test", "project_id": "proj_001"}

    monkeypatch.setattr(cs, "start_agent_task", fake_start)
    return captured


# ---------- 1. StateManager.truncate_chat_tail ----------

def test_truncate_tail_discards_and_persists(svc, ws_dir):
    svc.add_chat_message("user", "第一问")
    svc.add_chat_message("agent", "第一答")
    svc.add_chat_message("user", "第二问")
    svc.add_chat_message("agent", "第二答")

    entry = svc.truncate_chat_tail(1)
    assert entry is not None and entry["text"] == "第一答"
    assert [m["text"] for m in svc.get_chat_messages()] == ["第一问", "第一答"]

    # 持久化层真正删除：新实例从磁盘装载只见截断后消息
    reloaded = StateManager(str(ws_dir))
    assert [m["text"] for m in reloaded.get_chat_messages()] == ["第一问", "第一答"]


def test_truncate_tail_replace_text_keeps_metadata_and_clears_parts(svc):
    svc.add_chat_message("user", "原问题", turn_id="turn-keep")
    msgs = svc.get_chat_messages()
    # 模拟富文本消息携带 parts（渲染排版片段）
    msgs[-1]["parts"] = [{"type": "text", "text": "原问题"}]
    svc.add_chat_message("agent", "旧回答")

    entry = svc.truncate_chat_tail(0, "改过的问题")
    assert entry["text"] == "改过的问题"
    assert entry["turnId"] == "turn-keep"  # turnId 保留
    assert "parts" not in entry  # 富文本 parts 清空（纯文本编辑一致性）
    assert len(svc.get_chat_messages()) == 1  # 尾部丢弃


def test_truncate_tail_without_new_text_keeps_original(svc):
    svc.add_chat_message("user", "原问题")
    svc.add_chat_message("agent", "旧回答")
    entry = svc.truncate_chat_tail(0, None)
    assert entry["text"] == "原问题"
    assert len(svc.get_chat_messages()) == 1


@pytest.mark.parametrize("bad_index", [-1, 3, 99])
def test_truncate_tail_out_of_range_noop(svc, bad_index):
    svc.add_chat_message("user", "第一问")
    svc.add_chat_message("agent", "第一答")
    assert svc.truncate_chat_tail(bad_index) is None
    assert len(svc.get_chat_messages()) == 2  # 不写入


def test_truncate_tail_last_index_noop_but_valid(svc):
    """keep_index=末位：无尾部可丢，返回该消息（合法，非越界）。"""
    svc.add_chat_message("user", "第一问")
    entry = svc.truncate_chat_tail(0)
    assert entry is not None and entry["text"] == "第一问"


# ---------- 2. POST /api/chat/truncate-resend ----------

def _seed_resend_history(svc):
    svc.add_chat_message("user", "第一轮问题")
    svc.add_chat_message("agent", "第一轮回答")
    svc.add_chat_message("user", "原问题", turn_id="turn-last")
    svc.get_chat_messages()[-1]["parts"] = [{"type": "text", "text": "原问题"}]
    svc.add_chat_message("agent", "旧回答")


def test_truncate_resend_replaces_text_and_discards_tail(client, svc, capture_start):
    _seed_resend_history(svc)
    r = client.post("/api/chat/truncate-resend", json={"text": "改过的问题"})
    assert r.status_code == 200
    assert r.json() == {"task_id": "agt-test", "project_id": "proj_001", "model": "model-x"}

    msgs = svc.get_chat_messages()
    assert [m["text"] for m in msgs] == ["第一轮问题", "第一轮回答", "改过的问题"]
    assert msgs[-1]["turnId"] == "turn-last"  # 既有元数据保留
    assert "parts" not in msgs[-1]

    body = capture_start["body"]
    assert body.message == "改过的问题"
    assert capture_start["persisted_flag"] is True  # 内部守卫：发送管线不重复落盘
    assert body.provider == "prov-x" and body.model == "model-x"
    # 携带重答前的历史（用户消息之前）
    assert body.messages == [
        {"role": "user", "content": "第一轮问题"},
        {"role": "assistant", "content": "第一轮回答"},
    ]


def test_truncate_resend_null_text_keeps_original(client, svc, capture_start):
    _seed_resend_history(svc)
    r = client.post("/api/chat/truncate-resend", json={"text": None})
    assert r.status_code == 200
    msgs = svc.get_chat_messages()
    assert msgs[-1]["text"] == "原问题"
    assert len(msgs) == 3  # 尾部 agent 消息仍被丢弃
    assert capture_start["body"].message == "原问题"


def test_truncate_resend_same_text_treated_as_no_edit(client, svc, capture_start):
    _seed_resend_history(svc)
    r = client.post("/api/chat/truncate-resend", json={"text": "原问题"})
    assert r.status_code == 200
    assert svc.get_chat_messages()[-1]["text"] == "原问题"
    assert capture_start["body"].message == "原问题"


def test_truncate_resend_discard_persisted_to_disk(client, svc, ws_dir, capture_start):
    _seed_resend_history(svc)
    r = client.post("/api/chat/truncate-resend", json={"text": "改过的问题"})
    assert r.status_code == 200
    reloaded = StateManager(str(ws_dir))
    assert [m["text"] for m in reloaded.get_chat_messages()] == [
        "第一轮问题", "第一轮回答", "改过的问题",
    ]


def test_truncate_resend_no_user_message_400(client, svc):
    svc.add_chat_message("agent", "只有 agent 消息")
    svc.add_chat_message("user", "系统动作行", kind="system_action")  # 不算用户消息
    r = client.post("/api/chat/truncate-resend", json={"text": "x"})
    assert r.status_code == 400
    body = r.json()
    assert body["error_code"] == "NO_USER_MESSAGE"
    assert body["code"].startswith("err.")
    # 未做任何截断
    assert len(svc.get_chat_messages()) == 2


def test_truncate_resend_empty_conversation_400(client, svc):
    r = client.post("/api/chat/truncate-resend", json={})
    assert r.status_code == 400
    assert r.json()["error_code"] == "NO_USER_MESSAGE"


def test_truncate_resend_busy_409(client, svc, monkeypatch):
    from src.video_agent.web import agent_task_manager as atm_mod

    _seed_resend_history(svc)

    class _StubTM:
        def list_running(self, project_id):
            return [{"task_id": "agt-busy-1", "status": "running"}]

    monkeypatch.setattr(atm_mod, "get_agent_task_manager", lambda: _StubTM())
    r = client.post("/api/chat/truncate-resend", json={"text": "x"})
    assert r.status_code == 409
    assert r.json()["error_code"] == "AGENT_BUSY"
    # 忙碌拒收不产生任何截断/替换副作用
    assert len(svc.get_chat_messages()) == 4


def test_truncate_resend_skips_system_action_user_messages(client, svc, capture_start):
    """最后一条用户消息是 system_action 时，回退到更早的真实用户消息。"""
    svc.add_chat_message("user", "真实问题")
    svc.add_chat_message("user", "放行", kind="system_action")
    svc.add_chat_message("agent", "回答")
    r = client.post("/api/chat/truncate-resend", json={"text": "改过的"})
    assert r.status_code == 200
    assert [m["text"] for m in svc.get_chat_messages()] == ["改过的"]
    assert capture_start["body"].message == "改过的"


# ---------- 3. 发送管线守卫（内部 contextvar）不重复落盘用户消息 ----------

class _Evt:
    def __init__(self, type_: str, payload=None, text: str = ""):
        self.type = type_
        self.payload = payload
        self.text = text


def _stream_body(**over):
    ns = SimpleNamespace(
        request_id="req-resend", message="改过的问题", provider="prov-x",
        model="model-x", messages=[], attachments=[],
        selected_draft_id="", selected_type="", skill_name="", skill_slug="",
        asset_mode="bound",
    )
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


async def test_real_stream_skips_user_persist_when_flag_set(svc, monkeypatch):
    import src.video_agent.web.chat_service as cs

    svc.add_chat_message("user", "改过的问题", turn_id="turn-last")
    events = []

    async def emit(ev):
        events.append(ev)

    monkeypatch.setattr(cs, "_create_chat_adapter", lambda p, m: object())
    monkeypatch.setattr(cs, "_resolve_summary_adapter", lambda body, cands: None)

    async def fake_stream(self, content, ctx):
        yield _Evt("done", {"text": "新回答"})

    monkeypatch.setattr(cs.Planner, "handle_message_stream", fake_stream)

    token = chat_tail_ops.user_message_persisted.set(True)
    try:
        await cs._real_stream(
            svc, None, _stream_body(),
            "改过的问题", "改过的问题", "改过的问题", True, emit, 0.0,
        )
    finally:
        chat_tail_ops.user_message_persisted.reset(token)
    user_msgs = [m for m in svc.get_chat_messages() if m.get("sender") == "user"]
    assert len(user_msgs) == 1  # 未重复落盘
    assert any(m.get("text") == "新回答" for m in svc.get_chat_messages())
    assert any(e.get("type") == "done" for e in events)


async def test_real_stream_persists_user_message_by_default(svc, monkeypatch):
    """对照：无标记时照常落盘用户消息（既有行为不变）。"""
    import src.video_agent.web.chat_service as cs

    async def emit(ev):
        pass

    monkeypatch.setattr(cs, "_create_chat_adapter", lambda p, m: object())
    monkeypatch.setattr(cs, "_resolve_summary_adapter", lambda body, cands: None)

    async def fake_stream(self, content, ctx):
        yield _Evt("done", {"text": "回答"})

    monkeypatch.setattr(cs.Planner, "handle_message_stream", fake_stream)

    await cs._real_stream(
        svc, None, _stream_body(), "改过的问题", "改过的问题", "改过的问题",
        True, emit, 0.0,
    )
    user_msgs = [m for m in svc.get_chat_messages() if m.get("sender") == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["text"] == "改过的问题"


# ---------- 4. suggestedActions 落盘与读回 ----------

def test_add_chat_message_suggested_actions_persist_and_readback(svc):
    svc.add_chat_message(
        "agent", "⚠️ 出错了",
        suggested_actions=[{"kind": "retry", "label": "继续刚才的任务", "value": ""}],
    )
    entry = svc.get_chat_messages()[-1]
    assert entry["suggestedActions"] == [
        {"kind": "retry", "label": "继续刚才的任务", "value": ""},
    ]
    # 快照/replay 原样带回（历史装载即可读到）
    snap = svc.get_full_snapshot()
    assert snap["chatMessages"][-1]["suggestedActions"][0]["kind"] == "retry"
    convs = svc.list_conversations()
    active = next(c for c in convs["conversations"] if c["id"] == convs["active_conversation_id"])
    assert active["messages"][-1]["suggestedActions"][0]["label"] == "继续刚才的任务"


def test_add_chat_message_suggested_actions_sanitized(svc):
    """kind 为空的项丢弃；无合法项时不落 suggestedActions 字段。"""
    svc.add_chat_message("agent", "x", suggested_actions=[{"kind": "", "label": "无效"}])
    assert "suggestedActions" not in svc.get_chat_messages()[-1]
    svc.add_chat_message("agent", "y", suggested_actions=[
        {"kind": "next", "label": None, "value": 123},
    ])
    assert svc.get_chat_messages()[-1]["suggestedActions"] == [
        {"kind": "next", "label": "", "value": "123"},
    ]


async def test_stream_error_persists_retry_suggestion(svc, monkeypatch):
    """streamError 收敛路径：错误消息随「继续刚才的任务」（kind=retry）落盘。"""
    import src.video_agent.web.chat_errors as chat_errors
    from src.video_agent.exceptions import GenerationError

    svc.add_chat_message("user", "用户消息")
    events = []

    async def emit(ev):
        events.append(ev)

    await chat_errors._emit_stream_error(
        svc, SimpleNamespace(model="model-x"), GenerationError("boom"), emit, True,
    )
    err_msg = svc.get_chat_messages()[-1]
    assert err_msg["sender"] == "agent"
    assert err_msg["text"].startswith("⚠️")
    assert err_msg["suggestedActions"] == [
        {"kind": "retry", "label": "继续刚才的任务", "value": ""},
    ]
    assert events[-1]["type"] == "error"


async def test_stream_error_without_user_message_no_suggestion(svc):
    """与前端挂载条件同语义：无用户消息时不给继续建议。"""
    import src.video_agent.web.chat_errors as chat_errors
    from src.video_agent.exceptions import GenerationError

    async def emit(ev):
        pass

    await chat_errors._emit_stream_error(
        svc, SimpleNamespace(model=""), GenerationError("boom"), emit, True,
    )
    assert "suggestedActions" not in svc.get_chat_messages()[-1]


async def test_persist_stop_trace_carries_retry_suggestion(svc):
    """停止收敛路径：有文本/无文本两条痕迹消息均随建议落盘。"""
    from src.video_agent.web.stop_manager import persist_stop_trace

    svc.add_chat_message("user", "用户消息")
    await persist_stop_trace(svc, "部分输出", "streaming", "model-x", "turn-s", True)
    await persist_stop_trace(svc, "", "thinking", "model-x", "turn-s2", True)
    msgs = svc.get_chat_messages()
    with_text, no_text = msgs[-2], msgs[-1]
    assert with_text["text"] == "部分输出"
    assert with_text["suggestedActions"][0]["kind"] == "retry"
    assert no_text["text"].startswith("⏹")
    assert no_text["suggestedActions"][0]["label"] == "继续刚才的任务"


def test_retry_suggestion_if_user_guard(svc):
    from src.video_agent.web.stop_manager import retry_suggestion_if_user

    assert retry_suggestion_if_user(svc) is None
    svc.add_chat_message("user", "hi")
    assert retry_suggestion_if_user(svc) == [
        {"kind": "retry", "label": "继续刚才的任务", "value": ""},
    ]


# ---------- 5. 安全性：冲突/防抖/空正文零副作用/双击并发 ----------

def test_truncate_conflict_when_disk_newer_returns_409(client, svc, ws_dir, capture_start):
    """磁盘账本被别的实例写过更新 → 截断落盘被版本闸拒绝 → 409，
    且不起任务、内存态回滚至磁盘事实。"""
    _seed_resend_history(svc)
    # 另一实例先写同项目：磁盘账本新于 svc 已知号
    other = StateManager(str(ws_dir))
    other.add_chat_message("agent", "另一实例的写入")

    r = client.post("/api/chat/truncate-resend", json={"text": "改过的问题"})
    assert r.status_code == 409
    assert r.json()["error_code"] == "STATE_CONFLICT"
    assert "body" not in capture_start  # 冲突时不起任务
    # 磁盘未被截断（另一实例的写入仍在尾部）
    reloaded = StateManager(str(ws_dir))
    texts = [m["text"] for m in reloaded.get_chat_messages()]
    assert texts[-1] == "另一实例的写入"
    assert "原问题" in texts  # 截断未落盘
    # 内存态回滚：与磁盘一致（不残留截断后的幽灵态）
    assert [m["text"] for m in svc.get_chat_messages()] == texts


async def test_truncate_flushes_inflight_debounce_no_loss(svc, ws_dir, monkeypatch):
    """防抖在途时截断：先冲刷在途防抖（不丢未落盘变更）再截断。"""
    import src.video_agent.web.routes.chat as chat_mod
    import src.video_agent.web.agent_task_manager as atm_mod
    import src.video_agent.web.chat_service as cs

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
    monkeypatch.setattr(
        cs, "start_agent_task",
        lambda body: {"task_id": "agt-d", "project_id": "proj_001"},
    )

    # 事件循环内写入 → 防抖在途（脏标在位，尚未落盘）
    svc.add_chat_message("user", "第一问")
    svc.add_chat_message("agent", "第一答")
    svc.add_chat_message("user", "第二问")
    assert svc._save_dirty is True

    await chat_tail_ops.flush_pending_saves(svc)
    mid = StateManager(str(ws_dir))
    assert len(mid.get_chat_messages()) == 3  # 在途防抖内容已冲刷落盘

    r = await chat_mod.truncate_resend(chat_mod.TruncateResendRequest(text="改过的问题"))
    assert isinstance(r, dict) and r["task_id"] == "agt-d"  # 成功路径直接返回任务体
    reloaded = StateManager(str(ws_dir))
    assert [m["text"] for m in reloaded.get_chat_messages()] == [
        "第一问", "第一答", "改过的问题",
    ]


def test_empty_message_rejected_before_truncate_no_side_effects(client, svc, capture_start):
    """空正文请求在截断前被拒：不产生任何截断副作用，不起任务。"""
    svc.add_chat_message("user", "")  # 原文为空
    svc.add_chat_message("agent", "旧回答")
    r = client.post("/api/chat/truncate-resend", json={"text": "   "})  # 编辑值也为空
    assert r.status_code == 400
    assert r.json()["error_code"] == "EMPTY_MESSAGE"
    assert len(svc.get_chat_messages()) == 2  # 未截断
    assert svc.get_chat_messages()[-1]["text"] == "旧回答"  # 尾部仍在
    assert "body" not in capture_start  # 未起任务


async def test_concurrent_double_click_creates_single_task(svc, monkeypatch):
    """双击并发（busy TOCTOU）：忙碌判定/截断/任务注册同临界区，两请求只成一单。"""
    import src.video_agent.web.routes.chat as chat_mod
    import src.video_agent.web.agent_task_manager as atm_mod

    svc.add_chat_message("user", "原问题")
    svc.add_chat_message("agent", "旧回答")

    class _FakeTM:
        def __init__(self):
            self.created = []

        def create(self, project_id, factory, task_id="", model="", conversation_id=""):
            rec = {"task_id": task_id, "project_id": project_id, "status": "running",
                   "conversation_id": conversation_id}
            self.created.append(rec)
            return rec

        def list_running(self, project_id=""):
            return list(self.created)

    fake = _FakeTM()
    monkeypatch.setattr(atm_mod, "get_agent_task_manager", lambda: fake)
    monkeypatch.setattr(chat_mod, "_resolve_chat_target", lambda: ("prov-x", "model-x"))
    import src.video_agent.core.provider_config as pc
    monkeypatch.setattr(
        pc, "load_merged_providers",
        lambda: [{"id": "prov-x", "enabled": True, "chat_models": ["model-x"]}],
    )

    body = chat_mod.TruncateResendRequest(text="改过的问题")
    r1, r2 = await asyncio.gather(
        chat_mod.truncate_resend(body), chat_mod.truncate_resend(body),
    )
    codes = sorted(getattr(x, "status_code", 200) for x in (r1, r2))
    assert codes == [200, 409]
    busy = r1 if getattr(r1, "status_code", 200) == 409 else r2
    assert json.loads(busy.body)["error_code"] == "AGENT_BUSY"
    assert len(fake.created) == 1  # 只成一个任务
    # 截断只发生一次（若两次都截断，第二条请求会先看到已截断态仍替换）
    assert [m["text"] for m in svc.get_chat_messages()] == ["改过的问题"]


def test_start_agent_task_failure_returns_structured_500(client, svc, monkeypatch):
    """不可预检的起任务失败：结构化 500，且截断必须回滚——
    尾部快照原样恢复（起任务失败→消息回滚），不得遗留截断后的半成品对话。"""
    import src.video_agent.web.chat_service as cs

    _seed_resend_history(svc)
    texts_before = [m["text"] for m in svc.get_chat_messages()]

    def boom(body):
        raise RuntimeError("任务注册器故障")

    monkeypatch.setattr(cs, "start_agent_task", boom)
    r = client.post("/api/chat/truncate-resend", json={"text": "改过的问题"})
    assert r.status_code == 500
    body = r.json()
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "起任务失败" in body["detail"]
    # 起任务失败→消息回滚：被截断丢弃的尾部与被替换的正文原样恢复
    assert [m["text"] for m in svc.get_chat_messages()] == texts_before
    assert texts_before == ["第一轮问题", "第一轮回答", "原问题", "旧回答"]


# ---------- 6. 契约扩展：显式 provider/model/thinking_level ----------

def _patch_providers(monkeypatch, providers):
    # patch 目标归一为实现体（与 test_flow_pause_wizard 口径对齐）：
    # core/provider_config.py 是单一事实源（批次E：web 薄壳已清偿删除）
    import src.video_agent.core.provider_config as pc
    monkeypatch.setattr(pc, "load_merged_providers", lambda: providers)


def test_resend_explicit_target_valid_and_model_in_response(client, svc, capture_start, monkeypatch):
    _patch_providers(monkeypatch, [
        {"id": "prov-a", "enabled": True, "chat_models": ["model-a1", "model-a2"]},
    ])
    _seed_resend_history(svc)
    r = client.post("/api/chat/truncate-resend", json={
        "text": "改过的问题", "provider": "prov-a",
        "model": "model-a2", "thinking_level": "high",
    })
    assert r.status_code == 200
    assert r.json()["model"] == "model-a2"  # 200 响应体携带实际解析模型
    body = capture_start["body"]
    assert body.provider == "prov-a" and body.model == "model-a2"
    assert body.thinking_level == "high"


def test_resend_explicit_target_disabled_provider_400(client, svc, capture_start, monkeypatch):
    _patch_providers(monkeypatch, [
        {"id": "prov-a", "enabled": False, "chat_models": ["model-a1"]},
    ])
    _seed_resend_history(svc)
    r = client.post("/api/chat/truncate-resend", json={"provider": "prov-a", "model": "model-a1"})
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_CHAT_TARGET"
    assert len(svc.get_chat_messages()) == 4  # 截断前拒绝：零副作用
    assert "body" not in capture_start


def test_resend_explicit_model_not_in_list_400(client, svc, capture_start, monkeypatch):
    _patch_providers(monkeypatch, [
        {"id": "prov-a", "enabled": True, "chat_models": ["model-a1"]},
    ])
    _seed_resend_history(svc)
    r = client.post("/api/chat/truncate-resend", json={"provider": "prov-a", "model": "model-x"})
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_CHAT_TARGET"
    assert len(svc.get_chat_messages()) == 4


def test_resend_explicit_provider_default_model(client, svc, capture_start, monkeypatch):
    """只传 provider 不传 model → 取该供应商聊天模型清单首个。"""
    _patch_providers(monkeypatch, [
        {"id": "prov-a", "enabled": True, "chat_models": ["model-a1", "model-a2"]},
    ])
    _seed_resend_history(svc)
    r = client.post("/api/chat/truncate-resend", json={"provider": "prov-a"})
    assert r.status_code == 200
    assert r.json()["model"] == "model-a1"
    assert capture_start["body"].model == "model-a1"


# ---------- 7. 非流式轨守卫（同流式轨同构） ----------

def _non_stream_body():
    return SimpleNamespace(
        request_id="req-ns", message="改过的问题", provider="prov-x", model="model-x",
        messages=[], attachments=[], selected_draft_id="", selected_type="",
        skill_name="", skill_slug="", asset_mode="bound", context_mode="studio",
        doc_blocks=[], skill_blocks=[], gate_overrides=[], user_id="",
        thinking_level="", pause_response={}, system_action="",
        images=[], videos=[], content_parts=[],
    )


def _stub_non_stream_planner(monkeypatch):
    """桩掉适配器解析与 Planner，非流式轨不触网（传输契约验证用）。"""
    import src.video_agent.web.chat_service as cs

    monkeypatch.setattr(cs, "_create_chat_adapter", lambda p, m: object())
    monkeypatch.setattr(cs, "_resolve_summary_adapter", lambda body, cands: None)

    async def fake_handle_message(self, content, ctx, on_event=None):  # noqa: ARG001
        return SimpleNamespace(
            text="stub 回答", applied_actions=0, steps=1, warnings=[],
            confirmation="", action_log=[], confirmation_options=[],
            pause_id="", pause_kind="", image_urls=[], documents_written=[],
            suggested_actions=None,
        )

    monkeypatch.setattr(cs.Planner, "handle_message", fake_handle_message)


async def test_non_stream_skips_user_persist_when_flag_set(svc, monkeypatch):
    import src.video_agent.web.chat_service as cs

    _stub_non_stream_planner(monkeypatch)

    senders = []
    orig_add = svc.add_chat_message

    def rec(sender, text, **kw):
        senders.append(sender)
        return orig_add(sender, text, **kw)

    svc.add_chat_message = rec
    orig_add("user", "改过的问题")  # 截断重答已落盘的用户消息
    senders.clear()

    token = chat_tail_ops.user_message_persisted.set(True)
    try:
        await cs._non_stream_inner(_non_stream_body(), "改过的问题")
    finally:
        chat_tail_ops.user_message_persisted.reset(token)
        svc.add_chat_message = orig_add
    assert "user" not in senders  # 未重复落盘用户消息
    assert "agent" in senders  # agent 回复照常落盘


async def test_non_stream_persists_user_message_by_default(svc, monkeypatch):
    """对照：无守卫标记时非流式轨照常落盘用户消息。"""
    import src.video_agent.web.chat_service as cs

    _stub_non_stream_planner(monkeypatch)

    senders = []
    orig_add = svc.add_chat_message

    def rec(sender, text, **kw):
        senders.append(sender)
        return orig_add(sender, text, **kw)

    svc.add_chat_message = rec
    try:
        await cs._non_stream_inner(_non_stream_body(), "改过的问题")
    finally:
        svc.add_chat_message = orig_add
    assert "user" in senders
