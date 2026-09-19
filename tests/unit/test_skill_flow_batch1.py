# -*- coding: utf-8 -*-
"""Skill 流程跑通修复批 1：造格子（A1 分析落点 / A4 规格更新留痕）。

A1 —— 剧本分析有地方交卷：全仓多处读 state.analysis.summary、零处写入
（3333 事故根因之一）。本文件钉死：
- script_analysis_report 工具把分析结论写入 state.analysis（StateManager 唯一写入点）；
- 既有消费方零改动生效：stage_done("analysis") 客观探针、
  event_cards 分析事件卡（detail_md 携全文挂卡折叠，对齐批 2026-09-08）、
  context_builder 状态裁剪注入；
- summary 缺失 = 明确报错（不许假成功）；未知入参字段原子拒收。
A4 —— 规格文档可被更新且留下痕迹（document_write 覆盖式更新计修订数）。
"""
import pytest

from src.video_agent.core.event_cards import product_event_card
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
        "summary": "太阳系确认遭遇疑似二向箔的白色薄片打击。",
        "report_markdown": (
            "**剧本分类**：A 类（成熟分镜剧本）\n\n"
            "**角色清单**\n- 程心：出场于太空电梯；外貌——东方女性，黑色短发\n\n"
            "**场景清单**\n- 太空电梯：碳纳米管井道，镜头 1-3\n\n"
            "**关键道具**：二向箔\n\n"
            "**幕次结构**：开篇（约 3 镜）"
        ),
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
    assert "程心" in state["analysis"]["report"]
    assert "二向箔" in state["analysis"]["report"]
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
        "script_analysis_report", _analysis_payload(summary="改定声音方向：全程无旁白。"))
    state = StateManager.get_instance().state_dict
    assert state["analysis"]["summary"] == "改定声音方向：全程无旁白。"


# ---------- A1：既有消费方零改动生效 ----------


async def test_analysis_event_card_carries_full_report():
    """分析落账 → 事件卡（对齐批 2026-09-08）：卡名/一句话明细命中，
    detail_md 携报告全文（前端折叠展示），to_ctx=False（全文不进模型上下文）。"""
    payload = _analysis_payload()
    await ToolManager.invoke_tool("script_analysis_report", payload)
    cards = product_event_card("script_analysis_report", payload, 0)
    assert len(cards) == 1
    name, detail, to_ctx, detail_md = cards[0]
    assert name == "剧本分析已完成"
    assert detail == "太阳系确认遭遇疑似二向箔的白色薄片打击。"
    assert to_ctx is False
    assert "## 剧本分析《三体简短版.md》" in detail_md
    assert "**一句话总结**：太阳系确认遭遇疑似二向箔的白色薄片打击。" in detail_md
    assert "**剧本分类**：A 类（成熟分镜剧本）" in detail_md
    assert "- 程心：出场于太空电梯" in detail_md


async def test_analysis_not_in_model_snapshot():
    """analysis 不进模型状态快照（2026-09-18 批 B 挪出；2026-09-19 退役 A'
    临时尾后不再常驻注入，对齐 flova 分析一次性使用 + 历史衰减）。
    state.analysis 仍作探针/事件卡/前端数据源；下游阶段经规格文档/读工具
    按需获取故事内容。"""
    await ToolManager.invoke_tool("script_analysis_report", _analysis_payload())
    state = StateManager.get_instance().state_dict
    # 模型状态快照不含 analysis
    snap = _build_snapshot_dict(state, "")
    assert "analysis" not in snap
    # state.analysis 仍在（探针/事件卡/前端数据源，未丢）
    assert state["analysis"]["summary"].startswith("太阳系确认遭遇")


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
