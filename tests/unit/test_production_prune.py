# -*- coding: utf-8 -*-
"""主代理工具面契约单测（2026-09-19 主代理纯编排批更新）。

钉死断言：
① 顶级生产轮主代理结构性缺执行写入工具（MAIN_AGENT_DENY），但保留
   读工具/媒体生成/文档/确认/编排工具；
② 子级面持本阶段声明的生产工具（script_analyze 子级可调 read_uploaded_doc、
   storyboard 子级可调 storyboard_create_group），且**只**持本阶段声明的那部分
   （非本阶段的委派专属写入工具结构性不可见，2026-09-21 批0 事故 2222/Q5）；
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
    MAIN_AGENT_DENY, PIPELINE_STAGE_KINDS, STAGE_TOOL_DENY_EXTRA,
    SUBAGENT_TOOL_DENY, _STAGE_TOOLS, child_deny_set, stage_tools,
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


# ---------- ① 顶级生产轮面 = 主代理纯编排（锁执行写入工具） ----------

def test_top_level_production_main_agent_deny(svc):
    """主代理纯编排（2026-09-19 用户裁决）：顶级生产轮主代理结构性缺
    MAIN_AGENT_DENY 执行写入工具（只能经委派触达），但保留读工具/
    媒体生成/文档/确认/编排工具。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True)
    excluded = planner._compute_excluded_tools(ctx)

    # 执行写入工具被锁（故事板结构/素材分析产出/提示词草稿）
    for t in MAIN_AGENT_DENY:
        assert t in excluded, f"{t} 应被主代理结构性裁剪"
    assert "storyboard_create_group" in excluded
    assert "storyboard_delete_group" in excluded
    assert "storyboard_add_draft" in excluded
    assert "storyboard_patch_draft" in excluded
    assert "script_analysis_report" in excluded
    # 读工具不裁（主代理理解需求/读资料）
    assert "read_uploaded_doc" not in excluded
    assert "read_draft" not in excluded
    assert "view_storyboard_media" not in excluded
    assert "read_state_group" not in excluded
    assert "read_skill" not in excluded
    # 媒体生成不裁（例外：花钱生成确认闸留主线程）
    assert "image_generate" not in excluded
    assert "generate_video" not in excluded
    # 编排/文档/确认工具保留
    assert "run_subagent" not in excluded
    assert "workflow_pause" not in excluded
    assert "document_write" not in excluded
    assert "storyboard_confirm_draft" not in excluded
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

def test_child_does_not_inherit_main_agent_deny(svc):
    """子级（depth≥1）不继承主代理纯编排 deny——阶段执行器仍持生产工具。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    # script_analyze 子级：deny 集不含 read_uploaded_doc / script_analysis_report
    ctx_script = PlannerContext(
        skill_name=SKILL, subagent_depth=1, use_studio_context=True,
        subagent_deny=child_deny_set("script_analyze"))
    excluded_script = planner._compute_excluded_tools(ctx_script)
    assert "read_uploaded_doc" not in excluded_script
    assert "script_analysis_report" not in excluded_script

    # storyboard_key_elements 子级：本批恢复为合法阶段 → 持本阶段声明的故事板
    # 写入工具（建组/删组/加卡），不继承主代理 MAIN_AGENT_DENY 里**本阶段未声明**
    # 的部分（patch_draft 已由 2026-09-21 批0 收走）；stage deny 额外去 read_skill。
    # 2026-09-21 批0 回归修复：add_draft **必须**留——角色音色卡
    # （key_element_audio）是该阶段产出（Skill 明文「声音特征单独登记为
    # key_element_audio」；proj-1789754393 实证该阶段建过 8 张 mediaType=audio 卡）。
    ctx_key = PlannerContext(
        skill_name=SKILL, subagent_depth=1, use_studio_context=True,
        subagent_deny=child_deny_set("storyboard_key_elements"))
    excluded_key = planner._compute_excluded_tools(ctx_key)
    assert "storyboard_create_group" not in excluded_key
    assert "storyboard_delete_group" not in excluded_key
    assert "storyboard_add_draft" not in excluded_key
    # 批0：非本阶段的专业写入工具对本阶段子代理结构性不可见
    assert child_deny_set("storyboard_key_elements") == (
        SUBAGENT_TOOL_DENY | STAGE_TOOL_DENY_EXTRA
        | (MAIN_AGENT_DENY - stage_tools("storyboard_key_elements")))
    assert "storyboard_patch_draft" in excluded_key
    # 子代理 read_skill 仍 deny（不能自由读其他章节）
    assert "read_skill" in excluded_key


def test_stage_tools_mapping():
    """stage_tools 返回各阶段生产工具集（_STAGE_TOOLS 单一源）。"""
    assert stage_tools("script_analyze") == frozenset(
        {"read_uploaded_doc", "script_analysis_report"})
    assert stage_tools("write_media_prompt") == frozenset(
        {"storyboard_add_draft", "storyboard_patch_draft"})
    # 2026-09-19 主代理纯编排批：故事板三阶段恢复委派集 → 非空工具集
    # 2026-09-21 批0 回归修复：key_elements 补 add_draft（音色卡是该阶段产出）
    assert stage_tools("storyboard_key_elements") == frozenset(
        {"storyboard_create_group", "storyboard_delete_group",
         "storyboard_add_draft"})
    assert stage_tools("storyboard_shots") == frozenset(
        {"storyboard_create_group", "storyboard_delete_group",
         "storyboard_add_draft", "storyboard_patch_draft"})
    assert stage_tools("storyboard_audio") == frozenset(
        {"storyboard_create_group", "storyboard_delete_group",
         "storyboard_add_draft"})
    # 未知/空阶段返回空集
    assert stage_tools("") == frozenset()
    assert stage_tools("不存在") == frozenset()


def test_main_agent_orchestrator_surface(svc):
    """主代理纯编排（2026-09-19）：生产轮锁掉 5 个执行写入工具，保留
    读工具/媒体生成；委派集 = 素材分析 + 故事板三阶段 + 提示词撰写。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True)
    excluded = planner._compute_excluded_tools(ctx)
    # 执行写入工具被锁
    assert "storyboard_create_group" in excluded
    assert "script_analysis_report" in excluded
    assert "storyboard_add_draft" in excluded
    assert "storyboard_patch_draft" in excluded
    # 读工具保留
    assert "read_skill" not in excluded
    assert "read_uploaded_doc" not in excluded
    assert PIPELINE_STAGE_KINDS == frozenset({
        "script_analyze", "storyboard_key_elements", "storyboard_shots",
        "storyboard_audio", "write_media_prompt"})


def test_main_agent_deny_subset_of_stage_tools():
    """MAIN_AGENT_DENY 每个工具都被某个可委派阶段使用（否则锁掉后不可达）。"""
    all_stage_tools = frozenset().union(*_STAGE_TOOLS.values())
    assert MAIN_AGENT_DENY <= all_stage_tools
    # 读工具不在 deny 集（主代理保留读能力）
    assert "read_uploaded_doc" not in MAIN_AGENT_DENY
    # 媒体生成不在 deny 集（例外：留主代理带确认闸）
    assert "image_generate" not in MAIN_AGENT_DENY
    assert "generate_video" not in MAIN_AGENT_DENY


# ---------- ②b 子代理工具面按阶段收口（事故 2222/Q5） ----------

def test_stage_child_face_equals_declared_tools(svc):
    """事故 2222/Q5：子代理工具面必须等于「本阶段声明 + 非专业写入工具」。

    2222 实测：storyboard_key_elements 子代理可见 18/23 个工具，
    storyboard_add_draft / patch_draft / script_analysis_report 全在——
    而注入章节的散文只说它是"登记元素"。散文说没有、手上却有，
    模型只能自行裁决「算不算越权」（该子代理 21.5% 推理花在此），
    最终按"任务书要求 + 工具在手"两票越界写了 17 张提示词卡。

    修法（P2 约束下沉）：让阶段边界由工具面机械保证，不靠散文劝阻。
    """
    sb_write = frozenset({
        "storyboard_create_group", "storyboard_delete_group",
        "storyboard_add_draft", "storyboard_patch_draft",
    })
    planner = Planner(state_manager=svc, llm_adapter=None)
    for stage in sorted(PIPELINE_STAGE_KINDS):
        excluded = planner._compute_excluded_tools(PlannerContext(
            skill_name=SKILL, subagent_depth=1, use_studio_context=True,
            subagent_deny=child_deny_set(stage)))
        visible_pro_write = {
            t for t in MAIN_AGENT_DENY if t not in excluded}
        assert visible_pro_write == set(stage_tools(stage) & MAIN_AGENT_DENY), (
            f"阶段 {stage} 的委派专属写入工具面与 _STAGE_TOOLS 声明不一致："
            f"可见 {sorted(visible_pro_write)}，声明 "
            f"{sorted(stage_tools(stage) & MAIN_AGENT_DENY)}")
        # 故事板写入四件套里，未声明的必须不可见（2222 越界的直接通道）
        assert not ((visible_pro_write & sb_write) - stage_tools(stage))
    # 反向钉：write_media_prompt 正是用 add/patch_draft 的阶段，不得被误收
    assert "storyboard_add_draft" not in child_deny_set("write_media_prompt")
    assert "storyboard_patch_draft" not in child_deny_set("write_media_prompt")


def test_stage_deny_never_starves_declared_tools():
    """防过度收口：任何阶段自己声明的工具都不在它的 deny 集里（断链即 FAIL）。

    与 test_stage_child_face_equals_declared_tools 互补——那边防"收得不够"，
    这边防"收得过头"。2222 之前 1111 批的教训正是过度 allowlist 导致
    script_analysis_report 未授予、分析结论无法提交。
    """
    for stage in sorted(PIPELINE_STAGE_KINDS):
        deny = child_deny_set(stage)
        starved = stage_tools(stage) & deny
        assert not starved, f"阶段 {stage} 的必备工具被自己的 deny 集收走：{sorted(starved)}"
    # 四条硬约束在任何阶段都不被削弱
    for stage in sorted(PIPELINE_STAGE_KINDS):
        assert SUBAGENT_TOOL_DENY <= child_deny_set(stage)
    # 通用委派（无 stage）不并入 MAIN_AGENT_DENY：无阶段即无阶段边界
    assert child_deny_set("") == SUBAGENT_TOOL_DENY
    assert not (MAIN_AGENT_DENY & child_deny_set(""))


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
