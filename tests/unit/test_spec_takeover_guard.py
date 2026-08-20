"""8888 事故回归：规格写入被拒后系统接管向导卡 + 防虚报盲区 +
前奏时间线只登记真实事件（不冒充读取/存档）。
"""

import json

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core import prompt_gates
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult


def test_prelude_only_real_events():
    """前奏只登记「加载 Skill 流程基线」；不得出现假「读取并存档上传文档」。"""
    from src.video_agent.web.chat_service import _build_prelude_notes

    notes = _build_prelude_notes("AI-短剧一站式生成")
    assert len(notes) == 1
    assert "加载 Skill「AI-短剧一站式生成」流程规范进上下文" in notes[0][1]
    assert "读取并存档" not in str(notes)
    assert "读取上传文档" not in str(notes)
    assert _build_prelude_notes("") == []


def test_fc_spec_reject_takes_over_with_wizard(tmp_path, monkeypatch):
    """script_analyze 成功 + 规格写入被向导拒收 → 接管为规格向导卡，
    模型不得用「请求阶段确认」跳过规格，也不得声称已生成规格。"""
    import asyncio

    tmp_svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: tmp_svc))
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])

    raw_state = {"documents": [], "usedSkills": ["AI-短剧一站式生成"], "interaction": {}}

    class _TM:
        async def invoke_tool(self, name, args):
            if name == "script_analyze":
                return ToolResult(success=True, data={"summary": "分析完成"})
            if name == "document_write":
                return ToolResult(success=False, error="《制片规格》由系统按向导选定自动拼装，无需手写")
            if name == "workflow_pause":
                return ToolResult(success=True, data={})
            return ToolResult(success=True, data={})

    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: raw_state))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "script_analyze", "arguments": "{}"}},
        {"id": "c2", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "制片规格.md", "content": "画幅：16:9"})}},
        {"id": "c3", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({"message": "已完成《三体简短版.md》的剧本分析，并为您生成了初步的《制作规格》文档"})}},
    ])
    _applied, confirmation, *_rest = asyncio.run(runner.execute(response, injected_skill="AI-短剧一站式生成"))
    assert "尚待您选定" in confirmation
    assert "已生成初步的《制作规格》" not in confirmation
    assert raw_state["interaction"].get("pending_pause_kind") == "spec"
    # 8888 二轮：接管时同步洗掉 workflow_pause 写入的假完成文案
    assert raw_state["interaction"].get("awaiting_confirmation") is True
    assert raw_state["interaction"].get("confirmation_message") == confirmation


def test_general_mixed_failure_override(tmp_path, monkeypatch):
    """部分关键成功、部分失败 + 模型声称全部完成 → 覆盖为诚实文案（盲区修复）。"""
    import asyncio

    tmp_svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: tmp_svc))

    class _TM:
        async def invoke_tool(self, name, args):
            if name == "script_analyze":
                return ToolResult(success=True, data={"summary": "分析完成"})
            if name == "storyboard_shots":
                return ToolResult(success=False, error="当前 Skill「未指定」未注册 storyboard_shots 执行器")
            if name == "workflow_pause":
                return ToolResult(success=True, data={})
            return ToolResult(success=True, data={})

    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "script_analyze", "arguments": "{}"}},
        {"id": "c2", "type": "function", "function": {
            "name": "storyboard_shots", "arguments": "{}"}},
        {"id": "c3", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({"message": "关键元素与分镜全部完成，请确认"})}},
    ])
    _applied, confirmation, *_rest = asyncio.run(runner.execute(response, injected_skill="AI-短剧一站式生成"))
    assert "关键步骤未全部完成" in confirmation
    assert "全部完成，请确认" not in confirmation
