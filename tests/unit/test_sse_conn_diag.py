# -*- coding: utf-8 -*-
"""SseConnDiag 连接级诊断计数（D2 批 commit1）单测。

钉死：① 帧/心跳/seq 高水位计数口径；② close 幂等（首因锁定，finally 兜底
不覆盖明确原因）；③ 无 seq 旧帧只计数不炸。纯计数类，零控制流参与。
"""
from loguru import logger

from src.video_agent.web.sse_conn_diag import SseConnDiag


def test_frame_and_heartbeat_counts():
    d = SseConnDiag("t-1")
    d.note_frame(3)
    d.note_frame(5)
    d.note_frame(4)  # 乱序不回落高水位
    d.note_heartbeat()
    d.note_heartbeat()
    assert d.frames == 3
    assert d.heartbeats == 2
    assert d.last_seq == 5


def test_legacy_frame_without_seq_only_counts():
    d = SseConnDiag("t-2")
    d.note_frame(None)
    d.note_frame("nonsense")  # 旧帧/脏值只计数不炸
    assert d.frames == 2
    assert d.last_seq == 0


def test_close_idempotent_first_reason_wins():
    d = SseConnDiag("t-3")
    d.note_frame(1)
    d.close("terminal:done")
    d.close("generator_exit")  # finally 兜底不得覆盖明确首因
    assert d.closed_by == "terminal:done"


def test_close_emits_log_line():
    msgs = []
    sid = logger.add(lambda m: msgs.append(str(m)), level="INFO", format="{message}")
    try:
        d = SseConnDiag("t-4")
        d.note_frame(7)
        d.close("client_disconnected")
    finally:
        logger.remove(sid)
    text = "".join(msgs)
    assert "[SseDiag]" in text
    assert "task=t-4" in text
    assert "close=client_disconnected" in text
    assert "last_seq=7" in text
