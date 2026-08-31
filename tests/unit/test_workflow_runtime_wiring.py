# -*- coding: utf-8 -*-
"""v2 批1 接线回归：WorkflowRuntime 入主链（轮始 run 同步 + decision 消费）。

钉死（主体回归 ADR-0004 后语义）：
① 轮始 start_run 幂等创建 run；缺原料 → waiting_user + InputRequested（层 9 提醒卡）；
② 推进信号消费输入类 decision → DecisionResolved + ready；
③ 附件轮交接模型循环（模型唯一行动主体，runtime 不自主提交节点）。
"""
import pytest

from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager
from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.workflow_events import EventLedger
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


# （原 _fake_analyze：exec_tools.ScriptAnalyzeTool 探针已随任务#36 B5
# 执行器一步退役删除，代跑路径不复存在。）


@pytest.fixture
def env(tmp_path, monkeypatch):
    # （原 register_skill_runtime_tools + ScriptAnalyzeTool.aexecute 探针已随
    # 任务#36 B5 执行器一步退役删除：系统代跑路径不复存在，
    # 「runtime 不自主提交节点」由探针适配器 calls 断言钉死。）
    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter,
                      tool_manager=ToolManager)
    yield svc, adapter, planner
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_write_spec_wizard_chain_retired(env):
    """v2 批2 向导落盘/审阅链已随用户裁决 2026-08-31 退役（D-08 清偿）：
    _consume_spec_wizard 已删除，规格交互归模型自主对话。"""
    from src.video_agent.web import chat_consume
    assert not hasattr(chat_consume, "_consume_spec_wizard")


def test_workflow_projection_no_decision_no_payload(env):
    """任务 #3：无挂起决策时不附 payload（投影只读派生，不造壳）。"""
    from src.video_agent.core import workflow_runtime
    svc, _adapter, _planner = env
    proj = workflow_runtime.project(svc.state_dict)
    assert proj["pending_decision"] is False
    assert "pending_decision_payload" not in proj
