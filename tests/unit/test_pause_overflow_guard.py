# -*- coding: utf-8 -*-
"""暂停卡两通道契约回归（v2 批4 立，2026-09-21 批B 改写）。

**契约变更（事故 5555/Q4，用户裁决「照搬 dsh」，翻案 2026-08-31「卡问句系统
组装」）**：
- 旧：卡问句恒为系统模板；模型 message 一律进正文通道（模型永不撰写问句）。
- 新：**模型撰写 question**（对齐 dsh `ask_user_question`）当卡问句；
  模型 message 仍进正文通道；模型**未写** question 时**回落系统模板**
  （「「阶段名」已完成，请过目以上成果并选择下一步。」）。

两条不变的红线（本文件继续钉死）：
① **不静默丢弃**——`fc_tool_runner` 记载 2026-09-12 曾有「静默剥离字段造成
   假成功空提示词卡」的闸机被用户裁决删除；本改动同理：宁可回落模板，
   不可丢空卡。模型没写 question 时卡上必须有问句。
② **正文通道不没收**——模型 message 原文照旧进正文，不被吞。
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


def _run(*calls, monkeypatch=None):
    runner = FCToolRunner(tool_manager=_TM())
    if monkeypatch is not None:
        monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    return asyncio.run(runner.execute(_fc(*calls)))


def test_model_message_goes_to_body_channel(monkeypatch):
    """模型 message 原文进正文通道（不被没收、不被塞进问句行）。"""
    long_msg = "✅ 阶段一「剧本分析」已完成。" + "结构化要点内容。" * 30
    res = _run(("workflow_pause", {"message": long_msg}), monkeypatch=monkeypatch)
    assert res.pause_overflow == long_msg, "模型 message 原文必须进正文通道"
    assert long_msg not in res.confirmation, "模型 message 不得进确认通道"


def test_model_question_becomes_card_question(monkeypatch):
    """2026-09-21 批B：模型撰写 question → 它就是卡问句（对齐 dsh）。"""
    res = _run(
        ("workflow_pause", {
            "question": "角色三视图的卡由哪个阶段构建？",
            "message": "本轮已完成关键元素拆分。",
        }),
        monkeypatch=monkeypatch)
    assert res.confirmation == "角色三视图的卡由哪个阶段构建？", \
        "模型撰写的 question 未成为卡问句（批B 契约）"
    assert res.pause_overflow == "本轮已完成关键元素拆分。"
    assert "请过目以上成果" not in res.confirmation, \
        "模型写了 question 时不应再回落系统模板"


def test_missing_question_falls_back_not_silently_dropped(monkeypatch):
    """红线：模型没写 question → 回落系统模板，**绝不留空卡**。

    对齐 2026-09-12 静默剥离事故的教训：宁可回落，不可静默丢。
    """
    res = _run(("workflow_pause", {"message": "请确认"}), monkeypatch=monkeypatch)
    assert res.confirmation, "无 question 时卡问句不得为空（静默丢弃红线）"
    assert "请过目以上成果" in res.confirmation, "缺系统模板回落"
    assert res.pause_overflow == "请确认", "model message 仍进正文通道"


def test_empty_message_still_yields_question(monkeypatch):
    """空 message + 空 question → 仍有系统模板问句（审批事实语义），overflow 空串。"""
    res = _run(("workflow_pause", {"message": ""}), monkeypatch=monkeypatch)
    assert res.pause_overflow == ""
    assert "请过目以上成果" in res.confirmation


def test_system_question_carries_stage_label(monkeypatch):
    """回落模板带真实阶段标签（同批先跑 script_analyze → 「剧本分析」）。"""
    long_msg = "成果dump。" * 60
    res = _run(
        ("script_analyze", {"skill_name": "任意"}),
        ("workflow_pause", {"message": long_msg}),
        monkeypatch=monkeypatch)
    assert "「剧本分析」已完成" in res.confirmation
    assert res.pause_overflow == long_msg


def test_question_level_fields_propagate(monkeypatch):
    """2026-09-21 批B：header / detail / multi_select 随结果上抛（对齐 dsh）。"""
    res = _run(
        ("workflow_pause", {
            "question": "选哪个方向？",
            "header": "选择模式",
            "detail": "这会决定后续所有镜头的基调。",
            "multi_select": True,
        }),
        monkeypatch=monkeypatch)
    assert res.pause_header == "选择模式"
    assert res.pause_detail == "这会决定后续所有镜头的基调。"
    assert res.pause_multi_select is True


def test_defaults_for_question_level_fields(monkeypatch):
    """未提供问题级字段 → 空/False（缺省不伪造，前端按缺省渲染）。"""
    res = _run(("workflow_pause", {"message": "确认"}), monkeypatch=monkeypatch)
    assert res.pause_header == ""
    assert res.pause_detail == ""
    assert res.pause_multi_select is False
