# -*- coding: utf-8 -*-
"""暂停卡两通道契约回归（v2 批4 立，2026-09-21 批B/批F 改写）。

**契约变更（事故 5555/Q4，用户裁决「照搬 dsh」，翻案 2026-08-31「卡问句系统
组装」）**：
- 旧：卡问句恒为系统模板；模型 message 一律进正文通道（模型永不撰写问句）。
- 新：**模型撰写 question**（对齐 dsh `ask_user_question`）当卡问句；
  模型 message 仍进正文通道；模型**未写** question 时**回落系统模板**
  （「「阶段名」已完成，请过目以上成果并选择下一步。」）。

**批F 追加（事故 4444/Q2③+Q3）**：暂停卡由「一个问题」扩为「一次可问 N 个
问题」（对齐 dsh `questions[]`）。4444 实证：模型有 5 个维度要问，手上只有
一个扁平 options + 一个 multi_select，只能自创"套餐"把前四维压成互斥预设、
把第五维塞进 detail（detail 非可选项 → **用户结构上答不了** → 模型自判
「未回复即遵循原文」并把它写成了既定规格）。本组钉死 questions[] 层：
N 问各有自己的问句/选项/多选标志；**扁平形态不废除**（回落保留）；
缺问句的项回落模板**不丢项**。

三条不变的红线（本文件继续钉死）：
① **不静默丢弃**——`fc_tool_runner` 记载 2026-09-12 曾有「静默剥离字段造成
   假成功空提示词卡」的闸机被用户裁决删除；本改动同理：宁可回落模板，
   不可丢空卡。模型没写 question 时卡上必须有问句。
② **正文通道不没收**——模型 message 原文照旧进正文，不被吞。
③ **暂停卡不为空**——任何输入组合下都至少有一个问题。
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
    """回落模板带真实阶段标签（同批先跑 script_analyze → 「素材分析」）。"""
    long_msg = "成果dump。" * 60
    res = _run(
        ("script_analyze", {"skill_name": "任意"}),
        ("workflow_pause", {"message": long_msg}),
        monkeypatch=monkeypatch)
    assert "「素材分析」已完成" in res.confirmation
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


# ---------- 批F：问题级列表（事故 4444/Q2③+Q3） ----------

def test_flat_fields_produce_single_question(monkeypatch):
    """旧扁平形态 → 单元素问题列表（**旧形态不废除**，消费方零改动）。

    4444 实证：模型有 5 个维度要问，只有一组扁平 options + 一个 multi_select，
    第 5 维只能塞 detail（非可选项 → 用户答不了 → 被写成既定规格）。
    批F 补 questions[] 层，但扁平形态必须继续可用（回落保留）。
    """
    res = _run(
        ("workflow_pause", {
            "question": "选哪个？", "header": "选择", "detail": "说明",
            "options": [{"label": "A"}, {"label": "B", "group": "g"}],
        }),
        monkeypatch=monkeypatch)
    assert len(res.pause_questions) == 1, "扁平形态应归一为单个问题"
    q = res.pause_questions[0]
    assert q["question"] == "选哪个？"
    assert q["header"] == "选择"
    assert q["detail"] == "说明"
    assert [o["label"] for o in q["options"]] == ["A", "B"]
    # 首问投影兼容位同步（既有消费方读 pause_header 等仍拿到首问的值）
    assert res.pause_header == "选择"
    assert res.confirmation == "选哪个？"


def test_questions_layer_carries_n_questions(monkeypatch):
    """questions[] 非空 → 一次问 N 个问题，各带自己的问句/选项/多选标志。

    这是 4444/Q2③ 的正解：模型不必再自创"套餐"，每维一问、各问各答。
    """
    res = _run(
        ("workflow_pause", {
            "questions": [
                {"id": "ratio", "question": "画幅选哪个？",
                 "options": [{"label": "16:9"}, {"label": "9:16"}]},
                {"id": "naming", "question": "二向箔是否在台词中显名？",
                 "header": "显名", "detail": "台词里是否直呼其名。",
                 "multi_select": False,
                 "options": [{"label": "显名"}, {"label": "不显名"}]},
            ],
            "message": "请一并确认。",
        }),
        monkeypatch=monkeypatch)
    assert len(res.pause_questions) == 2, "两问应各成一项（4444/Q2③ 正解）"
    assert res.pause_questions[0]["id"] == "ratio"
    assert res.pause_questions[1]["id"] == "naming"
    assert res.pause_questions[1]["header"] == "显名"
    assert res.pause_questions[1]["detail"] == "台词里是否直呼其名。"
    # 各问选项不串台
    assert [o["label"] for o in res.pause_questions[0]["options"]] == ["16:9", "9:16"]
    assert [o["label"] for o in res.pause_questions[1]["options"]] == ["显名", "不显名"]
    # 首问投影：确认通道 = 首问问句（旧消费方仍可用）
    assert res.confirmation == "画幅选哪个？"
    assert res.pause_overflow == "请一并确认。"


def test_question_missing_text_falls_back_not_dropped(monkeypatch):
    """红线：某问缺 question 文本 → 回落阶段模板，**绝不丢项**。

    同 2026-09-12 静默剥离事故教训：宁可回落，不可静默丢（该问的选项仍可答）。
    """
    res = _run(
        ("workflow_pause", {
            "questions": [
                {"id": "a", "question": ""},
                {"id": "b", "question": "第二问？", "options": [{"label": "X"}]},
            ],
        }),
        monkeypatch=monkeypatch)
    assert len(res.pause_questions) == 2, "缺问句的项被丢掉了（静默丢弃红线）"
    assert "请过目以上成果" in res.pause_questions[0]["question"], "缺系统模板回落"
    assert res.pause_questions[1]["question"] == "第二问？"


def test_question_without_id_gets_generated_id(monkeypatch):
    """模型没给 id → 系统补 q1/q2…（回答回携需要稳定标识）。"""
    res = _run(
        ("workflow_pause", {"questions": [
            {"question": "第一问？"}, {"question": "第二问？"},
        ]}),
        monkeypatch=monkeypatch)
    assert res.pause_questions[0]["id"] == "q1"
    assert res.pause_questions[1]["id"] == "q2"


def test_empty_questions_list_falls_back_to_flat(monkeypatch):
    """questions 为空列表 → 回落扁平形态（视为未提供，不产出空卡）。"""
    res = _run(
        ("workflow_pause", {"questions": [], "question": "扁平问句？"}),
        monkeypatch=monkeypatch)
    assert len(res.pause_questions) == 1
    assert res.pause_questions[0]["question"] == "扁平问句？"


def test_question_multi_select_is_per_question(monkeypatch):
    """multi_select 是**每问独立**的（4444/Q3①：全局单选装不下多维度问题）。"""
    res = _run(
        ("workflow_pause", {"questions": [
            {"question": "单选问？", "multi_select": False},
            {"question": "多选问？", "multi_select": True},
        ]}),
        monkeypatch=monkeypatch)
    assert res.pause_questions[0]["multi_select"] is False
    assert res.pause_questions[1]["multi_select"] is True


def test_multi_question_defaults_to_empty_list(monkeypatch):
    """完全无问题级输入 → 仍产出单问（不产出空列表，卡不为空）。"""
    res = _run(("workflow_pause", {"message": "确认"}), monkeypatch=monkeypatch)
    assert len(res.pause_questions) == 1, "暂停卡必须至少有一个问题（不空卡）"
    assert "请过目以上成果" in res.pause_questions[0]["question"]
