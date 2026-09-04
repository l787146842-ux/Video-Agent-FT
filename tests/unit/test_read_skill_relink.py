# -*- coding: utf-8 -*-
"""read_skill 可见性回归（任务#12 批次A：门禁短路解除后的新口径）。

口径：planner._compute_excluded_tools 不再以「选中 Skill 全文直注」为由
剔除 read_skill——任何 Skill 激活下（含短 Skill 全文直注、超长分级注入），
read_skill 全程可见可调用，续读/资源加载入口恒保留。
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


def _make_ctx(skill):
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill
    return ctx


@pytest.mark.parametrize("skill", ["任意Skill", "AI-短剧一站式生成"])
def test_planner_never_excludes_read_skill(svc, monkeypatch, skill):
    """read_skill 恒可见：全文直注不再是剔除理由，任意激活态都不关入口。"""
    monkeypatch.setattr(
        "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
    excluded = _make_planner(svc)._compute_excluded_tools(_make_ctx(skill))
    assert "read_skill" not in excluded


def test_oversized_real_skills_keep_read_skill_available(svc, monkeypatch):
    """真实数据链路：三个超长分级注入 Skill 激活时，
    read_skill 续读入口恒保留（续读断链回潮防线）。"""
    monkeypatch.setattr(
        "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
    planner = _make_planner(svc)
    for stem in ("水墨风格武侠短片", "3D国漫古装精品短剧", "李安美学风格短片"):
        assert "read_skill" not in planner._compute_excluded_tools(
            _make_ctx(stem)), f"{stem} 续读断链回潮"
