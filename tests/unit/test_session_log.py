# -*- coding: utf-8 -*-
"""会话事件流（v4 主刀批 E1）回归：
- append/load 往返 + seq 单调；
- derive_messages：surface 推导顺序、步回喂模板派生、pruned_from 就地替换、
  replaces_seqs 压缩折叠、log/rewind 截面、悬挂 tool_calls 补位；
- migrate_from_chat_messages：一次性导入 + 幂等 + mechanical/卡片过滤；
- load_history D4 回落（日志通道异常 → None）。
设计依据 docs/会话层append-only化细案.md。
"""
import json

import pytest

from src.video_agent.core import session_log
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    StateManager._instance = instance
    # 清掉 demo 种子消息：迁移/装载口径确定性（chatMessages 指向活跃会话列表）
    instance._raw_state.get("chatMessages") or instance._raw_state.setdefault("chatMessages", [])
    if isinstance(instance._raw_state.get("chatMessages"), list):
        instance._raw_state["chatMessages"].clear()
    yield instance
    StateManager.reset_instance()
    session_log._SEQ_CACHE.clear()


def _write_raw(svc, events, cid="conv-main"):
    path = session_log.log_path(svc, cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                    encoding="utf-8")


# ---------- append/load 往返 ----------


def test_append_load_roundtrip_and_seq_monotonic(svc):
    session_log.append_user_message(svc, "", "你好")  # cid 空 → 活跃会话
    session_log.append_assistant_message(svc, "", 1, "在", usage={"prompt_tokens": 10})
    session_log.append_tool_result(svc, "", 1, "c1", "read_skill", "全文…", ok=True)
    events = session_log.load_events(svc, "")
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert events[1].get("tool_calls") in ([], None)
    assert events[2]["call_id"] == "c1" and events[2]["ok"] is True
    assert events[0]["type"] == "user/message"
    assert session_log.log_path(svc, "").exists()


# ---------- derive_messages ----------


def _base_events():
    return [
        {"seq": 1, "type": "user/message", "content": "开始"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read_skill", "arguments": "{}"}}]},
        {"seq": 3, "type": "tool/result", "step": 1, "call_id": "c1", "name": "read_skill",
         "content": "章节全文"},
        {"seq": 4, "type": "step/feedback", "step": 1, "tool_count": 1},
        {"seq": 5, "type": "assistant/message", "step": 2, "content": "完成"},
    ]


def test_derive_messages_surface_order_and_step_feedback(svc):
    msgs = session_log.derive_messages(_base_events())
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "user", "assistant"]
    assert msgs[1]["tool_calls"][0]["id"] == "c1"
    assert msgs[2]["tool_call_id"] == "c1"
    assert "第 1 轮" in msgs[3]["content"] and "1 个 Tool" in msgs[3]["content"]
    assert msgs[4]["content"] == "完成"


def test_derive_pruned_from_replaces_in_place(svc):
    events = _base_events() + [
        {"seq": 6, "type": "tool/result", "step": 1, "pruned_from": 3,
         "content": "头…[... 中略 ...]…尾"},
    ]
    msgs = session_log.derive_messages(events)
    assert msgs[2]["content"] == "头…[... 中略 ...]…尾"
    assert len(msgs) == 5  # 不新增节点，只就地替换


def test_derive_replaces_seqs_compaction_checkpoint(svc):
    events = _base_events() + [
        {"seq": 6, "type": "user/message", "replaces_seqs": [1, 2, 3, 4],
         "content": "<compacted-summary>早期摘要</compacted-summary>"},
    ]
    msgs = session_log.derive_messages(events)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "<compacted-summary>早期摘要</compacted-summary>"
    assert msgs[1]["content"] == "完成"  # 保留尾不受影响


def test_derive_rewind_drops_tail_from_marker(svc):
    events = [
        {"seq": 1, "type": "user/message", "content": "第一轮"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "答1"},
        {"seq": 3, "type": "log/rewind", "to_seq": 0},
        {"seq": 4, "type": "user/message", "content": "第二轮（重答）"},
    ]
    msgs = session_log.derive_messages(events)
    assert [m["content"] for m in msgs] == ["第二轮（重答）"]


def test_derive_patches_dangling_tool_calls(svc):
    """用户停止/取消轮：assistant(tool_calls) 无配对结果 → 派生补占位
    （满足供应商「call 必有 result」硬约束），且补位紧跟连续 tool 块之后。"""
    events = [
        {"seq": 1, "type": "user/message", "content": "开始"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}}]},
        {"seq": 3, "type": "tool/result", "step": 1, "call_id": "c1", "name": "a", "content": "ok"},
        {"seq": 4, "type": "user/message", "content": "继续"},
    ]
    msgs = session_log.derive_messages(events)
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "tool", "user"]
    assert msgs[2]["tool_call_id"] == "c1" and msgs[2]["content"] == "ok"
    assert msgs[3]["tool_call_id"] == "c2" and "未执行完成" in msgs[3]["content"]


# ---------- 迁移（细案 §六） ----------


def test_migrate_imports_nominal_messages_and_idempotent(svc):
    svc.add_chat_message("user", "第一问")
    svc.add_chat_message("agent", "第一答", reasoning_content="思考")
    svc.add_chat_message("agent", "", image_urls=["http://x/1.png"])  # 卡片：空正文跳过
    svc.add_chat_message("user", "机械流水", kind="mechanical")  # mechanical 跳过
    svc.add_chat_message("user", "第二问")

    assert session_log.migrate_from_chat_messages(svc, "") is True
    assert session_log.migrate_from_chat_messages(svc, "") is False  # 幂等（文件已存在）

    msgs = session_log.derive_messages(session_log.load_events(svc, ""))
    assert [m["content"] for m in msgs] == ["第一问", "第一答", "第二问"]
    assert msgs[1].get("reasoning_content") == "思考"
    marker = session_log.load_events(svc, "")[-1]
    assert marker["type"] == "log/imported" and marker["source"] == "chatMessages"


# ---------- 装载与 D4 回落 ----------


@pytest.mark.allow_degradation
def test_load_history_returns_list_and_none_on_channel_failure(svc):
    svc.add_chat_message("user", "历史问")
    svc.add_chat_message("agent", "历史答")
    hist = session_log.load_history(svc, "")
    assert hist is not None and [m["content"] for m in hist] == ["历史问", "历史答"]

    def _boom(*_a, **_k):
        raise RuntimeError("日志通道故障")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(session_log, "migrate_from_chat_messages", _boom)
    try:
        assert session_log.load_history(svc, "") is None  # D4：回落信号
    finally:
        monkey.undo()


@pytest.mark.allow_degradation
def test_corrupt_line_stops_at_last_complete_event(svc, tmp_path):
    """写入中断（半行）止于最后完整事件；续写不重号。劣化告警为有意注入。"""
    _write_raw(svc, [
        {"seq": 1, "type": "user/message", "content": "完整事件"},
    ])
    path = session_log.log_path(svc, "")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq":2,"type":"user/mess')  # 半行（写入中断）
    events = session_log.load_events(svc, "")
    assert [e["seq"] for e in events] == [1]
    # 后续 append 从最后完整事件续排，不重号
    ev = session_log.append_user_message(svc, "", "续写")
    assert ev["seq"] == 2
