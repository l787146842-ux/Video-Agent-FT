# -*- coding: utf-8 -*-
"""阶段分工/建卡限定退役回归（2026-11-12 宽权限批）。

旧 9999 事故的「写提示词 vs 出图」边界不再由平台按阶段渲染；改由
Skill 散文 + 主代理判断。平台只保留花钱/确认/导出安全边界。
"""
from src.video_agent.core import subagent as subagent_mod
from src.video_agent.tools.document_tools import _stage_hint


def test_stage_scope_contract_retired():
    for stage in ("", "media_generate", "script_analyze",
                  "storyboard_design", "no_such_stage"):
        assert subagent_mod.stage_scope_contract(stage) == ""


def test_stage_card_contract_retired():
    for stage in ("", "storyboard_design", "media_generate"):
        assert subagent_mod.stage_card_contract(stage) == ""


def test_stage_hint_is_display_only():
    hint = _stage_hint()
    assert "script_analyze" in hint and "storyboard_design" in hint
    assert "分工边界" not in hint
    assert "对新建草稿卡的限定" not in hint
    assert "技能内容由你在 task 里提供" in hint


def test_policy_text_states_safety_boundary_only():
    pol = subagent_mod.subagent_policy()
    assert "安全边界" in pol
    assert "image_generate" in pol and "generate_video" in pol
    assert "media_generate" not in pol
    for leak in ("建卡", "字段怎么写", "交不交提示词", "几个场景"):
        assert leak not in pol
