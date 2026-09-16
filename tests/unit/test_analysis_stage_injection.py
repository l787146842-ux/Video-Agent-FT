# -*- coding: utf-8 -*-
"""R7 analysis 阶段化注入契约单测（P1-G 批）。

钉死：故事板设计阶段（白名单 storyboard_key_elements / storyboard_shots）子代理
在隔离上下文（history=[]，零状态通道）里能看到前序 analysis 结论——系统按预算
截断（summary≤500 / report≤2500）注入 base_task；非白名单阶段零注入；analysis
为空守卫跳过。不驱动真实模型循环（monkeypatch handle_message 断言装配契约，
同 test_subagent_stage 口径）。
"""
import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core import planner as pmod
from src.video_agent.core.planner import Planner, PlannerContext, _ANALYSIS_INJECT_STAGES
from src.video_agent.state.manager import StateManager

INJECT_MARKER = "===== 前序分析摘要（系统注入）====="
SUMMARY = "太阳系确认遭遇疑似二向箔的白色薄片打击。"
REPORT = "**剧本分类**：A 类\n**关键道具**：二向箔"


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


def _fake_child(captured: dict):
    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        captured["msg"] = user_message
        captured["ctx"] = context
        return _FakeResp()

    return _fake_handle


def _set_analysis(svc, summary=SUMMARY, report=REPORT):
    svc.state_dict["analysis"] = {"doc_name": "三体.md", "summary": summary, "report": report}


# ---------- 白名单常量 ----------

def test_whitelist_is_storyboard_design_stages():
    assert _ANALYSIS_INJECT_STAGES == frozenset(
        {"storyboard_key_elements", "storyboard_shots"})


# ---------- 白名单阶段注入 ----------

async def test_key_elements_stage_injects_analysis(svc, monkeypatch):
    """白名单阶段 storyboard_key_elements：注入 analysis 摘要 + 报告。"""
    _set_analysis(svc)
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "拆解关键元素", PlannerContext(subagent_depth=0),
        stage="storyboard_key_elements")
    msg = captured["msg"]
    assert INJECT_MARKER in msg
    assert SUMMARY in msg
    assert REPORT in msg


async def test_shots_stage_injects_analysis(svc, monkeypatch):
    """白名单阶段 storyboard_shots：注入 analysis 摘要 + 报告。"""
    _set_analysis(svc)
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "拆解分镜", PlannerContext(subagent_depth=0),
        stage="storyboard_shots")
    msg = captured["msg"]
    assert INJECT_MARKER in msg
    assert SUMMARY in msg
    assert REPORT in msg


# ---------- 非白名单阶段零注入 ----------

async def test_non_whitelist_stage_no_injection(svc, monkeypatch):
    """非白名单阶段（script_analyze）：即便有 analysis 也零注入。"""
    _set_analysis(svc)
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "分析剧本", PlannerContext(subagent_depth=0),
        stage="script_analyze")
    assert INJECT_MARKER not in captured["msg"]


async def test_write_media_prompt_stage_no_injection(svc, monkeypatch):
    """非白名单阶段（write_media_prompt）零注入。"""
    _set_analysis(svc)
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "写提示词", PlannerContext(subagent_depth=0),
        stage="write_media_prompt")
    assert INJECT_MARKER not in captured["msg"]


# ---------- analysis 为空守卫 ----------

async def test_empty_analysis_no_injection(svc, monkeypatch):
    """白名单阶段但 analysis 为空：守卫跳过，零注入。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "拆解分镜", PlannerContext(subagent_depth=0),
        stage="storyboard_shots")
    assert INJECT_MARKER not in captured["msg"]


async def test_blank_analysis_no_injection(svc, monkeypatch):
    """白名单阶段但 summary/report 全空白：视同空，零注入。"""
    svc.state_dict["analysis"] = {"summary": "   ", "report": ""}
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "拆解分镜", PlannerContext(subagent_depth=0),
        stage="storyboard_shots")
    assert INJECT_MARKER not in captured["msg"]


# ---------- 截断预算 ----------

async def test_truncation_budget(svc, monkeypatch):
    """summary > 500 截断到 500、report > 2500 截断到 2500。"""
    _set_analysis(svc, summary="A" * 600, report="B" * 3000)
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "拆解分镜", PlannerContext(subagent_depth=0),
        stage="storyboard_shots")
    msg = captured["msg"]
    assert INJECT_MARKER in msg
    assert "A" * 500 in msg
    assert "A" * 501 not in msg          # summary 截断到 500
    assert "B" * 2500 in msg
    assert "B" * 2501 not in msg         # report 截断到 2500
