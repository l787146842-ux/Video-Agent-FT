# -*- coding: utf-8 -*-
"""会话投影四单元折叠/视图/一致切单测（D2 批 commit2）。

钉死：① 暂停单元三态折叠（发行/真人消费/合成消息不消费）；② 子代理目录
running→completed/failed；③ 故事板计数只记 ok 且按 group_type 归类；
④ 聊天尾上限截断；⑤ snapshot asOfSeq 与双跑对拍 [ProjDiff] 留痕。
"""
import json

from loguru import logger

from src.video_agent.core import session_projection as sp


def _assistant_pause(seq, message="确认？", options=None):
    return {
        "type": "assistant/message", "seq": seq, "content": "",
        "tool_calls": [{"id": f"c{seq}", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps(
                {"message": message, "options": options or []},
                ensure_ascii=False),
        }}],
    }


def test_pause_issue_then_user_consumes():
    evs = [
        _assistant_pause(1),
        {"type": "user/message", "seq": 2, "source": "user", "content": "好"},
    ]
    v = sp.view_states(sp.fold_events(evs))["interaction_pause"]
    assert v["active_pause"] is None
    assert v["pause_count"] == 1


def test_pause_synthetic_state_message_does_not_consume():
    evs = [
        _assistant_pause(1),
        {"type": "user/message", "seq": 2, "source": "state", "content": "x"},
    ]
    v = sp.view_states(sp.fold_events(evs))["interaction_pause"]
    assert v["active_pause"] is not None
    assert v["active_pause"]["message"] == "确认？"
    assert v["active_pause"]["seq"] == 1


def test_subagent_catalog_lifecycle():
    evs = [
        {"type": "assistant/message", "seq": 1, "tool_calls": [
            {"id": "s1", "function": {"name": "run_subagent",
                                      "arguments": json.dumps(
                                          {"stage": "script_analyze",
                                           "task": "分析剧本"})}}]},
        {"type": "tool/result", "seq": 2, "name": "run_subagent",
         "call_id": "s1", "ok": True, "content": "x"},
        {"type": "assistant/message", "seq": 3, "tool_calls": [
            {"id": "s2", "function": {"name": "run_subagent",
                                      "arguments": json.dumps(
                                          {"stage": "storyboard_shots",
                                           "task": "拆镜"})}}]},
        {"type": "tool/result", "seq": 4, "name": "run_subagent",
         "call_id": "s2", "ok": False, "content": "x"},
    ]
    v = sp.view_states(sp.fold_events(evs))["subagent_catalog"]
    assert [e["status"] for e in v["subagents"]] == ["completed", "failed"]
    assert v["subagents"][0]["stage"] == "script_analyze"


def test_storyboard_counts_only_ok_and_by_type():
    evs = [
        {"type": "assistant/message", "seq": 1, "tool_calls": [
            {"id": "g1", "function": {"name": "storyboard_create_group",
                                      "arguments": json.dumps(
                                          {"group_type": "keyElement",
                                           "title": "Element_程心"})}},
            {"id": "g2", "function": {"name": "storyboard_create_group",
                                      "arguments": json.dumps(
                                          {"group_type": "shot",
                                           "title": "Shot_开场"})}}]},
        {"type": "tool/result", "seq": 2, "name": "storyboard_create_group",
         "call_id": "g1", "ok": True, "content": "x"},
        {"type": "tool/result", "seq": 3, "name": "storyboard_create_group",
         "call_id": "g2", "ok": False, "content": "拒收"},
    ]
    v = sp.view_states(sp.fold_events(evs))["storyboard_progress"]
    assert v["counts"] == {"keyElement": 1, "shot": 0, "audio": 0}
    assert v["recent_titles"] == ["Element_程心"]


def test_chat_tail_cap():
    evs = [{"type": "turn/end", "seq": i, "reason": "done"}
           for i in range(1, 30)]
    v = sp.view_states(sp.fold_events(evs))["chat_tail"]
    assert len(v["tail"]) == sp._CHAT_TAIL_CAP
    assert v["tail"][-1]["seq"] == 29


class _DummySvc:
    def __init__(self, interaction):
        self.state_dict = {"interaction": interaction}


def test_snapshot_asofseq_and_dual_run_diff_log(monkeypatch):
    evs = [_assistant_pause(5),
           {"type": "user/message", "seq": 6, "source": "user",
            "content": "好"},
           {"type": "turn/end", "seq": 7, "reason": "done"}]
    monkeypatch.setattr(sp.session_log, "load_events",
                        lambda svc, cid="": evs)
    msgs = []
    sid = logger.add(lambda m: msgs.append(str(m)), level="WARNING",
                     format="{message}")
    try:
        # 投影已消费（active=None）与权威无暂停一致 → 不告警
        snap = sp.snapshot(_DummySvc({"active_pause": None,
                                      "awaiting_confirmation": False}))
        assert snap["asOfSeq"] == 7
        assert snap["values"]["interaction_pause"]["pause_count"] == 1
        assert snap["values"]["interaction_pause"]["active_pause"] is None
        assert not any("[ProjDiff]" in m for m in msgs)

        # 权威侧有活跃暂停、投影已消费 → 不一致告警（双跑对拍留痕）
        snap2 = sp.snapshot(_DummySvc({"active_pause": {"x": 1},
                                       "awaiting_confirmation": True}))
        assert any("[ProjDiff]" in m for m in msgs)
        assert snap2["values"]["interaction_pause"]["active_pause"] is None
    finally:
        logger.remove(sid)
