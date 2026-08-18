# -*- coding: utf-8 -*-
"""0818-2222 运行复盘回归 — 执行器冗余重跑 / 慢 / 一句话总结残留。

本文件覆盖：
① 步级总结拼接接 Skill 声明门禁（与 B20 轮末组装对齐，平台不全局化）
② 规格文档已定稿时 script_analyze 不再跑软参数候选出题（省冗余独立 LLM）
③ 暂停轮正文补客观完成记账（防「接下来解析」承诺句误导下一轮重跑执行器）
   + 双轨阶段账本统一（FC 轨轮末策略不漏）
"""
import inspect
from types import SimpleNamespace

import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.agent_loop import AgentLoopResult
from src.video_agent.core.planner import Planner
from src.video_agent.core.planner_output import assemble_response


# ---------- ① 步级总结拼接归 Skill 声明驱动 ----------

def test_0818_step_prepend_skipped_when_skill_not_declaring(monkeypatch):
    """未声明总结展示的 Skill：步级拼接不生效（正文原样返回）。"""
    from src.video_agent.core import planner_output

    monkeypatch.setattr(prompt_gates, "skill_declares_summary", lambda name: False)
    tr = [{"name": "script_analyze", "ok": True, "data": {"summary": "总结A"}}]
    out = planner_output.maybe_prepend_script_summary("接下来我先解析。", tr, "某Skill")
    assert out == "接下来我先解析。"


def test_0818_step_prepend_applies_when_skill_declares(monkeypatch):
    """声明总结展示的 Skill：步级拼接照常生效（语义与 prepend_script_summary 一致）。"""
    from src.video_agent.core import planner_output

    monkeypatch.setattr(prompt_gates, "skill_declares_summary", lambda name: True)
    tr = [{"name": "script_analyze", "ok": True, "data": {"summary": "总结A"}}]
    out = planner_output.maybe_prepend_script_summary("接下来我先解析。", tr, "某Skill")
    assert out.startswith("**剧本一句话总结**：总结A")


def test_0818_planner_fc_track_uses_gated_prepend():
    """钉死：FC 轨步级拼接走带门禁的 helper，无门禁旧路径不复存在。"""
    src = inspect.getsource(Planner.handle_message)
    assert "maybe_prepend_script_summary(content, tool_results" in src
    assert "_prepend_script_summary(content, tool_results)" not in src


# ---------- ② 规格已定稿不再出软参数候选 ----------

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


# ---------- ③ 暂停轮客观完成记账 ----------

def _executor_stub(stages=()):
    return SimpleNamespace(
        skill_stages_done=set(stages),
        action_log=[],
        documents_written=[],
        chat_inserts=[],
    )


def test_0818_pause_text_gets_objective_done_note():
    """script_analyze 完成且暂停：正文保留模型 prose 并追加客观完成行，
    下一轮历史能看到分析已完成的客观事实。"""
    lr = AgentLoopResult(
        text="素材已就位。接下来我先对剧本做结构化解析。",
        confirmation="暂停待确认",
    )
    resp = assemble_response(
        lr, executor=_executor_stub({"script_analyze"}),
        response_factory=lambda **kw: kw,
    )
    assert resp["text"].startswith("素材已就位。")
    assert "剧本分析已完成" in resp["text"]


def test_0818_pause_note_dedup_and_scope():
    """判重与触发边界：正文已含完成陈述不重复；未暂停/未跑解析不追加。"""
    # 正文已含客观完成 → 不重复拼
    lr = AgentLoopResult(text="剧本分析已完成，按流程停在阶段边界。", confirmation="暂停")
    resp = assemble_response(
        lr, executor=_executor_stub({"script_analyze"}),
        response_factory=lambda **kw: kw,
    )
    assert resp["text"].count("剧本分析已完成") == 1

    # 未暂停 → 不追加
    lr2 = AgentLoopResult(text="接下来我先解析。", confirmation="")
    resp2 = assemble_response(
        lr2, executor=_executor_stub({"script_analyze"}),
        response_factory=lambda **kw: kw,
    )
    assert resp2["text"] == "接下来我先解析。"

    # 本轮未跑 script_analyze → 不追加
    lr3 = AgentLoopResult(text="接下来我先解析。", confirmation="暂停")
    resp3 = assemble_response(lr3, executor=_executor_stub(), response_factory=lambda **kw: kw)
    assert resp3["text"] == "接下来我先解析。"


def test_0818_fc_stage_ledger_merged_into_round_end():
    """钉死：循环结束后 FC 轨阶段账本并入文本轨 executor，轮末策略不漏 FC 轮。"""
    src = inspect.getsource(Planner.handle_message)
    assert "skill_stages_done.update(self._fc_runner.skill_stages_done)" in src
