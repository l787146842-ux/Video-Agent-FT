# -*- coding: utf-8 -*-
"""③ 分工声明的回归钉（事故编号：9999）。
2026-10-08 批（用户裁决「把分工弄对、文案写清楚」）。
"""
from src.video_agent.core import subagent as subagent_mod
from src.video_agent.tools.document_tools import _stage_hint


def test_9999_stage_scope_declares_media_boundary():
    """③-a：媒体生成阶段必须声明分工边界（写提示词 vs 出图）。"""
    sc = subagent_mod.stage_scope_contract("media_generate")
    assert sc, "media_generate 必须有分工边界声明（9999 思考打架根因）"
    assert "写提示词" in sc, "必须写明本阶段做的是写提示词"
    assert "主线程" in sc or "主代理" in sc, "必须写明出图归主线程"


def test_9999_stage_scope_is_positive_and_structural():
    """③-b：声明是**结构事实**，不是新散文禁令（P2/G3）。"""
    sc = subagent_mod.stage_scope_contract("media_generate")
    for banned in ("不得", "禁止", "不要", "不允许"):
        assert banned not in sc, f"分工声明不得含禁令词 {banned!r}（G3 禁区）"
    # 声明的依据必须真实存在于结构里（不是写一句话让模型配合）
    stage_tools = subagent_mod.stage_tools("media_generate")
    assert "storyboard_add_draft" in stage_tools
    assert "storyboard_patch_draft" in stage_tools
    assert "image_generate" not in stage_tools, "出图工具不该在子代理工具面"
    assert "generate_video" not in stage_tools
    deny = subagent_mod.SUBAGENT_TOOL_DENY
    assert {"image_generate", "generate_video", "workflow_pause"} <= deny


def test_9999_stage_scope_only_for_media_generate():
    """③-c：只对 media_generate 出句（其余阶段零变化，不误伤）。"""
    assert subagent_mod.stage_scope_contract("") == ""
    assert subagent_mod.stage_scope_contract("script_analyze") == ""
    assert subagent_mod.stage_scope_contract("storyboard_design") == ""
    assert subagent_mod.stage_scope_contract("no_such_stage") == ""


def test_9999_stage_hint_renders_scope_and_card_limits():
    """③-d：分工声明必须真的到达模型可见面（stage 入参描述）。"""
    hint = _stage_hint()
    assert "分工边界" in hint, "stage 描述必须渲染分工边界段"
    assert "真正花钱的出图与出视频由主代理在主线程直调" in hint
    assert "对新建草稿卡的限定" in hint, "原有建卡限定不得被挤掉"


def test_9999_policy_text_states_media_split():
    """③-e：委派策略段必须写明「委派的是写、主线程做的是生成」。"""
    from src.video_agent.core.subagent import subagent_policy
    pol = subagent_policy()
    assert "写" in pol and "主线程" in pol, \
        "SUBAGENT_POLICY 必须写明媒体生成边界（9999 两条规则打架处）"
    # 旧表述「花钱生成不委派」曾与「可委派阶段主代理不直接调用」并列而无边界，
    # 是 9999 反复自我辩论的直接来源；新表述给出边界。
    assert "媒体生成阶段的边界" in pol
    # 4444/Q2① 钉子：不得回潮内部机制词（平台词会被模型当事实复述）
    for leak in ("建卡", "字段怎么写", "交不交提示词", "几个场景"):
        assert leak not in pol, f"回潮内部机制词 {leak!r}（4444/Q2①）"
