# -*- coding: utf-8 -*-
"""整改批 2.4：read_skill 续读断链修复回归。

历史缺陷：planner._compute_excluded_tools 用 compile_definition(skill) 恒真
条件剔除 read_skill——任何已注册 Skill 激活即关死续读入口，超长分级注入
Skill（3D国漫/李安/水墨）的「目录 + read_skill 续读」链路断裂。
修复后判定与 fc_tool_runner.read_skill 短路同源（fc_gates.skill_full_text_injected）：
全文真注入才关入口，分级注入保续读。本文件双向钉死。
"""
import pytest

from src.video_agent.core import fc_gates
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


@pytest.mark.parametrize("full_injected", [True, False])
def test_planner_read_skill_exclusion_defers_to_injection_reality(
        svc, monkeypatch, full_injected):
    """剔除判定单一事实源 = skill_full_text_injected：
    全文真注入 → read_skill 出 schema（防重读）；分级注入 → 保留续读入口。"""
    monkeypatch.setattr(fc_gates, "skill_full_text_injected",
                        lambda name: full_injected)
    excluded = _make_planner(svc)._compute_excluded_tools(_make_ctx("任意Skill"))
    assert ("read_skill" in excluded) is full_injected


def test_oversized_real_skills_keep_read_skill_available(svc, monkeypatch):
    """真实数据链路：三个超长 Skill 分级注入 → planner 不剔除 read_skill；
    短 Skill 全文直注 → 剔除生效（短路语义不松动）。"""
    from src.video_agent.core.prompt_builder import GENERIC_FULL_INJECT_LIMIT
    monkeypatch.setattr(
        "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
    planner = _make_planner(svc)
    for stem in ("水墨风格武侠短片", "3D国漫古装精品短剧", "李安美学风格短片"):
        assert not fc_gates.skill_full_text_injected(stem), (
            f"{stem} 实测超阈值，此用例前提失效须同步修订")
        assert "read_skill" not in planner._compute_excluded_tools(
            _make_ctx(stem)), f"{stem} 续读断链回潮"
    short = "剧本生视频需上传剧本"
    content_len = len(fc_gates.resolve_entry(short).content.strip())
    assert content_len <= GENERIC_FULL_INJECT_LIMIT, "短 Skill 前提失效"
    assert "read_skill" in planner._compute_excluded_tools(_make_ctx(short))
