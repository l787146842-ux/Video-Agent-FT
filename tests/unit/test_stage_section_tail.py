# -*- coding: utf-8 -*-
"""A' 阶段键控临时尾（stage_section_tail）回归钉（2026-09-18 批 B）。

钉死计划书 §五 的两条红线 + 窗口门控：
① 纯函数：同 (state, skill) 回放重算字节一致（不掺时间戳/随机/遍历序）；
② 不突变 state（只读构造）——「不落事件流」由 agent_loop 的 extra_messages
   通道结构性保证（拼副本、不持久化，见 agent_loop._await_llm_with_stop_guard）；
③ 窗口门控：analysis 未落账（current 节点未到设计段）/ review_storyboard
   已过 → 空串；故事板窗口（含第一批 KE 组落笔前的几步）→ 章节原文；
④ 章节逐字原文、平台零产出形态引导（红线：desc 零引导 / 不给卡面正例）。
"""
import copy

from src.video_agent.core import stage_section_tail, workflow_runtime
from src.video_agent.state.models import (
    CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS,
)

SKILL = "AI-短剧一站式生成"


def _state_in_window():
    """故事板窗口内：KE 非空、shots/audio 未齐（review_storyboard 未过）。"""
    return {
        CAT_KEY_ELEMENTS: [{"id": "ke1", "title": "角色A"}],
        CAT_SHOTS: [],
        CAT_AUDIO_ITEMS: [],
        "workflow_run": {},
    }


def _state_no_ke():
    """KE 未起：非故事板窗口。"""
    return {CAT_KEY_ELEMENTS: [], CAT_SHOTS: [], CAT_AUDIO_ITEMS: [],
            "workflow_run": {}}


# ---------- ③ 窗口门控（in_storyboard_window 客观探针） ----------

def test_window_opens_on_ke():
    """KE 非空 + review_storyboard 未过 → 窗口开。"""
    assert workflow_runtime.in_storyboard_window(_state_in_window(), SKILL) is True


def test_window_closed_no_ke():
    """KE 未起 → 窗口关（故事板设计尚未开始）。"""
    assert workflow_runtime.in_storyboard_window(_state_no_ke(), SKILL) is False


def test_window_opens_at_ke_node_before_first_ke(monkeypatch):
    """D3（3333 批）：analysis/spec/review_spec 已过、KE 尚空 → current 节点 =
    storyboard_key_elements → 窗口开（第一批 KE 组落笔时章节必须在场；
    旧实现「KE 非空」开窗致该几步章节缺席）。"""
    real = workflow_runtime._node_objectively_done

    def fake(node, run, state, skill):
        if node in ("collect_spec", "write_spec", "review_spec"):
            return True
        return real(node, run, state, skill)

    monkeypatch.setattr(workflow_runtime, "_node_objectively_done", fake)
    state = {CAT_KEY_ELEMENTS: [], CAT_SHOTS: [], CAT_AUDIO_ITEMS: [],
             "analysis": {"summary": "三幕科幻剧本"}, "workflow_run": {}}
    assert workflow_runtime.current_node_probe(state, SKILL) == \
        "storyboard_key_elements"
    assert workflow_runtime.in_storyboard_window(state, SKILL) is True


def test_window_closed_after_review(monkeypatch):
    """review_storyboard 已通过 → 窗口关（探针粒度陷阱防护：分镜确认后停注入）。"""
    monkeypatch.setattr(
        workflow_runtime, "_node_objectively_done",
        lambda node, run, state, skill: node == "review_storyboard")
    assert workflow_runtime.in_storyboard_window(_state_in_window(), SKILL) is False


def test_window_non_dict_state():
    """非 dict state → 窗口关（fail-closed）。"""
    assert workflow_runtime.in_storyboard_window(None, SKILL) is False


# ---------- 章节拼接 ----------

def test_tail_sections_in_window():
    """故事板窗口内返回章节原文（非空、含中性引导头、含 skill 章节内容）。"""
    tail = stage_section_tail.build_stage_section_tail(_state_in_window(), SKILL)
    assert tail, "故事板窗口内应注入章节"
    assert "当前制作阶段 Skill 章节原文" in tail  # 中性引导头（零产出引导）
    # 章节逐字原文来自 skill 故事板三章（key_element 登记规范）
    assert "key_element" in tail or "角色" in tail
    assert len(tail) > 200  # 三章原文有体量


def test_tail_empty_outside_window():
    """非故事板窗口（KE 未起）→ 空串，不注入。"""
    assert stage_section_tail.build_stage_section_tail(_state_no_ke(), SKILL) == ""


def test_tail_empty_skill():
    """无 skill → 空串。"""
    assert stage_section_tail.build_stage_section_tail(_state_in_window(), "") == ""


# ---------- ① 纯函数确定性（回放自证） ----------

def test_pure_deterministic():
    """同 (state, skill) 两次调用字节一致（回放重算自证，不掺非确定性）。"""
    st = _state_in_window()
    a = stage_section_tail.build_stage_section_tail(st, SKILL)
    b = stage_section_tail.build_stage_section_tail(st, SKILL)
    assert a == b
    assert a  # 非空前提下的一致性才有意义


# ---------- ② 不突变 state ----------

def test_no_state_mutation():
    """构造 A' 尾不写 state（只读；落库由 extra_messages 通道结构性杜绝）。"""
    st = _state_in_window()
    before = copy.deepcopy(st)
    stage_section_tail.build_stage_section_tail(st, SKILL)
    assert st == before


# ---------- ④ 红线：零产出形态引导 ----------

def test_no_output_form_guidance():
    """平台措辞零产出形态引导（红线）：引导头中性，不含'怎么写'类指令。"""
    tail = stage_section_tail.build_stage_section_tail(_state_in_window(), SKILL)
    for banned in ("摄像机→主体", "中文叙事式", "按此模板写", "示例desc",
                   "最高优先级"):
        assert banned not in tail


# ---------- B2：analysis 段（章节前、仅故事板窗口） ----------

def _state_in_window_with_analysis():
    st = _state_in_window()
    st["analysis"] = {"summary": "木星轨道危机开场",
                      "report": "白色薄片可被穿透却持续释放引力波"}
    return st


def test_analysis_digest_in_window():
    """故事板窗口 + 有 analysis → 临时尾含 analysis 段（summary 原文）。"""
    tail = stage_section_tail.build_stage_section_tail(
        _state_in_window_with_analysis(), SKILL)
    assert "剧本分析" in tail
    assert "木星轨道危机开场" in tail


def test_analysis_before_sections():
    """顺序：analysis 段在章节段之前（章节近生成端，近因效应）。"""
    tail = stage_section_tail.build_stage_section_tail(
        _state_in_window_with_analysis(), SKILL)
    assert tail.index("剧本分析") < tail.index("当前制作阶段 Skill 章节原文")


def test_no_analysis_only_sections():
    """无 analysis → 临时尾只有章节段（不含 analysis 头）。"""
    tail = stage_section_tail.build_stage_section_tail(_state_in_window(), SKILL)
    assert "剧本分析" not in tail
    assert "当前制作阶段 Skill 章节原文" in tail


def test_analysis_report_truncated():
    """analysis report 超预算被截断（2500 字）。"""
    st = _state_in_window()
    st["analysis"] = {"summary": "s", "report": "x" * 5000}
    tail = stage_section_tail.build_stage_section_tail(st, SKILL)
    assert tail.count("x") <= 2500


def test_analysis_pure_deterministic():
    """带 analysis 时仍纯函数（回放字节一致）。"""
    st = _state_in_window_with_analysis()
    a = stage_section_tail.build_stage_section_tail(st, SKILL)
    b = stage_section_tail.build_stage_section_tail(st, SKILL)
    assert a == b and a
