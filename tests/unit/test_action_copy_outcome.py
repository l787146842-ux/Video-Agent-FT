# -*- coding: utf-8 -*-
"""动作日志成果语测试（2026-09-06 对齐批）：
describe_fc_tool 产出类动作改成果语（用户视角），低信息机械续读类
在 aggregate_action_log 折叠不进聊天动作日志（trace/审计照记）。"""
from src.video_agent.core.action_descriptions import aggregate_action_log
from src.video_agent.core.fc_feedback import describe_fc_tool


def test_analysis_report_outcome_copy():
    assert describe_fc_tool("script_analysis_report", {}) == "剧本分析已完成"


def test_storyboard_create_group_outcome_copy():
    assert describe_fc_tool("storyboard_create_group", {"title": "主角"}) == "故事板已更新"


def test_generation_tools_outcome_copy():
    assert describe_fc_tool("image_generate", {}) == "已发起生图"
    assert describe_fc_tool("image_generate", {"mode": "single"}) == "已发起单张生图"
    assert describe_fc_tool("generate_video", {}) == "已发起视频生成"


def test_read_skill_keeps_title_brackets_for_grouping():
    desc = describe_fc_tool("read_skill", {"name": "宣言式概念短片"})
    assert desc == "Skill「宣言式概念短片」流程已加载"
    assert "「" in desc, "保留「」结构以兼容聚合正则"


def test_low_info_tools_folded_from_action_log():
    logs = [
        describe_fc_tool("read_skill", {"name": "宣言式概念短片"}),
        describe_fc_tool("list_skills", {}),
        describe_fc_tool("get_skill_asset", {}),
        describe_fc_tool("script_analysis_report", {}),
        describe_fc_tool("script_analysis_report", {}),
    ]
    assert aggregate_action_log(logs) == ["剧本分析已完成 ×2"], "机械续读类整类折叠"


def test_consecutive_grouping_still_works():
    logs = ["故事板已更新", "故事板已更新", "故事板已更新", "写入文档「制片规格.md」"]
    assert aggregate_action_log(logs) == ["故事板已更新 ×3", "写入文档"]
