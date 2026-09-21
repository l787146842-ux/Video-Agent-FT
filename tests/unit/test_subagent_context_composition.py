# -*- coding: utf-8 -*-
"""子代理上下文组合契约单测（2026-09-21 批A，事故 5555/Q3+Q8 与两项追加发现）。

背景（5555 实跑取证）：
① 关键元素子代理两次都死在供应商 504（单次输出体量过大），而唯一能拦住它的
   《Skill 流程纪律》第 6 条「每批 3~5 个、不要一次生成全部」**物理到不了子级**；
② 父代理暂停卡渲染成「本阶段」而非真实阶段名——`stage_label_for_tool` 只认
   工具名，而委派轮父级唯一工具是 run_subagent（不在表内）；
③ 子级收到循环指令：UNAVAILABLE 段说「run_subagent 不可用，替代路由 = 经
   委派（run_subagent）执行」——而被禁的正是 run_subagent 本身；
④ protocol.md 整文件无 depth 门控注入子级，其中两处指向《Skill 流程纪律》
   的指针在子级悬空（子级 skill_name=""，该纪律只在 _selected_block 里）。

本文件钉死批A 四项改动，防回潮。
"""
from pathlib import Path

import pytest

from src.video_agent.core import prompt_builder as pb_module
from src.video_agent.core import subagent as sub
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.utils import prompts as prompts_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUBAGENT_MD = PROJECT_ROOT / "prompts" / "planner" / "subagent.md"

_STAGE = "storyboard_key_elements"


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    prompts_mod.clear_cache()
    yield
    prompts_mod.clear_cache()


def _builder():
    return pb_module.PromptBuilder(
        get_skill_docs=lambda: None,
        get_project_id=lambda: "p1",
        get_raw_state=lambda: {},
    )


def _child_ctx(stage: str = _STAGE) -> PlannerContext:
    """复刻 key_elements 子级的真实 context（deny + turn_excluded 同源）。"""
    deny = sub.child_deny_set(stage)
    ctx = PlannerContext(
        use_studio_context=True, skill_name="", subagent_depth=1,
        subagent_deny=deny, subagent_stage=stage,
        state_json='{"keyElements":[]}',
    )
    ctx.turn_excluded = deny
    return ctx


# ---------- A1：子级不注入主代理协议（追加-2） ----------

def test_child_system_prompt_drops_planner_protocol():
    """子级 system prompt 不含 protocol.md（其指针在子级悬空、语义为反）。"""
    seg = pb_module._sec_protocol(_builder(), _child_ctx())
    assert seg == "", "子级仍在注入主代理协议（protocol.md）"


def test_parent_still_gets_protocol():
    """防误伤：主代理（depth 0）照常注入整文件（行为逐字不变）。"""
    ctx = PlannerContext(use_studio_context=True, skill_name="AI-x",
                         subagent_depth=0)
    seg = pb_module._sec_protocol(_builder(), ctx)
    assert seg, "主代理协议段丢失——批A/A1 只应对子级生效"
    assert "动作通道唯一" in seg, "主代理协议内容异常"


def test_non_studio_context_still_empty():
    """非 studio 上下文不注入（既有语义不变）。"""
    ctx = PlannerContext(use_studio_context=False, subagent_depth=0)
    assert pb_module._sec_protocol(_builder(), ctx) == ""


# ---------- A2：子级不渲染 UNAVAILABLE 段（追加-1） ----------

def test_child_tail_has_no_unavailable_section():
    """子级状态尾消息不出现 UNAVAILABLE 段。

    5555 实测原文：「以下工具本轮不可用：…, run_subagent, …。
    替代路由：经委派（run_subagent）执行对应阶段。」——用被禁的工具
    当被禁工具的替代路由（循环指令）。
    """
    tail = _builder().build_state_tail_message(_child_ctx())
    assert "UNAVAILABLE" not in tail, (
        "子级仍在渲染 UNAVAILABLE 段——替代路由文案是主代理专用的，"
        "套到子级会变成「run_subagent 不可用，请改用 run_subagent」")
    assert "替代路由" not in tail, "子级出现替代路由文案（循环指令）"


def test_child_deny_set_contains_run_subagent():
    """钉死前提：子级 deny 集确实含 run_subagent（结构防递归）。

    这条是上方缺陷成立的**原因**——若将来 run_subagent 不再被 deny，
    UNAVAILABLE 段的循环性会消失，届时本组断言需重新评估。
    """
    assert "run_subagent" in sub.SUBAGENT_TOOL_DENY
    assert "run_subagent" in sub.child_deny_set(_STAGE)


def test_parent_unavailable_section_unchanged():
    """防误伤：主代理（depth 0）照常渲染 UNAVAILABLE + 替代路由文案。"""
    from src.video_agent.core import prompt_builder as pb_mod2
    ctx = PlannerContext(
        use_studio_context=True, subagent_depth=0,
        state_json='{"keyElements":[]}',
        turn_excluded=frozenset({"storyboard_add_draft"}),
    )
    tail = _builder().build_state_tail_message(ctx)
    assert "UNAVAILABLE" in tail, "主代理 UNAVAILABLE 段丢失——批A/A2 只应对子级生效"
    assert "storyboard_add_draft" in tail
    assert pb_mod2 is not None


# ---------- A3：子级拿到分批纪律（Q8） ----------

def _delegation_context() -> str:
    return sub.subagent_delegation_context()


def test_delegation_context_carries_batching_discipline():
    """子级固定声明必须含分批推进事实（每批 3~5 个 + 思考同样分批）。

    5555/Q8：子代理读素材成功后，下一步要一次性吐 8 角色+3 场景+7 道具+
    8 张音色卡，60s 整网关 504（两次同点阵亡）。旧 DELEGATION_CONTEXT
    只有「批次之间禁止纯文本汇报轮」，**没有"每批几个"、没有"别一次生成全部"**。
    """
    ctx = _delegation_context()
    assert "分批" in ctx, "缺分批推进契约（5555/Q8 的直接病根）"
    assert "3~5" in ctx, "缺每批调用数上限（Skill 纪律第 6 条的对应物）"
    assert "思考同样分批" in ctx, "缺「思考同样分批」（一次性巨量思考同样致命）"
    assert "已落盘" in ctx, "缺后果说明——不给原因则退化成纯禁令（G3）"


def test_delegation_context_batching_is_self_sufficient():
    """A1 门控后，子级的分批约束必须自足（不能只指向《Skill 流程纪律》）。

    硬依赖：protocol.md 曾指向《Skill 流程纪律》第 6 条，而该纪律子级拿不到；
    A1 把 protocol 整个从子级移除后，若 DELEGATION_CONTEXT 也只在别处指路，
    子级就彻底失去分批约束——比修复前更糟。
    """
    ctx = _delegation_context()
    assert "《Skill 流程纪律》" not in ctx, (
        "子级声明仍在指向《Skill 流程纪律》——该纪律对子级不可达（悬空指针）")


def test_batching_discipline_actually_reachable_by_child():
    """端到端：分批纪律确实出现在子级收到的任务文本里。"""
    task = sub.build_subagent_task("登记关键元素", stage=_STAGE)
    assert "分批" in task, "分批纪律未随子级任务文本下发（Q8 未闭合）"
    assert "3~5" in task


def test_subagent_task_text_carries_no_parent_side_antiexample_list():
    """子级任务文本不得夹带**父侧反例清单**（2026-09-21 批E，事故 4444/Q2①）。

    4444 实证：模型在思考里说「章节里会说明**是否建卡**等」，而 `建卡` 在
    `data/skills/*/SKILL.md` 零命中——该词是平台反例清单喂进父级上下文的，
    不是章节里读到的。

    ⚠️ 边界（本钉只锁父侧反例短语，不锁裸名词）：`DELEGATION_CONTEXT` 里的
    「大批量登记（建组/建卡/写提示词）分批做」是批A/A3 **刻意**补的分批纪律，
    描述子代理**自己要做的事**（5555/Q8 的直接修复），删除它会回归。
    两者的区别是**句式**：反例清单用「要不要…／…怎么写／交不交…」这种
    揣测章节内容的疑问式列举；分批纪律是陈述式子代理行动指引。
    """
    task = sub.build_subagent_task("登记关键元素", stage=_STAGE)
    for leak in ("要不要建卡", "字段怎么写", "交不交提示词", "几个场景"):
        assert leak not in task, (
            f"子级任务文本夹带父侧反例短语「{leak}」——会被模型当成事实复述"
            f"（4444/Q2①）")
    # 反向确认：分批纪律本身仍在（防本钉误伤批A/A3 的修复）
    assert "分批" in task and "3~5" in task, \
        "分批纪律被误删——本钉只应排除父侧反例清单，不得动批A 的分批契约"


# ---------- A4：委派阶段回填父级阶段标签（Q3） ----------

def test_stage_display_label_maps_enum_to_label():
    """纯函数：阶段枚举 → 展示标签（空/未知回落空串）。"""
    assert sub.stage_display_label(_STAGE) == "关键元素拆解"
    assert sub.stage_display_label("script_analyze") == "剧本分析"
    assert sub.stage_display_label("") == ""
    assert sub.stage_display_label("not_a_stage") == ""


def test_delegated_stage_fills_parent_stage_label():
    """父级暂停卡的阶段标签：委派 run_subagent(stage=…) 后不再回落「本阶段」。

    5555 落盘实证 chatMessages[1].confirm ==
    '「本阶段」已完成，请过目以上成果并选择下一步。'
    """
    from src.video_agent.core.fc_tool_runner import FCToolRunner

    class _TM:
        async def invoke_tool(self, name, args):
            from src.video_agent.tools.base import ToolResult
            return ToolResult(success=True, data={})

        def get_tool(self, name):
            return type("_StubTool", (), {"risk": "low"})

    runner = FCToolRunner(tool_manager=_TM())
    # 委派由 planner 注入的 launcher 拦截执行（此处只验阶段标签回填）
    async def _fake_launch(task, kind="", stage="", on_event=None):
        return "（子代理摘要）"

    runner.subagent_launcher = _fake_launch

    import asyncio
    import json as _json

    from src.video_agent.adapters.base_chat import ChatResponse

    resp = ChatResponse(content="", tool_calls=[
        {"id": "c0", "type": "function", "function": {
            "name": "run_subagent",
            "arguments": _json.dumps({"stage": _STAGE, "task": "登记元素"})}},
        {"id": "c1", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": _json.dumps({"message": "请确认"})}},
    ])
    res = asyncio.run(runner.execute(resp))
    confirmation = res[1]
    assert "关键元素拆解" in confirmation, (
        f"暂停卡未带真实阶段标签（实得：{confirmation!r}）——"
        f"run_subagent 的阶段未回填父级 last_stage_label（5555/Q3）")
    assert "本阶段" not in confirmation, "仍回落系统模板的「本阶段」"


def test_generic_delegation_keeps_fallback_label():
    """通用委派（无 stage）不伪造阶段标签——照旧回落「本阶段」。"""
    import asyncio
    import json as _json

    from src.video_agent.adapters.base_chat import ChatResponse
    from src.video_agent.core.fc_tool_runner import FCToolRunner

    class _TM:
        async def invoke_tool(self, name, args):
            from src.video_agent.tools.base import ToolResult
            return ToolResult(success=True, data={})

        def get_tool(self, name):
            return type("_StubTool", (), {"risk": "low"})

    runner = FCToolRunner(tool_manager=_TM())

    async def _fake_launch(task, kind="", stage="", on_event=None):
        return "（子代理摘要）"

    runner.subagent_launcher = _fake_launch
    resp = ChatResponse(content="", tool_calls=[
        {"id": "c0", "type": "function", "function": {
            "name": "run_subagent",
            "arguments": _json.dumps({"task": "随便做点啥"})}},
        {"id": "c1", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": _json.dumps({"message": "请确认"})}},
    ])
    res = asyncio.run(runner.execute(resp))
    assert "本阶段" in res[1], "通用委派不应伪造阶段标签"
