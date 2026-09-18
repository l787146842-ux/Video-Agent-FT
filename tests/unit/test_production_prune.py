# -*- coding: utf-8 -*-
"""主代理工具面契约单测（2026-09-18 工具全还批更新）。

钉死断言：
① 顶级生产轮主代理持全量生产工具面（PRODUCTION_MAIN_PRUNE 裁剪已退役）；
② 子级面持生产工具（script_analyze 子级可调 read_uploaded_doc、
   key_elements 子级可调 storyboard_create_group）；
③ adjust_scope 不裁剪（微调子对话保留 patch/read 工具）；
④ 轮内 excluded 误调拒执行（one visibility = one permission）；
⑤ stage 映射缺失 fail-loud（装载期校验）；
⑥ 非法 stage fail-loud 拒收。
"""
import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core import planner as pmod
from src.video_agent.core import subagent as subagent_mod
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.subagent import (
    PIPELINE_STAGE_KINDS, _STAGE_TOOLS, SUBAGENT_TOOL_DENY,
    child_deny_set, stage_tools,
)
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult


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


# ---------- ① 顶级生产轮面 = 主线程集 ----------

def test_top_level_production_no_prune(svc):
    """工具全还（2026-09-18 用户裁决）：顶级生产轮主代理持全量生产工具面，
    PRODUCTION_MAIN_PRUNE 裁剪已退役——可委派阶段工具与回读两件套均不再裁。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True)
    excluded = planner._compute_excluded_tools(ctx)

    # 可委派阶段生产工具不再裁（主代理可亲做，委派改由协议引导）
    for stage, tools in _STAGE_TOOLS.items():
        for t in tools:
            assert t not in excluded, f"{t} (stage={stage}) 不应再被裁剪"
    # 回读两件套不再裁
    assert "read_draft" not in excluded
    assert "view_storyboard_media" not in excluded
    # 故事板建组工具与 read_skill 不裁
    assert "storyboard_create_group" not in excluded
    assert "read_skill" not in excluded
    # 主线程工具保留
    assert "run_subagent" not in excluded
    assert "workflow_pause" not in excluded
    assert "read_state_group" not in excluded
    assert "document_write" not in excluded
    assert "image_generate" not in excluded
    assert "generate_video" not in excluded
    # structured_output 仍子代理专属（主代理面裁）
    assert "structured_output" in excluded


def test_free_chat_no_prune(svc):
    """自由对话（无 skill）不裁剪：全工具面保留。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(skill_name="", subagent_depth=0, use_studio_context=True)
    excluded = planner._compute_excluded_tools(ctx)
    # 无 skill → 不触发生产裁剪
    assert "read_uploaded_doc" not in excluded
    assert "storyboard_create_group" not in excluded
    assert "read_skill" not in excluded


# ---------- ② 子级面不继承顶级裁剪 ----------

def test_child_does_not_inherit_production_prune(svc):
    """子级（depth≥1）不继承顶级生产裁剪——阶段执行器仍持生产工具。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    # script_analyze 子级：deny 集不含 read_uploaded_doc
    ctx_script = PlannerContext(
        skill_name=SKILL, subagent_depth=1, use_studio_context=True,
        subagent_deny=child_deny_set("script_analyze"))
    excluded_script = planner._compute_excluded_tools(ctx_script)
    assert "read_uploaded_doc" not in excluded_script
    assert "script_analysis_report" not in excluded_script

    # key_elements 子级：R4 后 storyboard 阶段已离委派集 → resolve 为通用形态
    ctx_key = PlannerContext(
        skill_name=SKILL, subagent_depth=1, use_studio_context=True,
        subagent_deny=child_deny_set("storyboard_key_elements"))
    excluded_key = planner._compute_excluded_tools(ctx_key)
    assert "storyboard_create_group" not in excluded_key
    assert child_deny_set("storyboard_key_elements") == SUBAGENT_TOOL_DENY


def test_stage_tools_mapping():
    """stage_tools 返回各阶段生产工具集（_STAGE_TOOLS 单一源）。"""
    assert stage_tools("script_analyze") == frozenset(
        {"read_uploaded_doc", "script_analysis_report"})
    assert stage_tools("write_media_prompt") == frozenset(
        {"storyboard_add_draft", "storyboard_patch_draft"})
    # R4（2026-09-16）：storyboard 三阶段已离委派集 → 空集
    assert stage_tools("storyboard_key_elements") == frozenset()
    assert stage_tools("storyboard_shots") == frozenset()
    assert stage_tools("storyboard_audio") == frozenset()
    # 未知/空阶段返回空集
    assert stage_tools("") == frozenset()
    assert stage_tools("不存在") == frozenset()


def test_main_agent_full_toolset(svc):
    """工具全还（2026-09-18）：主代理生产轮持全量工具——storyboard_create_group/
    read_skill/read_uploaded_doc/script_analysis_report/storyboard_add_draft/
    storyboard_patch_draft 均不再裁；委派集仍只余两阶段（协议引导委派）。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True)
    excluded = planner._compute_excluded_tools(ctx)
    assert "storyboard_create_group" not in excluded
    assert "read_skill" not in excluded
    assert "read_uploaded_doc" not in excluded
    assert "script_analysis_report" not in excluded
    assert "storyboard_add_draft" not in excluded
    assert "storyboard_patch_draft" not in excluded
    assert PIPELINE_STAGE_KINDS == frozenset(
        {"script_analyze", "write_media_prompt"})


# ---------- ③ adjust_scope 不裁剪 ----------

def test_adjust_scope_no_prune(svc):
    """微调子对话（adjust_scope 非空）不裁剪：保留 patch/read 工具。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True,
        adjust_scope={"group_id": "g1", "draft_id": "d1"})
    excluded = planner._compute_excluded_tools(ctx)
    # adjust_scope → 不触发生产裁剪
    assert "read_uploaded_doc" not in excluded
    assert "storyboard_create_group" not in excluded
    assert "storyboard_patch_draft" not in excluded
    assert "read_draft" not in excluded


# ---------- ④ 轮内 excluded 误调拒执行 ----------

async def test_turn_excluded_rejects_execution():
    """one visibility = one permission：轮内被裁工具误调 → 拒绝执行。"""
    runner = FCToolRunner(tool_manager=object())
    runner.turn_excluded = frozenset({"read_uploaded_doc", "storyboard_create_group"})

    # 被裁工具调用 → 拒执行
    res = await runner._dispatch_tool("read_uploaded_doc", {"name": "剧本.md"})
    assert res.success is False
    assert res.error_code == "validation"
    assert "不可用" in res.error or "裁剪" in res.error

    res2 = await runner._dispatch_tool("storyboard_create_group", {"title": "T"})
    assert res2.success is False
    assert res2.error_code == "validation"

    # 未裁工具正常执行（run_subagent 需 launcher，此处只验不被 turn_excluded 拦）
    runner.subagent_launcher = None  # 无 launcher → 另一条错误路径
    res3 = await runner._dispatch_tool("run_subagent", {"task": "T"})
    # run_subagent 不在 turn_excluded → 不走裁剪拒执行分支（走 launcher 缺失分支）
    assert "裁剪" not in (res3.error or "")


# ---------- ⑤ stage 映射缺失 fail-loud ----------

def test_pipeline_stage_kinds_consistency():
    """装载期校验：PIPELINE_STAGE_KINDS 每个成员必须在 _STAGE_TOOLS 有映射。
    （本测试在 import 后运行，若映射缺失则 import 期已 raise ValueError）"""
    for stage in PIPELINE_STAGE_KINDS:
        assert stage in _STAGE_TOOLS, f"{stage} missing from _STAGE_TOOLS"
        assert stage_tools(stage), f"{stage} has empty tool set"


# ---------- ⑥ 路由改造：非法 stage fail-loud ----------

async def test_invalid_stage_fail_loud():
    """run_subagent 带非法 stage → fail-loud 拒收（不静默回落通用委派）。"""
    runner = FCToolRunner(tool_manager=object())
    launched = []

    async def launcher(task, kind="", stage="", on_event=None):
        launched.append({"task": task, "stage": stage})
        return "ok"

    runner.subagent_launcher = launcher

    # 非法 stage → 拒收
    res = await runner._dispatch_tool(
        "run_subagent", {"task": "T", "stage": "不存在的阶段"})
    assert res.success is False
    assert res.error_code == "validation"
    assert "PIPELINE_STAGE_KINDS" in res.error or "可委派阶段" in res.error
    assert len(launched) == 0  # launcher 未被调用

    # 合法 stage → 正常委派
    res2 = await runner._dispatch_tool(
        "run_subagent", {"task": "T2", "stage": "script_analyze"})
    assert res2.success is True
    assert len(launched) == 1
    assert launched[0]["stage"] == "script_analyze"
