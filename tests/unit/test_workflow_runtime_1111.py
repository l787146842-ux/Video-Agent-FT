# -*- coding: utf-8 -*-
"""1111 黄金轮次契约（宪法 v6 Rule2 / ADR-0003，用户审定计划钉死）。

对照 tests/fixtures/workflow_1111_baseline.json（修复前基线）断言改善：
① 轮1 缺剧本 → kind=remind 机械卡：零 LLM、正文非空、卡≠正文复述；
② 轮3 带附件推进信号 → runtime 直跑分析：零模型规划轮、选项面系统派生
   （「确认，进入「制作规格」」前置、无模型自造继续/裸值规格组）、
   时间线含 collect_spec 独立条目且无 model_reasoning；
③ 自由提问（无推进信号）→ 交接模型循环（不错抓）；
④ 向导发送 → 机械落盘进产物账本 + 文档卡补落同轮可见；
⑤ read_skill canonical 身份归一（去连字符误差不报错）。
"""
import asyncio
import json
import pathlib

import pytest

SKILL = "AI-短剧一站式生成"
BASELINE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "workflow_1111_baseline.json"


def _baseline_has_planning_rounds() -> bool:
    """修复前基线含 model_reasoning 规划轮（本文件断言修复后为零）。"""
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return any(
        a.get("name") == "model_reasoning"
        for m in data.get("messages") or []
        for s in m.get("traceSteps") or []
        for a in s.get("actions") or []
    )


def test_baseline_records_pre_fix_planning_rounds():
    assert _baseline_has_planning_rounds()


@pytest.mark.asyncio
async def test_turn1_script_missing_remind_card_zero_llm(tmp_path):
    """① 缺剧本 → remind 卡：零模型、正文非空、卡为短问句（三通道）。"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    planner = Planner(state_manager=svc, llm_adapter=None, tool_manager=None)
    result = await planner.handle_message(
        "开始制作", PlannerContext(skill_name=SKILL))
    assert result.steps == 1
    assert result.pause_kind == "remind"
    assert result.text.strip(), "引导词归正文通道（禁空正文）"
    assert result.confirmation and result.confirmation != result.text, \
        "卡=一句问句，不复述正文"
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_turn3_direct_run_zero_planning_rounds(tmp_path, monkeypatch):
    """② 附件推进信号 → runtime 直跑：零模型调用、选项面系统派生、
    时间线无 model_reasoning、collect_spec 独立条目。"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager
    from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
    from src.video_agent.skill_runtime import exec_tools
    from src.video_agent.tools.base import ToolResult
    from src.video_agent.tools.manager import ToolManager

    class ProbeAdapter(BaseChatAdapter):
        def __init__(self):
            self.calls = 0

        @property
        def supports_function_calling(self):
            return False

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return ChatResponse(content="不应被调用", finish_reason="stop")

        async def chat_stream(self, messages, **kwargs):
            self.calls += 1
            yield ChatResponse(content="不应被调用", finish_reason="stop")

    async def fake_analyze(self, params):
        svc_now = StateManager.get_instance()
        svc_now.state_dict["analysis"] = {
            "summary": "程心苏醒与掩体失效。", "key_points": [], "doc_name": "剧本.md"}
        return ToolResult(success=True, data={"summary": "程心苏醒与掩体失效。"})

    async def fake_candidates(*a, **k):
        return None

    monkeypatch.setattr(exec_tools.ScriptAnalyzeTool, "aexecute", fake_analyze)
    monkeypatch.setattr(exec_tools.exec_spec, "_generate_soft_spec_candidates",
                        fake_candidates)
    from src.video_agent.skill_runtime.registration import register_skill_runtime_tools
    register_skill_runtime_tools()
    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：程心苏醒。"}]
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter,
                      tool_manager=ToolManager)
    result = await planner.handle_message(
        "请查看我上传的素材",
        PlannerContext(skill_name=SKILL, advance_signal="attachment"))
    assert adapter.calls == 0, "v6：确定性阶段直跑，零模型规划轮"
    assert result.text.strip()
    labels = [str(o.get("label") or "") for o in result.confirmation_options]
    assert "确认，进入「制作规格」" in labels, "选项面系统派生"
    assert not any("继续拆分" in l for l in labels), "模型自造继续选项无入口"
    assert not any(l.startswith(("16:9", "9:16")) for l in labels), \
        "模型裸值规格组无入口（向导为唯一规格交互）"
    actions = [
        a.get("name") for s in (result.trace.get("steps") or [])
        for a in (s.get("actions") or [])]
    assert "model_reasoning" not in actions, "直跑轮时间线无规划条目"
    assert "script_analyze" in actions
    assert "collect_spec" in actions, "候选出题独立节点可见"
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_question_turn_handoff_to_model(tmp_path):
    """③ 自由提问（无推进信号）→ 交接模型循环。"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager
    from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse

    class ProbeAdapter(BaseChatAdapter):
        def __init__(self):
            self.calls = 0

        @property
        def supports_function_calling(self):
            return False

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return ChatResponse(content="我是创作助手。", finish_reason="stop")

        async def chat_stream(self, messages, **kwargs):
            self.calls += 1
            yield ChatResponse(content="我是创作助手。", finish_reason="stop")

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文。"}]
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=None)
    await planner.handle_message(
        "这个剧本讲什么？", PlannerContext(skill_name=SKILL))
    assert adapter.calls >= 1, "提问轮必须交接模型循环"
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_wizard_send_artifact_ledger_and_doc_card(tmp_path):
    """④ 向导发送 → 产物账本 + 文档卡补落（同轮可见，非空消息 hack 退役）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web import chat_consume

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["usedSkills"] = [SKILL]
    svc.state_dict["interaction"] = {"spec_soft_candidates": {
        "画幅比例": ["16:9 横屏", "9:16 竖屏"]}}
    note = chat_consume._consume_spec_wizard(svc, "画幅比例：16:9 横屏")
    assert note, "机械落盘回执随用户消息回喂模型"
    run = svc.state_dict.get("workflow_run") or {}
    assert "Final_Video_Spec.md" in (run.get("artifacts") or []), \
        "ArtifactCommitted 一等条目"
    emitted = []

    async def fake_emit(ev):
        emitted.append(ev)

    name = await chat_consume.emit_pending_doc_card(svc, "t1", fake_emit)
    assert name == "Final_Video_Spec.md"
    assert any(e.get("type") == "doc_written" for e in emitted), \
        "文档卡即显事件同轮下发"
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_read_skill_canonical_identity(tmp_path):
    """⑤ 模型名字误差（去连字符）经 canonical 归一不再报错。"""
    from src.video_agent.tools.document_tools import ReadSkillTool

    tool = ReadSkillTool()
    params = tool.get_input_schema()(name="AI短剧一站式生成")
    result = await tool.aexecute(params)
    assert result.success, f"canonical 归一应命中：{result.error}"
    assert (result.data or {}).get("content")
