# -*- coding: utf-8 -*-
"""三通道分离 B 回归：pause message 超长机械压缩，原文进正文通道。

契约：workflow_pause.message = 一句确认问句；模型仍 dump 成果
（>PAUSE_MSG_MAX）时确定性变换——卡片留系统短问句（带真实阶段标签），
原文经 pause_overflow 随正文下发，不丢信息、不没收暂停。
"""
import asyncio
import json

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner, PAUSE_MSG_MAX
from src.video_agent.tools.base import ToolResult


class _TM:
    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})


def _fc(*calls):
    return ChatResponse(content="", tool_calls=[
        {"id": f"c{i}", "type": "function",
         "function": {"name": n, "arguments": json.dumps(a)}}
        for i, (n, a) in enumerate(calls)
    ])


def _unpack(res):
    (applied, confirmation, _urls, _inserts, _log, opts,
     _tr, _docs, _warn, overflow) = res
    return applied, confirmation, opts, overflow


def test_long_pause_message_compressed_and_overflow_carried(monkeypatch):
    """超 220 字 → confirmation 压缩为系统短问句，原文进第 10 元组。"""
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    long_msg = "✅ 阶段一「剧本分析」已完成。" + "结构化要点内容。" * 30
    assert len(long_msg) > PAUSE_MSG_MAX
    _applied, confirmation, _opts, overflow = _unpack(asyncio.run(
        runner.execute(_fc(("workflow_pause", {"message": long_msg})))))
    assert overflow == long_msg
    assert len(confirmation) <= PAUSE_MSG_MAX
    assert "已完成" in confirmation and "请过目以上成果" in confirmation


def test_short_question_carries_stage_label(monkeypatch):
    """同批先跑 script_analyze → 短问句带真实阶段标签「剧本分析」。"""
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    long_msg = "成果dump。" * 60
    _applied, confirmation, _opts, overflow = _unpack(asyncio.run(
        runner.execute(_fc(
            ("script_analyze", {"skill_name": "任意"}),
            ("workflow_pause", {"message": long_msg}),
        ))))
    assert "「剧本分析」已完成" in confirmation
    assert overflow == long_msg


def test_short_pause_message_untouched(monkeypatch):
    """≤220 字 → 原样保留，overflow 为空（契约内不干预）。"""
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    msg = "请确认分析结果，并选择下一步。"
    _applied, confirmation, _opts, overflow = _unpack(asyncio.run(
        runner.execute(_fc(("workflow_pause", {"message": msg})))))
    assert confirmation == msg
    assert overflow == ""
