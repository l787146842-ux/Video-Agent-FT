# -*- coding: utf-8 -*-
"""主代理/子代理工具面契约（2026-11-12 宽权限批）。

新口径：
① 主代理不再被 MAIN_AGENT_DENY 拿掉创作/故事板写入工具；
② 子代理只保留安全 deny（递归/花钱/确认/导出/用户交互），不再按阶段裁工具；
③ 阶段名只作展示/遥测；
④ 轮内 excluded 误调仍拒执行；
⑤ 非法 stage 仍 fail-loud。
"""
import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.subagent import (
    PIPELINE_STAGE_KINDS, SUBAGENT_TOOL_DENY, child_deny_set,
)
from src.video_agent.state.manager import StateManager


SKILL = "演示阶段技能"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    from src.video_agent.tools.analysis_tools import register_analysis_tools
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()


def test_main_agent_has_production_tools(svc):
    """主代理保留创作/故事板写入工具；只裁子代理专属打卡工具。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    excluded = planner._compute_excluded_tools(PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True))
    for t in ("script_analysis_report", "storyboard_create_group",
              "storyboard_delete_group", "storyboard_delete_draft",
              "storyboard_patch_group", "storyboard_add_draft",
              "storyboard_patch_draft", "read_uploaded_doc",
              "read_skill", "read_file", "read_image"):
        assert t not in excluded, f"{t} 不应再被主代理裁剪"
    assert "structured_output" in excluded
    assert "image_generate" not in excluded
    assert "generate_video" not in excluded
    assert "workflow_pause" not in excluded


def test_child_deny_is_safety_only():
    """子代理只保留安全 deny；阶段不再决定工具面。"""
    for stage in ("", "media_generate", "storyboard_design", "script_analyze",
                  "未知阶段"):
        deny = child_deny_set(stage)
        assert deny == SUBAGENT_TOOL_DENY
        assert "run_subagent" in deny
        assert "image_generate" in deny and "generate_video" in deny
        assert "workflow_pause" in deny
        assert "video_assembler" in deny
        assert "storyboard_confirm_draft" in deny
        assert "storyboard_media_to_chat" in deny
        for t in ("storyboard_create_group", "storyboard_add_draft",
                  "script_analysis_report", "read_skill", "read_file"):
            assert t not in deny


def test_child_gets_storyboard_tools(svc):
    """子代理继承创作工具，不再按阶段收走。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    excluded = planner._compute_excluded_tools(PlannerContext(
        skill_name=SKILL, subagent_depth=1, use_studio_context=True,
        subagent_deny=child_deny_set("storyboard_design")))
    for t in ("storyboard_create_group", "storyboard_delete_group",
              "storyboard_delete_draft", "storyboard_patch_group",
              "storyboard_add_draft", "storyboard_patch_draft",
              "read_skill", "read_file"):
        assert t not in excluded
    assert "image_generate" in excluded
    assert "workflow_pause" in excluded


def test_pipeline_stage_kinds_are_display_only():
    """阶段枚举保留用于展示/遥测，不再驱动工具裁剪。"""
    assert PIPELINE_STAGE_KINDS == frozenset({
        "script_analyze", "storyboard_design", "media_generate"})


def test_free_chat_no_prune(svc):
    planner = Planner(state_manager=svc, llm_adapter=None)
    excluded = planner._compute_excluded_tools(PlannerContext(
        skill_name="", subagent_depth=0, use_studio_context=True))
    assert "read_uploaded_doc" not in excluded
    assert "storyboard_create_group" not in excluded
    assert "read_skill" not in excluded


def test_adjust_scope_no_prune(svc):
    planner = Planner(state_manager=svc, llm_adapter=None)
    excluded = planner._compute_excluded_tools(PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True,
        adjust_scope={"group_id": "g1", "draft_id": "d1"}))
    for t in ("read_uploaded_doc", "storyboard_create_group",
              "storyboard_patch_draft", "read_draft"):
        assert t not in excluded


async def test_turn_excluded_rejects_execution():
    runner = FCToolRunner(tool_manager=object())
    runner.turn_excluded = frozenset({"read_uploaded_doc", "storyboard_create_group"})
    res = await runner._dispatch_tool("read_uploaded_doc", {"name": "剧本.md"})
    assert res.success is False and res.error_code == "validation"
    res2 = await runner._dispatch_tool("storyboard_create_group", {"title": "T"})
    assert res2.success is False and res2.error_code == "validation"


async def test_invalid_stage_fail_loud():
    runner = FCToolRunner(tool_manager=object())
    launched = []

    async def launcher(task, kind="", stage="", current_step="", on_event=None):
        launched.append({"task": task, "stage": stage})
        return "ok"

    runner.subagent_launcher = launcher
    res = await runner._dispatch_tool(
        "run_subagent", {"task": "T", "stage": "不存在的阶段"})
    assert res.success is False
    assert res.error_code == "validation"
    assert "PIPELINE_STAGE_KINDS" in res.error or "可委派阶段" in res.error
    assert len(launched) == 0

    res2 = await runner._dispatch_tool(
        "run_subagent", {"task": "T2", "stage": "script_analyze"})
    assert res2.success is True
    assert len(launched) == 1
    assert launched[0]["stage"] == "script_analyze"
