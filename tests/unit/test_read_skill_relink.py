# -*- coding: utf-8 -*-
"""read_skill 可见性回归（任务#12 批次A + 2026-09-15 铺满批更新）。

口径演进：
- 任务#12 批次A：planner._compute_excluded_tools 不再以「选中 Skill 全文直注」为由
  剔除 read_skill——任何 Skill 激活下 read_skill 全程可见可调用。
- 2026-09-15 铺满批（dsh 对齐）：顶级生产轮（skill_name 非空 + depth==0 +
  非 adjust_scope）read_skill 曾进 PRODUCTION_MAIN_PRUNE 裁剪集（回读三件套之一）。
- 2026-09-16 R4 批（对齐 flova）：read_skill 解禁——故事板翻回主代理直做，
  主代理须在设计前 read_skill 读全对应章节（产出形态归 Skill 章节唯一
  表述源，2026-09-17 裁决平台零引导）；顶级生产轮
  不再裁 read_skill。子级/微调/自由对话仍保留 read_skill 可见。
"""
import pytest

from src.video_agent.core.planner import Planner, PlannerContext


@pytest.fixture()
def svc(tmp_path):
    from src.video_agent.state.manager import StateManager
    StateManager.reset_instance()
    yield StateManager(str(tmp_path))
    StateManager.reset_instance()


def _make_planner(svc):
    planner = Planner.__new__(Planner)
    planner.state_manager = svc
    return planner


def _make_ctx(skill, depth=0, adjust_scope=None):
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill
    ctx.subagent_depth = depth
    if adjust_scope is not None:
        ctx.adjust_scope = adjust_scope
    return ctx


@pytest.mark.parametrize("skill", ["任意Skill", "AI-短剧一站式生成"])
def test_production_turn_keeps_read_skill(svc, monkeypatch, skill):
    """2026-09-16 R4 批（对齐 flova）：顶级生产轮 read_skill 解禁——
    故事板翻回主代理亲做，主代理须在设计前 read_skill 读全对应章节
    （flova 式合规杠杆=上下文在场；产出形态归 Skill 章节，平台零引导）。"""
    monkeypatch.setattr(
        "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
    excluded = _make_planner(svc)._compute_excluded_tools(_make_ctx(skill))
    assert "read_skill" not in excluded


def test_free_chat_keeps_read_skill(svc, monkeypatch):
    """自由对话（无 skill）不裁剪：read_skill 仍可见。"""
    monkeypatch.setattr(
        "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
    excluded = _make_planner(svc)._compute_excluded_tools(_make_ctx(""))
    assert "read_skill" not in excluded


def test_child_agent_keeps_read_skill(svc, monkeypatch):
    """子级（depth≥1）不继承顶级生产裁剪：read_skill 仍可见。"""
    monkeypatch.setattr(
        "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
    excluded = _make_planner(svc)._compute_excluded_tools(
        _make_ctx("AI-短剧一站式生成", depth=1))
    assert "read_skill" not in excluded


def test_adjust_scope_keeps_read_skill(svc, monkeypatch):
    """微调子对话（adjust_scope 非空）不裁剪：read_skill 仍可见。"""
    monkeypatch.setattr(
        "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
    excluded = _make_planner(svc)._compute_excluded_tools(
        _make_ctx("AI-短剧一站式生成", adjust_scope={"group_id": "g1"}))
    assert "read_skill" not in excluded


def test_oversized_real_skills_keep_read_skill_in_production(svc, monkeypatch):
    """真实数据链路：三个超长分级注入 Skill 激活时，
    顶级生产轮 read_skill 仍可见（R4 批解禁：主代理亲做故事板须读章节）。"""
    monkeypatch.setattr(
        "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
    planner = _make_planner(svc)
    for stem in ("水墨风格武侠短片", "3D国漫古装精品短剧", "李安美学风格短片"):
        assert "read_skill" not in planner._compute_excluded_tools(
            _make_ctx(stem)), f"{stem} 生产轮不应裁剪 read_skill"
