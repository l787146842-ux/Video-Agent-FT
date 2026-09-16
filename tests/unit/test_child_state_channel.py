# -*- coding: utf-8 -*-
"""K5 批（2026-09-16 对齐 flova）子代理工作台状态通道契约单测。

钉死：① child_ctx 携 state_builder（与父共享 StateManager 缓存同键命中）；
② 子级状态尾消息非空且含工作台 JSON（子代理看得见工作台）；
③ flova 实证不裁剪：context_builder 签名不引入 prune 参数/裁剪表；
④ 主路径（depth=0）装配逐字不变（deny 集 / 章节注入不变）。
不驱动真实模型循环（monkeypatch handle_message 断言装配契约，
同 test_subagent_stage 口径）。
"""
import inspect

import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core import planner as pmod
from src.video_agent.core import prompt_builder as pb_module
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.core.subagent import child_deny_set
from src.video_agent.state.manager import StateManager
from tests.unit.test_prompt_sections_subagent_prune import (
    TestPromptSectionsKeyOrder,
)

SKILL = "演示阶段技能"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    instance.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "程心", "desc": "主角", "drafts": []}]
    instance.state_dict["shots"] = []
    instance.state_dict["audioItems"] = []
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


def _fake_child(captured: dict):
    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        captured["msg"] = user_message
        captured["ctx"] = context
        return _FakeResp()

    return _fake_handle


def _make_builder(svc):
    return PromptBuilder(
        get_skill_docs=lambda: None,
        get_project_id=lambda: "p1",
        get_raw_state=lambda: svc.state_dict,
    )


class _FakeSkillDocs:
    """提供全文回落路径（章节注入标记可见）。"""

    def __init__(self, content: str = ""):
        self.content = content

    def get_skill_doc(self, slug):
        return {"content": self.content} if self.content else None


async def test_child_ctx_carries_state_builder_shared_cache(svc, monkeypatch):
    """子级携 state_builder；与父共享 StateManager 缓存（同键命中同串）。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "分析剧本", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="script_analyze")
    child_ctx = captured["ctx"]
    assert child_ctx.state_builder is not None
    child_json = child_ctx.state_builder()
    assert "程心" in child_json
    assert child_json == svc.build_agent_context("bound")


async def test_child_state_tail_renders_workbench(svc, monkeypatch):
    """子级状态尾消息非空且含工作台 JSON（子代理看得见工作台）。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "分析剧本", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="script_analyze")
    tail = _make_builder(svc).build_state_tail_message(captured["ctx"])
    assert "当前工作台状态 JSON" in tail
    assert "程心" in tail


async def test_no_prune_param_and_main_path_unchanged(svc, monkeypatch):
    """flova 实证不裁剪：context_builder 签名无 prune 参数；主路径装配
    （deny 集 / 章节注入）逐字不变。"""
    from src.video_agent.state import context_builder as cb
    assert "prune" not in inspect.signature(cb.build_agent_context).parameters

    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None,
                     skill_docs=_FakeSkillDocs(content="Z" * 100))
    await parent._launch_subagent(
        "分析剧本", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="script_analyze")
    assert captured["ctx"].subagent_deny == child_deny_set("script_analyze")
    assert "注入 Skill 章节" in captured["msg"]


def test_prompt_sections_key_order_unchanged():
    """K5 不新增/不重排 system 段：键序快照单一事实源 =
    test_prompt_sections_subagent_prune.TestPromptSectionsKeyOrder（P1 不复述）。"""
    actual = [spec.name for spec in pb_module.PROMPT_SECTIONS]
    assert actual == TestPromptSectionsKeyOrder.EXPECTED_KEYS
