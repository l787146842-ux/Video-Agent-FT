# -*- coding: utf-8 -*-
"""Skill 流程跑通修复批 1：造格子（A1 分析落点 / A4 规格更新留痕）。

A1 —— 剧本分析有地方交卷：全仓多处读 state.analysis.summary、零处写入
（3333 事故根因之一）。本文件钉死：
- script_analysis_report 工具把分析结论写入 state.analysis（StateManager 唯一写入点）；
- 既有消费方零改动生效：stage_done("analysis") 客观探针、
  stage_deliverables 正文渲染器、context_builder 状态裁剪注入；
- summary 缺失 = 明确报错（不许假成功）；未知入参字段原子拒收。
A4 —— 规格文档可被更新且留下痕迹（document_write 覆盖式更新计修订数）。
"""
import pytest

from src.video_agent.core.stage_deliverables import render_stage_deliverables
from src.video_agent.core.stage_probes import stage_done
from src.video_agent.state.context_builder import _build_snapshot_dict
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.analysis_tools import (
    ScriptAnalyzeInput,
    register_analysis_tools,
)
from src.video_agent.tools.document_tools import WriteDocumentInput, DocumentWriteTool
from src.video_agent.tools.manager import ToolManager


@pytest.fixture(autouse=True)
def _env():
    """工具注册面隔离（状态单例由 conftest _state_singleton_isolation 钉临时区；
    测试内一律经 get_instance() 取同一实例，不与夹具顺序竞速）。"""
    ToolManager.reset()
    register_analysis_tools()
    yield
    StateManager.reset_instance()
    ToolManager.reset()


def _analysis_payload(**overrides) -> dict:
    payload = {
        "doc_name": "三体简短版.md",
        "script_class": "A",
        "summary": "太阳系确认遭遇疑似二向箔的白色薄片打击。",
        "key_points": ["核心人物：程心、AA、曹彬。", "无标题单条要点"],
        "characters": [{"name": "程心", "scenes": "太空电梯", "appearance": "东方女性"}],
        "scenes": [{"name": "太空电梯", "features": "碳纳米管", "shot_range": "1-3"}],
        "props": ["二向箔"],
        "acts": [{"act": "开篇", "shots_estimate": "3"}],
    }
    payload.update(overrides)
    return payload


# ---------- A1：写入落点 ----------


async def test_analysis_writes_state_and_flips_probe():
    """state.analysis 有写入方：工具成功 ⇒ 探针 stage_done("analysis") 翻真。"""
    assert stage_done("analysis", StateManager.get_instance().state_dict) is False
    result = await ToolManager.invoke_tool("script_analysis_report", _analysis_payload())
    assert result.success is True, result.error
    state = StateManager.get_instance().state_dict
    assert state["analysis"]["summary"] == "太阳系确认遭遇疑似二向箔的白色薄片打击。"
    assert state["analysis"]["script_class"] == "A"
    assert state["analysis"]["characters"][0]["name"] == "程心"
    assert state["analysis"]["props"] == ["二向箔"]
    assert stage_done("analysis", state) is True


async def test_analysis_empty_summary_rejected_atomically():
    """summary 为空 = 明确报错（不许假成功），且不写入任何字段。"""
    result = await ToolManager.invoke_tool(
        "script_analysis_report", _analysis_payload(summary="   "))
    assert result.success is False
    assert result.error_code == "validation"
    assert "summary" in result.error
    state = StateManager.get_instance().state_dict
    assert not (state.get("analysis") or {}), "失败路径不得半写入"
    assert stage_done("analysis", state) is False


async def test_analysis_unknown_field_rejected():
    """写类工具 extra=forbid：未知入参字段原子拒收（错误可见，不静默丢弃）。"""
    result = await ToolManager.invoke_tool(
        "script_analysis_report", _analysis_payload(bogus_field="x"))
    assert result.success is False
    assert result.error_code == "validation"
    assert "bogus_field" in result.error
    assert not (StateManager.get_instance().state_dict.get("analysis") or {})


async def test_analysis_rerender_uses_latest_state():
    """重复提交以最后一次为准（分析是可整体重写的活结论）。"""
    await ToolManager.invoke_tool("script_analysis_report", _analysis_payload())
    await ToolManager.invoke_tool(
        "script_analysis_report", _analysis_payload(summary="改定声音方向：全程无旁白。",
                                            script_class="C"))
    state = StateManager.get_instance().state_dict
    assert state["analysis"]["summary"] == "改定声音方向：全程无旁白。"


# ---------- A1：既有消费方零改动生效 ----------


async def test_stage_deliverables_renders_analysis():
    """成果渲染器按写入工具名键控命中，正文自动渲染总结与要点。"""
    await ToolManager.invoke_tool("script_analysis_report", _analysis_payload())
    state = StateManager.get_instance().state_dict
    block = render_stage_deliverables(state, ["script_analysis_report"])
    assert "## 剧本分析《三体简短版.md》" in block
    assert "**一句话总结**：太阳系确认遭遇疑似二向箔的白色薄片打击。" in block
    assert "- **核心人物**：程心、AA、曹彬。" in block


async def test_analysis_enters_context_snapshot():
    """状态裁剪注入面看到分析摘要（拆解/提示词阶段主模型必须看到）。"""
    await ToolManager.invoke_tool("script_analysis_report", _analysis_payload())
    snap = _build_snapshot_dict(StateManager.get_instance().state_dict, "")
    assert snap["analysis"]["summary"].startswith("太阳系确认遭遇")


# ---------- A4：规格文档可更新且留痕 ----------


async def test_spec_document_update_leaves_trace():
    """document_write 同名覆盖 = updated_at 刷新 + revisions 递增（新建为 0）。"""
    tool = DocumentWriteTool()
    first = await tool.aexecute(
        WriteDocumentInput(name="制片规格.md", content="# v1\n画幅 16:9"))
    assert first.success is True
    assert first.data == {"name": "制片规格.md", "action": "created", "revisions": 0}

    docs = StateManager.get_instance().state_dict["documents"]
    mine = [d for d in docs if d.get("name") == "制片规格.md"]
    assert len(mine) == 1
    updated_before = mine[0]["updated_at"]

    second = await tool.aexecute(
        WriteDocumentInput(name="制片规格.md", content="# v2\n画幅 2.39:1"))
    assert second.success is True
    assert second.data["action"] == "updated"
    assert second.data["revisions"] == 1

    docs = StateManager.get_instance().state_dict["documents"]
    mine = [d for d in docs if d.get("name") == "制片规格.md"]
    assert len(mine) == 1, "同名文档覆盖而非新增"
    assert mine[0]["content"].startswith("# v2")
    assert mine[0]["revisions"] == 1
    assert mine[0]["updated_at"] >= updated_before
