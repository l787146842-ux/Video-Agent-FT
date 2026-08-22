# -*- coding: utf-8 -*-
"""9999 二轮回归：规格向导渲染客观边界。

9999 项目现场：规格收集完成后关键元素拆解暂停卡又混回 12 个规格选项
（spec_collected 一次性标记已被规格审阅暂停消费，向导渲染不看文档状态）。
（问题 1「出题客观边界」——_normalize_aspect_candidates/_duration_ladder/
collect_spec 节点候选落盘——已随任务#36 B5 执行器一步退役删除：
平台不再机械出题，规格收集改由模型按 skill_discipline 用 workflow_pause
分组向导完成。）
"""
from src.video_agent.core import prompt_gates

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


# ---------- 问题 1：出题客观边界（时长剧情速率 + 画幅白名单） ----------
# test_aspect_candidates_movie_ratios_rejected / test_aspect_candidates_keeps_valid_hits /
# test_duration_ladder_stays_under_cap / test_script_analyze_9999_candidates_objective
# 已随任务#36 B5 执行器一步退役删除：被测对象（executors 出题归一函数与
# exec_spec.run_collect_spec_node 候选落盘）不复存在。
