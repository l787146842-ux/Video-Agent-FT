# -*- coding: utf-8 -*-
"""三通道分离 B 回归（v2 批4）：workflow_pause 只提交审批事实。

契约：确认通道 = 系统组装问句（带真实阶段标签）；模型原文一律进
正文通道（pause_overflow），无阈值补丁——通道分离是契约不是压缩。
不没收暂停与选项。
"""
import asyncio
import json

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.tools.base import ToolResult


class _TM:
    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})

    def get_tool(self, name):
        """确认闸双保险（ctx.tool_risk_of 经 get_tool().risk 读数）的最小桩：
        桩内工具一律声明 low（只读桩）。"""
        return type("_StubTool", (), {"risk": "low"})


def _fc(*calls):
    return ChatResponse(content="", tool_calls=[
        {"id": f"c{i}", "type": "function",
         "function": {"name": n, "arguments": json.dumps(a)}}
        for i, (n, a) in enumerate(calls)
    ])


def _unpack(res):
    (applied, confirmation, _urls, _inserts, _log, opts,
     _tr, _docs, _warn, overflow, _pause_id) = res
    return applied, confirmation, opts, overflow


def test_model_dump_goes_to_body_channel(monkeypatch):
    """模型 dump 成果 → 卡问句系统组装，原文进第 10 元组（正文通道）。"""
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    long_msg = "✅ 阶段一「剧本分析」已完成。" + "结构化要点内容。" * 30
    _applied, confirmation, _opts, overflow = _unpack(asyncio.run(
        runner.execute(_fc(("workflow_pause", {"message": long_msg})))))
    assert overflow == long_msg
    assert "已完成" in confirmation and "请过目以上成果" in confirmation
    assert long_msg not in confirmation, "模型原文不得进确认通道"


def test_system_question_carries_stage_label(monkeypatch):
    """同批先跑 script_analyze → 系统问句带真实阶段标签「剧本分析」。"""
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


def test_empty_model_message_still_system_question(monkeypatch):
    """v2：无模型原文也发系统问句（审批事实语义），overflow 为空串。"""
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    _applied, confirmation, _opts, overflow = _unpack(asyncio.run(
        runner.execute(_fc(("workflow_pause", {"message": ""})))))
    assert overflow == ""
    assert "请过目以上成果" in confirmation
