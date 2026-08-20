# -*- coding: utf-8 -*-
"""v2 批1 接线回归：WorkflowRuntime 入主链（轮始 run 同步 + 节点推进提交）。

钉死（重构计划§一/§二）：
① 轮始 start_run 幂等创建 run；缺原料 → waiting_user + InputRequested；
② 推进信号消费输入类 decision → DecisionResolved + ready；
③ 直跑分析完成后 reducer 提交：StageSucceeded(analyze_script) +
   current_node 推进 collect_spec + completed_nodes 含 analyze_script；
④ 全程零模型调用（确定性节点不调主模型规划）。
"""
import pytest

from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager
from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.workflow_events import EventLedger
from src.video_agent.skill_runtime import exec_tools
from src.video_agent.tools.base import ToolResult
from src.video_agent.tools.manager import ToolManager

SKILL = "AI-短剧一站式生成"


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


async def _fake_analyze(self, params):
    svc_now = StateManager.get_instance()
    svc_now.state_dict["analysis"] = {
        "summary": "程心苏醒与掩体失效。",
        "key_points": ["结构：三场戏"],
        "doc_name": "剧本.md",
    }
    return ToolResult(success=True, data={"summary": "程心苏醒与掩体失效。"})


@pytest.fixture
def env(tmp_path, monkeypatch):
    from src.video_agent.skill_runtime.registration import register_skill_runtime_tools
    register_skill_runtime_tools()
    monkeypatch.setattr(exec_tools.ScriptAnalyzeTool, "aexecute", _fake_analyze)
    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter,
                      tool_manager=ToolManager)
    yield svc, adapter, planner
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_turn_start_waiting_user_and_input_requested(env):
    svc, adapter, planner = env
    result = await planner.handle_message(
        "为什么还没好？", PlannerContext(skill_name=SKILL))
    assert adapter.calls == 0
    run = svc.state_dict.get("workflow_run") or {}
    assert run.get("run_id")
    assert run.get("status") == "waiting_user"
    types = [e.event_type for e in EventLedger(svc.state_dict).by_run(run["run_id"])]
    assert "RunStarted" in types and "InputRequested" in types


@pytest.mark.asyncio
async def test_advance_signal_resolves_and_node_commit_advances(env):
    svc, adapter, planner = env
    await planner.handle_message("为什么还没好？", PlannerContext(skill_name=SKILL))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：程心苏醒。"}]
    result = await planner.handle_message(
        "请查看我上传的素材",
        PlannerContext(skill_name=SKILL, advance_signal="attachment"))
    assert adapter.calls == 0, "确定性节点零模型规划"
    assert result.applied_actions >= 1
    run = svc.state_dict.get("workflow_run") or {}
    assert run.get("pending_decision") is None
    assert run.get("status") == "ready"
    assert "analyze_script" in (run.get("completed_nodes") or [])
    assert run.get("current_node") == "collect_spec"
    types = [e.event_type for e in EventLedger(svc.state_dict).by_run(run["run_id"])]
    assert "DecisionResolved" in types
    assert "StageSucceeded" in types
    assert "TurnCommitted" in types
