# -*- coding: utf-8 -*-
"""9999 二轮回归：规格向导出题客观边界 + 拆解阶段向导重弹。

9999 项目现场：1197 字微剧本出「约 7 分钟」时长候选（旧 3 字/秒旁白速率
上限公式），画幅候选是模型自造电影规格（2.35:1/1.43:1 IMAX/1.85:1，
无 16:9）；规格收集完成后关键元素拆解暂停卡又混回 12 个规格选项
（spec_collected 一次性标记已被规格审阅暂停消费，向导渲染不看文档状态）。
"""
import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import executors as ex_mod
from src.video_agent.state.manager import StateManager
from src.video_agent.skill_runtime import exec_common
from src.video_agent.skill_runtime import exec_spec

_SPEC_FULL = (
    "- **画幅比例**：16:9\n- **目标时长**：约 4 分钟\n"
    "- **影像风格基调**：冷峻写实的高反差色调\n- **输出语言**：中文普通话\n"
)
_CANDS = {
    "画幅比例": ["2.35:1 宽银幕比例", "1.43:1 IMAX比例", "1.85:1 电影常规比例"],
    "目标时长": ["约 4 分钟", "约 5.5 分钟", "约 7 分钟"],
    "影像风格基调": ["冷峻写实的高反差色调", "幽暗深邃的太空纪实感"],
    "输出语言": ["中文普通话", "中英双语对白"],
}
_DIMS = ["画幅比例", "目标时长", "影像风格基调", "输出语言"]


# ---------- 问题2：向导客观闸门（只渲染规格里未定稿的维度） ----------

def test_merge_wizard_not_remerged_after_spec_finalized(monkeypatch):
    """9999 现场复现：规格已收集（一次性标记已被消费、不在状态里），
    规格文档四维全部定稿，拆解阶段模型自发暂停 → 向导不得再混入。"""
    monkeypatch.setattr(prompt_gates, "skill_spec_dimensions", lambda skill: list(_DIMS))
    state = {
        "usedSkills": ["AI-短剧一站式生成"],
        "documents": [{"name": "Final_Video_Spec.md", "content": _SPEC_FULL}],
        "interaction": {"spec_soft_candidates": dict(_CANDS)},
    }
    opts = [{"label": "编写关键元素提示词", "description": "下一步编写提示词草案"}]
    msg, new_opts, merged = prompt_gates.merge_spec_param_wizard(
        state, "拆解完成，请审阅", opts,
    )
    assert not merged
    assert msg == "拆解完成，请审阅"
    assert [o["label"] for o in new_opts] == ["编写关键元素提示词"]


def test_build_options_only_unresolved_dims(monkeypatch):
    """（待定）维度继续渲染收敛用户，已定稿维度不再出现。"""
    monkeypatch.setattr(prompt_gates, "skill_spec_dimensions", lambda skill: list(_DIMS))
    content = (
        "- 画幅比例：16:9\n- 目标时长：（待定）\n"
        "- 影像风格基调：写实\n- 输出语言：中文\n"
    )
    state = {"usedSkills": ["S"], "interaction": {"spec_soft_candidates": dict(_CANDS)}}
    _msg, opts = prompt_gates.build_spec_param_options(content, state)
    assert {o.get("group") for o in opts} == {"目标时长"}


def test_collect_phase_renders_all_dims_without_doc(monkeypatch):
    """收集阶段（尚无规格文档）维持全量渲染，不破坏 6666 收集主链路。"""
    monkeypatch.setattr(prompt_gates, "skill_spec_dimensions", lambda skill: list(_DIMS))
    state = {"usedSkills": ["S"], "interaction": {"spec_soft_candidates": dict(_CANDS)}}
    _msg, opts = prompt_gates.build_spec_param_options("", state)
    assert {o.get("group") for o in opts} == set(_DIMS)


def test_spec_pause_card_standard_when_finalized(monkeypatch):
    """规格写入后的暂停卡：文档已定稿 → 常规审阅卡（不再依赖一次性标记）。"""
    monkeypatch.setattr(prompt_gates, "skill_spec_dimensions", lambda skill: list(_DIMS))
    state = {
        "usedSkills": ["S"],
        "documents": [{"name": "Final_Video_Spec.md", "content": _SPEC_FULL}],
        "interaction": {"spec_soft_candidates": dict(_CANDS)},
    }
    msg, opts = prompt_gates.spec_pause_card(state)
    assert msg == prompt_gates.SPEC_DOC_PAUSED_MSG
    assert not any(o.get("group") for o in opts)


# ---------- 问题1：出题客观边界（时长剧情速率 + 画幅白名单） ----------

def test_aspect_candidates_movie_ratios_rejected():
    """9999 现场候选：仅 2.35:1 命中白名单（<2）→ 回落平台标准四选。"""
    out = ex_mod._normalize_aspect_candidates(list(_CANDS["画幅比例"]))
    assert "16:9 横屏" in out and "9:16 竖屏" in out
    assert not any("IMAX" in v or "1.43" in v or "1.85" in v for v in out)


def test_aspect_candidates_keeps_valid_hits():
    out = ex_mod._normalize_aspect_candidates(["16:9 横屏", "竖屏 9:16", "21:9 超宽"])
    assert out == ["16:9 横屏", "9:16 竖屏", "21:9 宽银幕"]


def test_duration_ladder_stays_under_cap():
    assert ex_mod._duration_ladder(2) == ["约 1 分钟", "约 1.5 分钟", "约 2 分钟"]
    assert ex_mod._duration_ladder(1) == ["约 30 秒", "约 60 秒"]
    assert ex_mod._duration_ladder(4) == ["约 2 分钟", "约 3 分钟", "约 4 分钟"]


@pytest.mark.asyncio
async def test_script_analyze_9999_candidates_objective(monkeypatch, tmp_path):
    """钉死 9999 现场：1197 字微剧本 + 内层模型回现场同款错候选 →
    落盘候选的时长全部 ≤2 分钟（确定性梯度），画幅含 16:9 且无 IMAX。"""
    from src.video_agent.skill_runtime import registry
    from src.video_agent.skill_runtime.executors import (
        ScriptAnalyzeInput, ScriptAnalyzeTool,
    )
    from src.video_agent.web import skill_docs as sd

    sd.save_skill_doc(
        "9999二轮测试桩",
        "# S\n> 调用规则：测试\n<script_analyze>\n分析\n</script_analyze>\n",
    )
    registry.register_skill("9999二轮测试桩")
    monkeypatch.setattr(registry, "skill_flow_enabled", lambda skill, key: True)
    monkeypatch.setattr(registry, "spec_wizard_active", lambda skill: True)
    monkeypatch.setattr(
        prompt_gates, "skill_spec_dimensions", lambda skill: list(_DIMS),
    )

    script = "场" * 1197  # 与 9999 现场同体量 → 上限 round(1197/600) = 2 分钟
    calls = {"n": 0}

    async def fake_json(system, user, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"summary": "末日降临", "key_points": []}
        return {k: list(v) for k, v in _CANDS.items()}

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "三体简短版.md", "content": script},
    ]
    monkeypatch.setattr(exec_spec, "_llm_json_call", fake_json)
    monkeypatch.setattr(exec_common, "_resolve_chat_provider", lambda p="", m="": ("f", "f"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    result = await ScriptAnalyzeTool().aexecute(
        ScriptAnalyzeInput(skill_name="9999二轮测试桩", doc_name="三体简短版.md")
    )
    assert result.success
    # 批3 分离：候选出题 = collect_spec 独立节点
    await exec_spec.run_collect_spec_node(svc, "9999二轮测试桩")
    cands = (svc.state_dict.get("interaction") or {}).get("spec_soft_candidates") or {}
    durs = cands.get("目标时长") or []
    assert durs, "时长维度候选全超限时必须有确定性回落"
    for d in durs:
        assert ex_mod._candidate_minutes(d) <= 2
    assert "约 7 分钟" not in durs
    aspects = cands.get("画幅比例") or []
    assert "16:9 横屏" in aspects
    assert not any("IMAX" in v for v in aspects)
    registry.reset_registry()
