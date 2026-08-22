"""doc_written 即显事件 turn_id 打戳回归（六轮 S5/N4a）。

钉死：透传层（chat_cards._stamp_doc_written，任务 #12 自 chat_service 等价归位）
给 doc_written 事件打戳本轮
turn_id——前端即显卡与 done 主消息同 turnId 严格归组，不再依赖相邻兜底。
"""
from src.video_agent.core.sse_events import SSE_DOC_WRITTEN
from src.video_agent.web.chat_cards import _stamp_doc_written


def test_stamp_adds_turn_id_to_payload():
    out = _stamp_doc_written({"type": SSE_DOC_WRITTEN, "name": "规格.md"}, "t-abc")
    assert out["type"] == SSE_DOC_WRITTEN
    assert out["name"] == "规格.md"
    assert out["turn_id"] == "t-abc"


def test_stamp_handles_missing_payload():
    out = _stamp_doc_written(None, "t-xyz")
    assert out["type"] == SSE_DOC_WRITTEN
    assert out["turn_id"] == "t-xyz"


def test_stamp_does_not_mutate_source_payload():
    src = {"type": SSE_DOC_WRITTEN, "name": "a.md"}
    _stamp_doc_written(src, "t-1")
    assert "turn_id" not in src  # 打戳产出新 dict，不改事件源
