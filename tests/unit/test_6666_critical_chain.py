"""6666 事故回归：铁律文档每轮确保 + FC 执行器注入 skill_name +
消息文本识别 Skill + 关键工具失败防虚报 + prelude 时间线恢复。
"""

import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.base import ToolResult


def test_6666_iron_rules_ensured_on_real_chat(tmp_path):
    """真实聊天/任务路径每轮确保《执行铁律.md》存在（不能只在 mock 路径创建）。"""
    from src.video_agent.core.spec_rules import find_iron_rules_doc
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_service import _stream_worker_impl
    from tests.unit.test_agent_task_transport import _mock_body

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["documents"] = []
    body = _mock_body()

    async def emit(_ev):
        pass

    import asyncio
    asyncio.run(_stream_worker_impl(body, svc, emit))
    assert find_iron_rules_doc(svc.state_dict) is not None


def test_6666_fc_injects_skill_name_into_executor_args(monkeypatch):
    """FC 调用执行器时，模型没带 skill_name → 平台强制注入 injected_skill。"""
    captured = {}

    class _TM:
        async def invoke_tool(self, name, args):
            captured["args"] = dict(args)
            return ToolResult(success=True, data={"summary": "ok"})

    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "script_analyze",
            "arguments": json.dumps({"doc_name": "剧本.md"}),
        }},
    ])
    import asyncio
    asyncio.run(runner.execute(response, injected_skill="AI-短剧一站式生成"))
    assert captured["args"].get("skill_name") == "AI-短剧一站式生成"


def test_6666_message_text_skill_match():
    """消息文本里出现已注册 Skill 名 → 自动绑定（不依赖请求字段/模型）。"""
    assert registry.match_skill_name_from_text("AI-短剧一站式生成") == "AI-短剧一站式生成"
    from src.video_agent.web.chat_service import _resolve_skill_name_for_injection
    assert _resolve_skill_name_for_injection("", "", {}, "请帮我跑 AI-短剧一站式生成") == "AI-短剧一站式生成"


def test_6666_false_claim_overridden_when_critical_tools_fail(tmp_path, monkeypatch):
    """script_analyze/document_write(规格) 失败但模型带确认声称完成 →
    8888 升级后由规格向导卡接管（不允许假完成文案）。"""
    import asyncio

    from src.video_agent.state.manager import StateManager

    tmp_svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: tmp_svc))
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    raw = {"documents": [], "usedSkills": ["AI-短剧一站式生成"], "interaction": {}}

    class _TM:
        async def invoke_tool(self, name, args):
            if name == "script_analyze":
                return ToolResult(success=False, error="当前 Skill「未指定」未注册 script_analyze 执行器")
            if name == "document_write":
                return ToolResult(success=False, error="《制片规格》由系统按向导选定自动拼装，无需手写")
            if name == "workflow_pause":
                return ToolResult(success=True, data={})
            return ToolResult(success=True, data={})

    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: raw))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "script_analyze", "arguments": "{}"}},
        {"id": "c2", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "制片规格.md", "content": "x"})}},
        {"id": "c3", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({"message": "剧本分析与全局参数设定已完成，请审阅"})}},
    ])
    _applied, confirmation, *_rest = asyncio.run(runner.execute(response, injected_skill="AI-短剧一站式生成"))
    assert "尚待您选定" in confirmation
    assert "剧本分析与全局参数设定已完成" not in confirmation
    assert raw["interaction"].get("pending_pause_kind") == "spec"


@pytest.mark.asyncio
async def test_6666_prelude_notes_recorded_in_trace(tmp_path):
    """prelude（加载 Skill 流程/读取存档文档）进入执行轨迹，前端时间线可见。"""
    from src.video_agent.core.agent_loop import run_agent_loop
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.actions import StudioActionExecutor

    svc = StateManager(str(tmp_path / "ws"))
    ex = StudioActionExecutor(svc, gate_enabled=False)

    async def llm(system_prompt, messages, stream_hook=None):
        return ("完成", "stop", 0)

    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
        prelude_notes=[("system", "加载 Skill「AI-短剧一站式生成」流程规范进上下文")],
    )
    assert "加载 Skill「AI-短剧一站式生成」流程规范进上下文" in str(result.trace)
