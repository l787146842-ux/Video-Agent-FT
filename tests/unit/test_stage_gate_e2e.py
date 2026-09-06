# -*- coding: utf-8 -*-
"""轮末阶段闸端到端测试（2026-09-06 Flova 对齐批·自查补）：
完整 handle_message_stream 轮次内，确认档下阶段翻转 → done payload
携带机械闸暂停卡（confirmation/pause_kind/pause_id + review: 挂起决议）；
微调子对话（adjust_scope）内同场景不签发（子对话不发确认卡纪律）。"""
import pytest

from src.video_agent.config import settings
from src.video_agent.core.agent_loop import AgentLoopResult
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager

SKILL = "宣言式概念短片"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


async def test_stage_gate_fires_in_full_turn(svc, monkeypatch):
    object.__setattr__(settings, "execution_mode", "key_steps_confirm")
    try:
        svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}

        async def fake_loop(user_text, **kwargs):
            # 模拟本轮模型写入规格文档 → spec 探针翻转 → current=review_spec
            svc.state_dict["documents"] = [{
                "name": "制片规格.md", "content": "时长：60 秒\n画幅：21:9",
            }]
            return AgentLoopResult(text="规格已写入", steps=1)

        monkeypatch.setattr("src.video_agent.core.planner.run_agent_loop", fake_loop)
        planner = Planner(state_manager=svc, llm_adapter=None)

        events = []
        async for ev in planner.handle_message_stream(
                "写规格", PlannerContext(use_studio_context=False, skill_name=SKILL)):
            events.append(ev)

        done = [e for e in events if e.type == "done"]
        assert done, "done 事件缺失"
        payload = done[0].payload or {}
        assert "规格审核" in (payload.get("confirmation") or ""), "完整轮次应机械签发闸卡"
        assert payload.get("pause_kind") == "stage_done"
        assert payload.get("pause_id"), "闸卡须经 _issue_pause 签发 pause_id"
        active = (svc.state_dict.get("interaction") or {}).get("active_pause") or {}
        assert active.get("pause_id") == payload.get("pause_id")
        pend = (svc.state_dict.get("workflow_run") or {}).get("pending_decision") or {}
        assert pend.get("token", "").startswith("review:")
    finally:
        object.__setattr__(settings, "execution_mode", "ai_decide")


async def test_stage_gate_silent_in_adjust_subdialog(svc, monkeypatch):
    """微调子对话（adjust_scope）内阶段翻转不签发闸卡（子对话不发确认卡）。"""
    object.__setattr__(settings, "execution_mode", "key_steps_confirm")
    try:
        svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}

        async def fake_loop(user_text, **kwargs):
            svc.state_dict["documents"] = [{
                "name": "制片规格.md", "content": "时长：60 秒",
            }]
            return AgentLoopResult(text="规格已微调写入", steps=1)

        monkeypatch.setattr("src.video_agent.core.planner.run_agent_loop", fake_loop)
        planner = Planner(state_manager=svc, llm_adapter=None)

        events = []
        async for ev in planner.handle_message_stream(
                "微调规格", PlannerContext(use_studio_context=False, skill_name=SKILL,
                                           adjust_scope={"thread": "t1"})):
            events.append(ev)

        done = [e for e in events if e.type == "done"]
        assert done and not (done[0].payload or {}).get("pause_id"), "子对话不得发闸卡"
        assert not (done[0].payload or {}).get("confirmation")
        run = svc.state_dict.get("workflow_run") or {}
        assert not run.get("pending_decision"), "子对话不得挂起 review 决议"
    finally:
        object.__setattr__(settings, "execution_mode", "ai_decide")
