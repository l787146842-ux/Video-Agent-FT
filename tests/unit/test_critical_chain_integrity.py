"""6666 事故回归：铁律文档每轮确保 + 消息文本识别 Skill +
关键工具失败防虚报 + prelude 时间线恢复。
（FC 向执行器注入 skill_name / 执行器强制主模型用例已随任务#36 B5
执行器一步退役删除：执行器工具不复存在，管线阶段改由通用主路径直走平台工具。）
"""

import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.base import ToolResult


def test_iron_rules_ensured_on_real_chat(tmp_path, monkeypatch):
    """真实聊天/任务路径每轮确保《执行铁律.md》存在。"""
    from src.video_agent.core.spec_rules import find_iron_rules_doc
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_service import _stream_worker_impl
    from tests.unit.test_agent_task_transport import _fake_body, _stub_chat_planner

    _stub_chat_planner(monkeypatch)

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["documents"] = []
    body = _fake_body()

    async def emit(_ev):
        pass

    import asyncio
    asyncio.run(_stream_worker_impl(body, svc, emit))
    assert find_iron_rules_doc(svc.state_dict) is not None


# test_fc_injects_skill_name_into_executor_args 已随任务#36 B5 执行器一步退役删除：
# skill_name 强制注入只为执行器工具（已删），平台工具 schema 自带所需参数。


def test_message_text_skill_match():
    """消息文本里出现已注册 Skill 名 → 自动绑定（不依赖请求字段/模型）。"""
    assert registry.match_skill_name_from_text("AI-短剧一站式生成") == "AI-短剧一站式生成"
    from src.video_agent.web.chat_service import _resolve_skill_name_for_injection
    assert _resolve_skill_name_for_injection("", "", {}, "请帮我跑 AI-短剧一站式生成") == "AI-短剧一站式生成"


def test_false_claim_overridden_when_critical_tools_fail(tmp_path, monkeypatch):
    """C1a 裁决 2026-08-31：关键步骤防虚报覆盖退役——模型暂停文案不再被
    客观账本改写；工具失败事实经 ToolResult 回喂通道可见。"""
    import asyncio

    from src.video_agent.state.manager import StateManager

    tmp_svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: tmp_svc))
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    raw = {"documents": [], "usedSkills": ["AI-短剧一站式生成"], "interaction": {}}

    class _TM:
        async def invoke_tool(self, name, args):
            if name == "document_write":
                return ToolResult(success=False, error="磁盘写入失败")
            if name == "workflow_pause":
                return ToolResult(success=True, data={})
            return ToolResult(success=True, data={})

    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: raw))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "进度日志.md", "content": "x"})}},
        {"id": "c2", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({"message": "文档写入已完成，请审阅"})}},
    ])
    _applied, confirmation, *_rest = asyncio.run(
        runner.execute(response, injected_skill="AI-短剧一站式生成", gate_override="all"))
    tool_results = _rest[4]
    # 不再覆盖暂停文案；失败事实经 ToolResult 回喂可见
    assert "关键步骤未全部完成" not in confirmation
    assert any(
        t.get("name") == "document_write" and t.get("ok") is False
        for t in tool_results)


# test_executor_force_main_chat_model 已随任务#36 B5 执行器一步退役删除：
# 被测行为（执行器内层 LLM 调用强制主模型）不复存在；管线阶段改由模型
# 直接调用平台工具，模型路由统一走主对话链，无执行器内层调用可串线。


@pytest.mark.asyncio
async def test_prelude_notes_recorded_in_trace(tmp_path):
    """prelude（加载 Skill 流程/读取存档文档）进入执行轨迹，前端时间线可见。"""
    from src.video_agent.core.agent_loop import run_agent_loop
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core.action_executor import StateOperationExecutor

    svc = StateManager(str(tmp_path / "ws"))
    ex = StateOperationExecutor(svc, gate_enabled=False)

    async def llm(system_prompt, messages, stream_hook=None):
        return ("完成", "stop", 0)

    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
        prelude_notes=[("system", "加载 Skill「AI-短剧一站式生成」流程规范进上下文")],
    )
    assert "加载 Skill「AI-短剧一站式生成」流程规范进上下文" in str(result.trace)
