# -*- coding: utf-8 -*-
"""K6 批（2026-09-16 对齐 flova/dsh）structured_output 打卡契约单测。

钉死：① 子代理专属可见（主代理面裁剪、UNAVAILABLE 段不渲染）；
② 打卡成功 = captured → 轮内终局 guard 拒后续工具调用/重复打卡；
③ reset_turn_tracking 轮始清空（上轮打卡不泄漏）；
④ 打卡指令 BRIEF 随委派任务下发（subagent.md 逐字锁零触碰）。
"""
import pytest

import src.video_agent.tools  # noqa: F401  触发全量工具注册
from src.video_agent.core import planner as pmod
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.subagent import CHILD_ONLY_TOOLS, child_deny_set
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager

SKILL = "演示阶段技能"


@pytest.fixture(autouse=True)
def _ensure_structured_tool():
    """跨文件 ToolManager.reset()（如 smoke harness finally）后重注册打卡工具。"""
    from src.video_agent.tools.structured_output import (
        register_structured_output_tools,
    )
    register_structured_output_tools()
    yield


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def test_child_only_visibility(svc):
    """主代理面（含自由对话）裁剪；子级（depth≥1）可见。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    main = planner._compute_excluded_tools(
        PlannerContext(skill_name=SKILL, subagent_depth=0,
                       use_studio_context=True))
    assert "structured_output" in main
    free = planner._compute_excluded_tools(
        PlannerContext(skill_name="", subagent_depth=0,
                       use_studio_context=True))
    assert "structured_output" in free
    child = planner._compute_excluded_tools(PlannerContext(
        skill_name=SKILL, subagent_depth=1, use_studio_context=True,
        subagent_deny=child_deny_set("script_analyze")))
    assert "structured_output" not in child
    assert CHILD_ONLY_TOOLS == frozenset({"structured_output"})


def test_unavailable_section_hides_child_only(svc):
    """UNAVAILABLE 段不渲染 CHILD_ONLY_TOOLS（主代理不感知打卡工具）。"""
    from src.video_agent.core.prompt_builder import PromptBuilder
    builder = PromptBuilder(
        get_skill_docs=lambda: None,
        get_project_id=lambda: "p1",
        get_raw_state=lambda: {},
    )
    ctx = PlannerContext(
        use_studio_context=True,
        state_json='{"keyElements":[]}',
        turn_excluded=frozenset({"structured_output"}),
    )
    assert "UNAVAILABLE" not in builder.build_state_tail_message(ctx)
    ctx2 = PlannerContext(
        use_studio_context=True,
        state_json='{"keyElements":[]}',
        turn_excluded=frozenset({"structured_output", "storyboard_add_draft"}),
    )
    tail = builder.build_state_tail_message(ctx2)
    assert "UNAVAILABLE" in tail
    assert "structured_output" not in tail
    assert "storyboard_add_draft" in tail


async def test_capture_then_terminal_guard():
    """打卡成功 → 轮内终局：其它工具拒收、重复打卡拒收；轮始清空。"""
    runner = FCToolRunner(tool_manager=ToolManager)
    res = await runner._dispatch_tool(
        "structured_output",
        {"created": ["keyElement 1 组（ke-1）"], "modified": [],
         "removed": [], "unfinished": []})
    assert res.success is True
    assert runner._structured_captured is True

    res2 = await runner._dispatch_tool("read_state_group", {"category": "shot"})
    assert res2.success is False
    assert "终局" in (res2.error or "")

    res3 = await runner._dispatch_tool("structured_output", {"created": []})
    assert res3.success is False
    assert "重复" in (res3.error or "")

    # 轮始清空：终局不泄漏到下一轮
    runner.reset_turn_tracking()
    assert runner._structured_captured is False


async def test_base_task_carries_brief(svc, monkeypatch):
    """打卡指令 BRIEF 随委派任务下发（subagent.md 零触碰）。"""
    captured = {}

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        captured["msg"] = user_message
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "分析剧本", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="script_analyze")
    assert "完工打卡" in captured["msg"]
    assert "structured_output" in captured["msg"]
