# -*- coding: utf-8 -*-
"""Skill 流程跑通修复批 2：插播报（具名事件卡）。

钉死四件事：
① 触发时刻逐卡唯一（§四 批 2 表）：规格已完成（建立或更新都发、非规格文档
   不发）/ 故事板已更新（建组/加卡/补字段）/ 素材已完成（image_generate 批级）/
   时间线已更新（generate_video）/ 信息搜索完成（读类，只进时间线不进上下文）；
② 事件卡双通道：trace 有条目（刷新后仍在）+ 实时时间线帧成对发出；
③ 写产物卡进模型上下文（flowEvents event_card），读类卡不进（防逐轮膨胀）；
④ 素材变更已同步：整板落库媒体指纹 diff 记 media_synced（一次性），
   轮始消费播报后不再可见。
"""
import asyncio
import json

import pytest

from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.progress import emit_event_card
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult
from src.video_agent.web.routes.project import (
    ProjectStateUpdate, _media_fingerprint, put_project_state,
)


class _OkTM:
    """全部工具一律成功；data 按工具名回填（image_generate 携带 image_urls）。"""

    async def invoke_tool(self, name, args):
        data = {}
        if name == "image_generate":
            data = {"image_urls": ["http://img/1.png", "http://img/2.png"]}
        return ToolResult(success=True, data=data)


def _run_tool(monkeypatch, tool_name, args, raw_state=None):
    """跑一次成功工具调用，返回 (SSE 事件列表, StateManager 流事件, trace 动作)。"""
    AgentTracer.reset()
    tracer = AgentTracer.get_instance()
    tracer.start_trace("batch2-event-cards")
    monkeypatch.setattr(
        FCToolRunner, "_raw_state", staticmethod(lambda: raw_state or {}))
    events = []

    async def on_event(ev):
        events.append(ev)

    runner = FCToolRunner(tool_manager=_OkTM())
    response = ChatResponseOf(tool_name, args)
    asyncio.run(runner.execute(response, on_event=on_event, gate_override=True))
    svc = StateManager.get_instance()
    tracer.end_step(step=1)  # 冲洗子步骤缓冲（事件卡挂 pending_subs）
    trace = tracer.finish_trace()
    actions = [a for s in (trace.get("steps") or []) for a in (s.get("actions") or [])]
    return events, svc, actions


def ChatResponseOf(tool_name, args):
    from src.video_agent.adapters.base_chat import ChatResponse

    return ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": tool_name, "arguments": json.dumps(args)}},
    ])


def _card_events(events):
    return [e for e in events if e.get("type") == "tool_started"
            and e.get("name") == "event_card"]


# ---------- ① 触发时刻逐卡唯一 ----------


@pytest.mark.parametrize("tool,args,expect_card,expect_count", [
    ("document_write", {"name": "Final_Video_Spec.md", "content": "# 规格"}, "规格已完成", 1),
    # 批 6 · A3：keyElement 建组 = 资产已注册 + 故事板已更新（一动作多卡）
    ("storyboard_create_group", {"group_type": "keyElement", "title": "角色"}, "资产已注册", 2),
    ("storyboard_create_group", {"group_type": "shot", "title": "镜头一"}, "故事板已更新", 1),
    ("storyboard_add_draft", {"draft": {"label": "程心"}}, "故事板已更新", 1),
    ("storyboard_patch_draft", {"draft_id": "d1", "patch": {"prompt": "p"}}, "故事板已更新", 1),
    ("generate_video", {"draft_id": "d1"}, "时间线已更新", 1),
    ("read_skill", {"name": "AI-短剧一站式生成"}, "信息搜索完成", 1),
    ("read_project_doc", {"name": "Final_Video_Spec.md"}, "信息搜索完成", 1),
])
def test_card_fires_on_trigger_tools(monkeypatch, tool, args, expect_card, expect_count):
    events, svc, actions = _run_tool(monkeypatch, tool, args)
    cards = _card_events(events)
    assert len(cards) == expect_count, f"{tool} 应发 {expect_count} 张卡（{expect_card}）"
    assert any(c["summary"].startswith(expect_card) for c in cards), \
        f"应含 {expect_card} 卡，实际: {[c['summary'] for c in cards]}"
    # trace 有对应条目（刷新后仍在）
    assert any(a.get("name") == "event_card" for a in actions)


def test_key_element_group_fires_asset_registered_then_board_updated(monkeypatch):
    """批 6 · A3（M8 兑现）：keyElement 建组先发「资产已注册」再发「故事板已更新」。"""
    events, _svc, _actions = _run_tool(
        monkeypatch, "storyboard_create_group",
        {"group_type": "keyElement", "title": "程心"})
    summaries = [c["summary"] for c in _card_events(events)]
    assert summaries == ["资产已注册：程心", "故事板已更新：程心"], summaries


def test_spec_card_fires_on_update_too(monkeypatch):
    """规格二次更新同样发「规格已完成」（V4-2：建立或更新都发）。"""
    for _ in range(2):
        events, svc, _ = _run_tool(
            monkeypatch, "document_write",
            {"name": "制片规格.md", "content": "# v"}, {})
        assert len(_card_events(events)) == 1


def test_no_card_for_non_spec_document(monkeypatch):
    """非规格文档写入不發规格卡（doc_written 即显卡仍在，事件卡不重复）。"""
    events, svc, _ = _run_tool(
        monkeypatch, "document_write", {"name": "剧本大纲.md", "content": "# 大纲"}, {})
    assert _card_events(events) == []


def test_image_generate_card_carries_batch_count(monkeypatch):
    events, svc, _ = _run_tool(
        monkeypatch, "image_generate", {"target": "all_keyElements"}, {})
    cards = _card_events(events)
    assert len(cards) == 1
    assert "2 张图片" in cards[0]["summary"]


# ---------- ②③ 模型上下文节流：写产物卡进、读类卡不进 ----------


def test_write_card_enters_flow_events_read_card_does_not(monkeypatch):
    _, svc, _ = _run_tool(
        monkeypatch, "storyboard_create_group",
        {"group_type": "keyElement", "title": "角色"}, {})
    kinds = [e.get("kind") for e in (svc.state_dict.get("flowEvents") or [])]
    assert "event_card" in kinds

    svc.state_dict["flowEvents"] = []  # 清写产物卡，单独验证读类卡不进上下文
    _, svc, _ = _run_tool(monkeypatch, "read_skill", {"name": "x"}, {})
    kinds = [e.get("kind") for e in (svc.state_dict.get("flowEvents") or [])]
    assert "event_card" not in kinds, "读类卡只进时间线，不进模型上下文"


# ---------- ④ 素材变更已同步 ----------


def test_media_fingerprint_detects_media_change_only():
    state_a = {"keyElements": [{"id": "g1", "drafts": [
        {"id": "d1", "imgUrl": "", "videoUrl": "", "audioUrl": ""}]}],
        "shots": [], "audioItems": [], "assets": []}
    state_b = {"keyElements": [{"id": "g1", "drafts": [
        {"id": "d1", "imgUrl": "http://x/1.png", "videoUrl": "", "audioUrl": ""}]}],
        "shots": [], "audioItems": [], "assets": []}
    state_c = {"keyElements": [{"id": "g1", "title": "改标题", "drafts": [
        {"id": "d1", "imgUrl": "", "videoUrl": "", "audioUrl": ""}]}],
        "shots": [], "audioItems": [], "assets": []}
    assert _media_fingerprint(state_a) != _media_fingerprint(state_b), "媒体 URL 变化须检出"
    assert _media_fingerprint(state_a) == _media_fingerprint(state_c), "纯标题改动不播报"


async def test_put_project_state_records_media_synced_once():
    """整板落库：媒体真实变化记 media_synced（一次性）；无变化不记。"""
    svc = StateManager.get_instance()
    for cat in ("keyElements", "shots", "audioItems", "assets"):
        svc.state_dict[cat] = []
    payload = {"id": "g1", "title": "角色", "drafts": [
        {"id": "d1", "label": "程心", "imgUrl": ""}]}
    await put_project_state(ProjectStateUpdate(keyElements=[dict(payload)]))
    assert not [e for e in (svc.state_dict.get("flowEvents") or [])
                if e.get("kind") == "media_synced"]

    changed = dict(payload, drafts=[{"id": "d1", "label": "程心",
                                     "imgUrl": "http://x/1.png"}])
    await put_project_state(ProjectStateUpdate(keyElements=[changed]))
    synced = [e for e in (svc.state_dict.get("flowEvents") or [])
              if e.get("kind") == "media_synced"]
    assert len(synced) == 1, "媒体变化恰好记一条一次性同步事件"


async def test_consume_flow_events_takes_only_requested_kind():
    svc = StateManager.get_instance()
    svc.record_flow_event("media_synced", "a")
    svc.record_flow_event("event_card", "规格已完成：x.md")
    svc.record_flow_event("media_synced", "b")
    taken = svc.consume_flow_events("media_synced")
    assert [e["detail"] for e in taken] == ["a", "b"]
    kinds = [e.get("kind") for e in (svc.state_dict.get("flowEvents") or [])]
    assert kinds == ["event_card"], "取走 media_synced 且不影响其他事件"
    assert svc.consume_flow_events("media_synced") == [], "消费一次性"


async def test_pre_turn_event_card_adopted_by_next_trace():
    """轮始事件卡：pre_turn 缓冲由下一次 start_trace 收养（持久化不丢）。"""
    AgentTracer.reset()
    emitted = []

    async def on_event(ev):
        emitted.append(ev)

    await emit_event_card("素材变更已同步", "按最新状态继续",
                          emitter=on_event, pre_turn=True)
    tracer = AgentTracer.get_instance()
    tracer.start_trace("batch2-turn-start")
    tracer.end_step(step=1)
    trace = tracer.finish_trace()
    actions = [a for s in trace.get("steps") for a in s.get("actions") or []]
    assert any(a.get("name") == "event_card"
               and "素材变更已同步" in a.get("summary", "") for a in actions)
    # 实时通道成对帧
    started = [e for e in emitted if e.get("type") == "tool_started"
               and e.get("name") == "event_card"]
    finished = [e for e in emitted if e.get("type") == "tool_finished"]
    assert len(started) == 1 and len(finished) == 1
    AgentTracer.reset()
