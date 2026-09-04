# -*- coding: utf-8 -*-
"""三通道分离 A 回归：阶段成果由层 9 确定性渲染进正文（1111 事故正向修复）。

成果（结构化分析）不再依赖模型自觉塞进 pause message，而是渲染器
从 state 机械产出 markdown 追加进正文；判重内置防双显。
"""
from types import SimpleNamespace

from src.video_agent.core.agent_loop import AgentLoopResult
from src.video_agent.core.planner_output import assemble_response
from src.video_agent.core.stage_deliverables import render_stage_deliverables

_STATE = {
    "analysis": {
        "doc_name": "三体简短版.md",
        "summary": "太阳系确认遭遇疑似二向箔的白色薄片打击。",
        "key_points": [
            "核心人物：程心、AA、曹彬。",
            "核心场景：木星轨道「星环」号球形舱。",
            "无标题单条要点",
        ],
    }
}


def test_render_script_analyze_markdown():
    """analysis → 正文 markdown：标题/总结/要点（冒号拆粗体标题）。"""
    out = render_stage_deliverables(_STATE, ["script_analysis_report"])
    assert "## 剧本分析《三体简短版.md》" in out
    assert "**一句话总结**：太阳系确认遭遇疑似二向箔的白色薄片打击。" in out
    assert "- **核心人物**：程心、AA、曹彬。" in out
    assert "- 无标题单条要点" in out


def test_render_no_hit_returns_empty():
    """未注册工具/无分析存档 → 空串（行为不侵入）。"""
    assert render_stage_deliverables(_STATE, ["storyboard_shots"]) == ""
    assert render_stage_deliverables({}, ["script_analysis_report"]) == ""


def _executor_with_state(state):
    return SimpleNamespace(
        action_log=[], documents_written=[], chat_inserts=[], state=state)


def _loop_with_trace(text="剧本分析完成，请审阅。"):
    lr = AgentLoopResult(text=text, confirmation="请确认")
    lr.trace = {"steps": [{"actions": [{"name": "script_analysis_report", "ok": True}]}]}
    return lr


def test_assemble_appends_deliverable_to_body():
    """本轮分析写入工具成功 → 成果块进正文（成果通道归系统）。"""
    resp = assemble_response(
        _loop_with_trace(), executor=_executor_with_state(_STATE),
        response_factory=lambda **kw: kw,
        analysis_summary=_STATE["analysis"]["summary"],
    )
    assert "## 剧本分析《三体简短版.md》" in resp["text"]
    assert resp["text"].startswith("剧本分析完成，请审阅。")


def test_assemble_dedup_when_prose_has_summary():
    """模型 prose 已含总结 → 不重复追加成果块（判重内置）。"""
    lr = _loop_with_trace(text="太阳系确认遭遇疑似二向箔的白色薄片打击。请审阅。")
    resp = assemble_response(
        lr, executor=_executor_with_state(_STATE),
        response_factory=lambda **kw: kw,
        analysis_summary=_STATE["analysis"]["summary"],
    )
    assert "## 剧本分析" not in resp["text"]


def test_assemble_no_trace_no_deliverable():
    """无 trace（纯暂停轮）→ 回落历史语义单行记账（兼容旧行为）。"""
    lr = AgentLoopResult(text="接下来暂停。", confirmation="请确认")
    resp = assemble_response(
        lr, executor=_executor_with_state(_STATE),
        response_factory=lambda **kw: kw,
        analysis_summary=_STATE["analysis"]["summary"],
    )
    assert "剧本分析已完成" in resp["text"]
