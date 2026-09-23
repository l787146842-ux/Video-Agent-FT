# -*- coding: utf-8 -*-
"""动作日志成果语测试（2026-09-06 对齐批）：
describe_fc_tool 产出类动作改成果语（用户视角），低信息机械续读类
在 aggregate_action_log 折叠不进聊天动作日志（trace/审计照记）。"""
from src.video_agent.core.action_descriptions import aggregate_action_log
from src.video_agent.core.fc_feedback import describe_fc_tool


def test_analysis_report_outcome_copy():
    assert describe_fc_tool("script_analysis_report", {}) == "素材分析已完成"


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
    assert aggregate_action_log(logs) == ["素材分析已完成 ×2"], "机械续读类整类折叠"


def test_todo_write_has_outcome_copy():
    """2026-09-23 批13：`todo_write` 必须登记成果语（4444 实跑漏登记取证）。

    批8 新增本工具时只加进注册表、没加进本表 ⇒ 动作日志回落通用兜底句
    「执行工具 todo_write（累计失败 N 次）」，**英文工具名裸奔给用户**
    （与 4444/C-1 的 `storyboard_patch_group` 漏登记是同一个病）。
    """
    r = describe_fc_tool("todo_write", {"todos": [
        {"content": "A", "status": "completed"},
        {"content": "B", "status": "in_progress"}]})
    assert r == "更新任务进度清单（1 项进行中）", r
    assert "todo_write" not in r, "英文工具名不得进用户可见文案"
    # 无 in_progress 时不带计数（形态稳定，聚合正则 _TITLE_RE 不依赖括号）
    assert describe_fc_tool("todo_write", {"todos": [
        {"content": "A", "status": "completed"}]}) == "更新任务进度清单"
    # 非法/缺失入参安全回落，不得抛错（本函数在工具执行前调用）
    assert describe_fc_tool("todo_write", {}) == "更新任务进度清单"
    assert describe_fc_tool("todo_write", {"todos": "not-a-list"}) == "更新任务进度清单"


def test_consecutive_grouping_still_works():
    logs = ["故事板已更新", "故事板已更新", "故事板已更新", "写入文档「制片规格.md」"]
    assert aggregate_action_log(logs) == ["故事板已更新 ×3", "写入文档"]
