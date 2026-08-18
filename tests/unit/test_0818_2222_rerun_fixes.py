# -*- coding: utf-8 -*-
"""0818-2222 运行复盘回归 — 执行器冗余重跑 / 慢 / 一句话总结残留。

本文件覆盖：
① 规格文档已定稿时 script_analyze 不再跑软参数候选出题（省冗余独立 LLM）
② 暂停轮正文补客观完成记账（防「接下来解析」承诺句误导下一轮重跑执行器）
0818 架构板正批 B3：步级总结拼接与双轨账本随门禁链退役删除。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.core.agent_loop import AgentLoopResult
from src.video_agent.core.planner_output import assemble_response


# ---------- ① 规格已定稿不再出软参数候选 ----------

@pytest.mark.asyncio
async def test_0818_soft_candidates_skipped_when_spec_doc_exists(tmp_path, monkeypatch):
    """规格文档已落盘：script_analyze 跳过候选出题（零冗余 LLM）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_tools

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：罗辑：黑暗森林。"}]
    svc.state_dict["documents"] = [
        {"name": "Final_Video_Spec.md", "content": "# 最终成片规格\n- 画幅：16:9\n"}]
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    async def fake_json_call(system, user, **kwargs):
        return {"summary": "一句话总结", "key_points": ["要点"]}

    cand_calls = {"n": 0}

    async def fake_candidates(*a, **k):
        cand_calls["n"] += 1

    monkeypatch.setattr(exec_tools.exec_spec, "_llm_json_call", fake_json_call)
    monkeypatch.setattr(exec_tools, "tool_available", lambda skill, tool: True)
    monkeypatch.setattr(exec_tools, "_generate_soft_spec_candidates", fake_candidates)
    tool = exec_tools.ScriptAnalyzeTool()
    params = tool.get_input_schema()(skill_name="AI-短剧一站式生成", doc_name="剧本.md")
    r = await tool.aexecute(params)
    assert r.success
    assert cand_calls["n"] == 0, "规格已定稿：候选出题不得再耗独立 LLM"


@pytest.mark.asyncio
async def test_0818_soft_candidates_still_run_without_spec_doc(tmp_path, monkeypatch):
    """无规格文档（首轮）：候选出题照常（行为不变）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_tools

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：罗辑：黑暗森林。"}]
    svc.state_dict["documents"] = []  # demo 状态自带规格文档，先清掉
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    async def fake_json_call(system, user, **kwargs):
        return {"summary": "一句话总结", "key_points": ["要点"]}

    cand_calls = {"n": 0}

    async def fake_candidates(*a, **k):
        cand_calls["n"] += 1

    monkeypatch.setattr(exec_tools.exec_spec, "_llm_json_call", fake_json_call)
    monkeypatch.setattr(exec_tools, "tool_available", lambda skill, tool: True)
    monkeypatch.setattr(exec_tools, "_generate_soft_spec_candidates", fake_candidates)
    tool = exec_tools.ScriptAnalyzeTool()
    params = tool.get_input_schema()(skill_name="AI-短剧一站式生成", doc_name="剧本.md")
    r = await tool.aexecute(params)
    assert r.success
    assert cand_calls["n"] == 1


# ---------- ② 暂停轮客观完成记账 ----------

def _executor_stub():
    return SimpleNamespace(
        action_log=[],
        documents_written=[],
        chat_inserts=[],
    )


def test_0818_pause_text_gets_objective_done_note():
    """分析已存档且暂停：正文保留模型 prose 并追加客观完成行，
    下一轮历史能看到分析已完成的客观事实。"""
    lr = AgentLoopResult(
        text="素材已就位。接下来我先对剧本做结构化解析。",
        confirmation="暂停待确认",
    )
    resp = assemble_response(
        lr, executor=_executor_stub(),
        response_factory=lambda **kw: kw,
        analysis_summary="程心苏醒与掩体失效。",
    )
    assert resp["text"].startswith("素材已就位。")
    assert "剧本分析已完成" in resp["text"]


def test_0818_pause_note_dedup_and_scope():
    """判重与触发边界：正文已含完成陈述不重复；未暂停/无分析不追加。"""
    # 正文已含客观完成 → 不重复拼
    lr = AgentLoopResult(text="剧本分析已完成，按流程停在阶段边界。", confirmation="暂停")
    resp = assemble_response(
        lr, executor=_executor_stub(),
        response_factory=lambda **kw: kw,
        analysis_summary="x",
    )
    assert resp["text"].count("剧本分析已完成") == 1

    # 未暂停 → 不追加
    lr2 = AgentLoopResult(text="接下来我先解析。", confirmation="")
    resp2 = assemble_response(
        lr2, executor=_executor_stub(),
        response_factory=lambda **kw: kw,
        analysis_summary="x",
    )
    assert resp2["text"] == "接下来我先解析。"

    # 无分析存档 → 不追加
    lr3 = AgentLoopResult(text="接下来我先解析。", confirmation="暂停")
    resp3 = assemble_response(lr3, executor=_executor_stub(), response_factory=lambda **kw: kw)
    assert resp3["text"] == "接下来我先解析。"
