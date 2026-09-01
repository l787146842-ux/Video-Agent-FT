# -*- coding: utf-8 -*-
"""二期子对话批 3：子对话上传参考素材 + 子对话不发确认卡（附带项）。

钉死契约（用户裁决）：
1. 素材绑子对话线程（对话级 scopeRefs）：scope 请求携带的引用只进
   conversations[i].scopeRefs，不进全局 assets/uploadedDocs（主对话零污染）；
   主对话上传行为不变（bind_attachments 照旧登记 assets）；
2. scopeRefs 生命周期与线程对齐：随撤销/快照原子恢复、随级联删除消失；
   unref 端点只解引用不删物理文件（引用不存在返 404）；
3. 上下文铁律不松动：_apply_scope_profile 注入本线程 scopeRefs 与
   「本线程参考素材已注入」措辞，跨线程不互串；
4. 子对话不发确认卡：scope_auto_pause=True 时 workflow_pause 直接放行
   （不登记暂停三态、不组卡、不签发 pause_id，回喂改写「已自动确认」）；
   主对话旗标缺省关，问即停语义零变化；Planner 旗标经 _execute_fc_tools 透传。
"""
import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.planner import Planner
from src.video_agent.state import context_builder, conversation_ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult
from src.video_agent.web import attachments as web_attachments


def _scope(draft_id: str, group_id: str = "grp-1") -> dict:
    return {
        "kind": "adjust", "cat": "shotGroups",
        "group_id": group_id, "draft_id": draft_id, "label": f"分镜 {draft_id}",
    }


def _att(url: str, name: str = "参考图", kind: str = "image", ref_id: str = "") -> dict:
    return {"id": ref_id, "name": name, "kind": kind, "url": url}


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


def _thread_scope_refs(svc, conv_id: str) -> list:
    for c in svc._raw_state.get("conversations") or []:
        if isinstance(c, dict) and c.get("id") == conv_id:
            return c.get("scopeRefs") or []
    return []


# ---------- 1. 绑线程隔离：不进全局，主对话行为不变 ----------

def test_bind_scope_refs_thread_only_global_untouched(svc):
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    added = conversation_ops.bind_thread_scope_refs(
        svc, thread["id"], [_att("/workspace/assets/a.png", ref_id="r1")])

    assert [r["url"] for r in added] == ["/workspace/assets/a.png"]
    refs = _thread_scope_refs(svc, thread["id"])
    assert refs and refs[0]["id"] == "r1" and refs[0]["kind"] == "image"
    # 主对话零污染：全局 assets / uploadedDocs 一律不动
    assert svc._raw_state.get("assets") in (None, [])
    assert svc._raw_state.get("uploadedDocs") in (None, [])


def test_bind_scope_refs_dedupes_url_and_caps_count(svc):
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    url = "/workspace/assets/a.png"
    conversation_ops.bind_thread_scope_refs(svc, thread["id"], [_att(url)])
    # 同 url 重复绑不重复登记
    conversation_ops.bind_thread_scope_refs(svc, thread["id"], [_att(url, name="又传一次")])
    assert len(_thread_scope_refs(svc, thread["id"])) == 1
    # 数量上限沿用 settings.max_attachments（与主链路同口径）
    from src.video_agent.config import settings
    many = [_att(f"/workspace/assets/m{i}.png") for i in range(int(settings.max_attachments) + 3)]
    thread2 = conversation_ops.create_scoped_conversation(svc, _scope("draft-2"))
    conversation_ops.bind_thread_scope_refs(svc, thread2["id"], many)
    assert len(_thread_scope_refs(svc, thread2["id"])) == int(settings.max_attachments)


def test_bind_scope_refs_unknown_thread_no_side_effect(svc):
    assert conversation_ops.bind_thread_scope_refs(
        svc, "conv-ghost", [_att("/workspace/assets/a.png")]) == []
    assert svc._raw_state.get("assets") in (None, [])


def test_main_chat_upload_binding_unchanged(svc):
    """主对话上传行为不变（隔离断言另一半：分流不伤既有链路）"""
    web_attachments.bind_attachments(svc, [_att("/workspace/assets/main.png")])
    assets = svc._raw_state.get("assets") or []
    assert any(a.get("url") == "/workspace/assets/main.png" and a.get("isBound") for a in assets)


def test_remove_thread_scope_ref_unbinds_only(svc):
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    conversation_ops.bind_thread_scope_refs(svc, thread["id"], [_att("/workspace/assets/a.png")])
    ref_id = _thread_scope_refs(svc, thread["id"])[0]["id"]

    assert conversation_ops.remove_thread_scope_ref(svc, thread["id"], ref_id) is True
    assert _thread_scope_refs(svc, thread["id"]) == []
    # 物理不清：文件仍留在共享素材目录口径（系统无素材 GC，此处钉引用层语义）
    assert conversation_ops.remove_thread_scope_ref(svc, thread["id"], ref_id) is False
    assert conversation_ops.remove_thread_scope_ref(svc, "conv-ghost", ref_id) is False


# ---------- 2. 撤销原子恢复 / 级联带走 ----------

def test_undo_restores_scope_refs_atomically(svc):
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    conversation_ops.bind_thread_scope_refs(svc, thread["id"], [_att("/workspace/assets/a.png")])

    svc.push_undo()
    ref_id = _thread_scope_refs(svc, thread["id"])[0]["id"]
    conversation_ops.remove_thread_scope_ref(svc, thread["id"], ref_id)
    assert _thread_scope_refs(svc, thread["id"]) == []

    assert svc.undo() is True
    # 快照栈含 conversations 全态：引用随线程体原子回来
    restored = _thread_scope_refs(svc, thread["id"])
    assert [r["url"] for r in restored] == ["/workspace/assets/a.png"]


def test_cascade_delete_takes_scope_refs(svc):
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    conversation_ops.bind_thread_scope_refs(svc, thread["id"], [_att("/workspace/assets/a.png")])

    removed = conversation_ops.cleanup_scoped_threads_for_removed(svc, {"draft-1"})
    assert removed == [thread["id"]]
    assert _thread_scope_refs(svc, thread["id"]) == []  # 线程没了，引用随对话体消失


# ---------- 3. 上下文注入（铁律不松动） ----------

def _parse(svc, scope):
    return json.loads(context_builder.build_agent_context(
        svc.state_dict, asset_mode="bound", cache=None, scope=scope))


def test_context_injects_thread_scope_refs(svc):
    svc.state_dict["shots"] = [{
        "id": "grp-1", "title": "G1",
        "drafts": [{"id": "draft-1", "label": "a", "prompt": "P"}],
    }]
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    conversation_ops.bind_thread_scope_refs(
        svc, thread["id"], [_att("/workspace/assets/a.png", name="风格参考")])

    snap = _parse(svc, _scope("draft-1"))
    assert snap["scopeRefs"] == [{"name": "风格参考", "kind": "image", "url": "/workspace/assets/a.png"}]
    assert "本线程参考素材" in snap["scopeNote"]
    # 铁律：全局素材面仍不可见
    assert "assets" not in snap and "uploadedDocs" not in snap


def test_context_scope_refs_no_cross_thread_leak(svc):
    """A 线程的引用不注入 B 线程；无线程时空列表"""
    thread_a = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    conversation_ops.bind_thread_scope_refs(
        svc, thread_a["id"], [_att("/workspace/assets/a.png")])
    conversation_ops.create_scoped_conversation(svc, _scope("draft-2"))

    assert _parse(svc, _scope("draft-2"))["scopeRefs"] == []
    assert [r["url"] for r in _parse(svc, _scope("draft-1"))["scopeRefs"]] == [
        "/workspace/assets/a.png"]


# ---------- 4. unref 端点（浮窗清单移除通道） ----------

def test_thread_endpoint_returns_scope_refs_and_unref_works(svc, client):
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    conversation_ops.bind_thread_scope_refs(svc, thread["id"], [_att("/workspace/assets/a.png")])

    resp = client.post("/api/conversations/thread", json={"scope": _scope("draft-1")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] == thread["id"]
    assert [r["url"] for r in data["scope_refs"]] == ["/workspace/assets/a.png"]

    ref_id = data["scope_refs"][0]["id"]
    ok = client.post("/api/conversations/thread/unref", json={
        "conversation_id": thread["id"], "ref_id": ref_id})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert _thread_scope_refs(svc, thread["id"]) == []
    # 重复移除 / 幽灵线程 → 404（幂等友好）
    again = client.post("/api/conversations/thread/unref", json={
        "conversation_id": thread["id"], "ref_id": ref_id})
    assert again.status_code == 404
    ghost = client.post("/api/conversations/thread/unref", json={
        "conversation_id": "conv-ghost", "ref_id": ref_id})
    assert ghost.status_code == 404


# ---------- 5. 子对话不发确认卡（pause 放行） ----------

class _TM:
    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})

    def get_tool(self, name):
        return type("_StubTool", (), {"risk": "low"})


def _fc(*calls):
    return ChatResponse(content="", tool_calls=[
        {"id": f"c{i}", "type": "function",
         "function": {"name": n, "arguments": json.dumps(a)}}
        for i, (n, a) in enumerate(calls)
    ])


def test_scope_auto_pause_passes_without_pause_registration(svc, monkeypatch):
    """scope 旗标开：不签发 pause_id、不组卡、不登记暂停三态、回喂改写"""
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))

    res = asyncio.run(runner.execute(
        _fc(("workflow_pause", {"message": "请确认"})), scope_auto_pause=True))

    assert res.pause_id == ""              # 未签发
    assert res.confirmation == ""          # 未组卡
    inter = svc.state_dict.get("interaction") or {}
    assert not inter.get("awaiting_confirmation")   # 暂停三态一律不写
    assert not (inter.get("active_pause") or {})
    # 回喂改写为「已自动确认」，模型继续执行
    assert res.tool_results[-1]["data"].get("auto_passed") is True


def test_main_chat_pause_semantics_unchanged(svc, monkeypatch):
    """旗标缺省关：主对话问即停照常发行（回归守卫）"""
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))

    res = asyncio.run(runner.execute(_fc(("workflow_pause", {"message": ""}))))

    assert res.pause_id != ""              # 照常签发
    assert res.confirmation                # 照常组卡
    assert res.tool_results[-1]["data"].get("auto_passed") is None


def test_planner_passes_scope_flag_to_runner(svc, monkeypatch):
    """Planner 实例旗标经 _execute_fc_tools 透传（每请求新建不跨请求泄漏）"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    captured = {}

    async def _capture(response, **kwargs):
        captured.update(kwargs)
        from src.video_agent.core.fc_tool_runner import FCExecuteResult
        return FCExecuteResult(
            applied=0, confirmation="", image_urls=[], chat_inserts=[], action_log=[],
            confirmation_options=[], tool_results=[], docs_written=[], warnings=[],
            pause_overflow="", pause_id="")

    monkeypatch.setattr(planner._fc_runner, "execute", _capture)

    planner._scope_auto_pause = True
    asyncio.run(planner._execute_fc_tools(_fc()))
    assert captured.get("scope_auto_pause") is True

    planner._scope_auto_pause = False
    asyncio.run(planner._execute_fc_tools(_fc()))
    assert captured.get("scope_auto_pause") is False
