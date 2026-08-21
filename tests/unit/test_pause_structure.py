"""暂停回应结构化闭环（对标 AskUserQuestion 范式）。

三个 confirm 产生源（FC workflow_pause / 闸预检兜底卡 / 轮末策略卡）在两个
汇流点统一签发 pause_id 并登记 interaction.active_pause；用户点选回应经
ChatRequest.pause_response 结构化回携，消费匹配后随用户消息持久化
pauseAnsweredId/Value——前端「当时所选」对勾从权威登记派生，不再文本反推。
登记不改变 awaiting_confirmation 既有语义（分诊/消费链零行为变更）。
"""
import pytest

from src.video_agent.core.agent_loop import AgentLoopResult
from src.video_agent.core.planner import Planner, PlannerContext, PlannerResponse
from src.video_agent.state.manager import StateManager
from src.video_agent.web.chat_consume import consume_pause_response


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


class TestIssuePause:
    """签发与登记（单一实现 Planner._issue_pause）"""

    def test_issues_id_and_registers_active_pause(self, svc):
        planner = Planner(state_manager=svc, llm_adapter=None)
        resp = PlannerResponse(
            text="已完成拆分", confirmation="请确认拆分结果",
            confirmation_options=[{"label": "确认"}],
        )
        planner._issue_pause(resp)

        assert resp.pause_id
        active = (svc.state_dict.get("interaction") or {}).get("active_pause") or {}
        assert active.get("pause_id") == resp.pause_id
        assert active.get("message") == "请确认拆分结果"
        assert active.get("options") == [{"label": "确认"}]

    def test_noop_without_confirmation(self, svc):
        planner = Planner(state_manager=svc, llm_adapter=None)
        resp = PlannerResponse(text="普通回复")
        planner._issue_pause(resp)

        assert resp.pause_id == ""
        assert "active_pause" not in (svc.state_dict.get("interaction") or {})


class TestLoopConfluenceIssuesPause:
    """汇流点一：模型循环产出 confirmation（FC workflow_pause / 轮末策略卡）"""

    async def test_done_payload_carries_pause_id(self, svc, monkeypatch):
        async def fake_loop(user_text, **kwargs):
            return AgentLoopResult(
                text="拆分完成", confirmation="请审阅故事板", steps=1)

        monkeypatch.setattr("src.video_agent.core.planner.run_agent_loop", fake_loop)
        planner = Planner(state_manager=svc, llm_adapter=None)

        events = []
        async for ev in planner.handle_message_stream("拆一下", PlannerContext(use_studio_context=False)):
            events.append(ev)

        done = [e for e in events if e.type == "done"]
        assert done, "done 事件缺失"
        payload = done[0].payload or {}
        assert payload.get("confirmation") == "请审阅故事板"
        assert payload.get("pause_id"), "done payload 必须携带 pause_id"
        active = (svc.state_dict.get("interaction") or {}).get("active_pause") or {}
        assert active.get("pause_id") == payload["pause_id"]

    async def test_no_confirmation_no_pause_id(self, svc, monkeypatch):
        async def fake_loop(user_text, **kwargs):
            return AgentLoopResult(text="好的", steps=1)

        monkeypatch.setattr("src.video_agent.core.planner.run_agent_loop", fake_loop)
        planner = Planner(state_manager=svc, llm_adapter=None)

        events = []
        async for ev in planner.handle_message_stream("你好", PlannerContext(use_studio_context=False)):
            events.append(ev)

        done = [e for e in events if e.type == "done"]
        assert done and not (done[0].payload or {}).get("pause_id")


class TestOrchestratorConfluenceIssuesPause:
    """汇流点二：兜底卡（script_pending / spec_pending；批 12 后 paused 机械卡退场）"""

    @pytest.mark.parametrize("kind", ["script_pending", "spec_pending"])
    async def test_mechanical_cards_carry_pause_id(self, svc, monkeypatch, kind):
        from src.video_agent.core import pipeline_orchestrator as po

        async def fake_precheck(state_manager, skill, user_message=""):
            return po.OrchestratorOutcome(
                kind=kind, message="机械卡文案", options=[{"label": "确认"}])

        monkeypatch.setattr(po, "gate_precheck", fake_precheck)
        planner = Planner(state_manager=svc, llm_adapter=None)

        resp = await planner._run_gate_precheck(
            PlannerContext(skill_name="AI-短剧一站式生成"), "继续")

        assert resp is not None
        assert resp.confirmation
        assert resp.pause_id, f"{kind} 机械卡必须签发 pause_id"
        active = (svc.state_dict.get("interaction") or {}).get("active_pause") or {}
        assert active.get("pause_id") == resp.pause_id

    async def test_handoff_returns_none(self, svc, monkeypatch):
        from src.video_agent.core import pipeline_orchestrator as po

        async def fake_precheck(state_manager, skill, user_message=""):
            return None

        monkeypatch.setattr(po, "gate_precheck", fake_precheck)
        planner = Planner(state_manager=svc, llm_adapter=None)

        resp = await planner._run_gate_precheck(
            PlannerContext(skill_name="AI-短剧一站式生成"), "继续")
        assert resp is None


class TestConsumePauseResponse:
    """用户回应的结构化消费（匹配清除登记；不匹配返回 None）"""

    def test_match_clears_registration_and_returns_marker(self, svc):
        inter = svc.state_dict.setdefault("interaction", {})
        inter["active_pause"] = {"pause_id": "abc123", "message": "m", "options": []}

        marker = consume_pause_response(
            svc, {"pause_id": "abc123", "value": "确认推进", "label": "确认"})

        assert marker == {"pause_id": "abc123", "value": "确认推进", "label": "确认"}
        assert "active_pause" not in (svc.state_dict.get("interaction") or {})

    def test_mismatch_returns_none_and_keeps_registration(self, svc):
        inter = svc.state_dict.setdefault("interaction", {})
        inter["active_pause"] = {"pause_id": "abc123", "message": "m", "options": []}

        marker = consume_pause_response(svc, {"pause_id": "expired99", "value": "确认"})

        assert marker is None
        assert (svc.state_dict.get("interaction") or {}).get("active_pause")

    def test_empty_payload_returns_none(self, svc):
        assert consume_pause_response(svc, None) is None
        assert consume_pause_response(svc, {}) is None


class TestPauseSlotMutex:
    """单一活跃暂停槽位互斥（主体回归，ADR-0004）：已有未消费暂停时
    重复 workflow_pause 被拒收（结构化拒因回喂，不静默吞掉）。"""

    @pytest.mark.asyncio
    async def test_duplicate_pause_rejected_when_slot_occupied(self, svc):
        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.manager import ToolManager
        from src.video_agent.skill_runtime.registration import (
            register_skill_runtime_tools,
        )

        register_skill_runtime_tools()
        inter = svc.state_dict.setdefault("interaction", {})
        inter["active_pause"] = {"pause_id": "existing1", "message": "m", "options": []}

        runner = FCToolRunner(ToolManager)
        resp = ChatResponse(content="", finish_reason="tool_calls", tool_calls=[
            {"id": "wp1", "type": "function", "function": {
                "name": "workflow_pause",
                "arguments": '{"message": "再暂停一次"}'}}])
        result = await runner.execute(resp)
        applied, confirmation = result[0], result[1]
        assert applied == 0, "槽位被占用时暂停不计为成功动作"
        assert not confirmation, "重复暂停不上抛 confirmation（防双暂停）"

    @pytest.mark.asyncio
    async def test_pause_accepted_when_slot_free(self, svc):
        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.manager import ToolManager
        from src.video_agent.skill_runtime.registration import (
            register_skill_runtime_tools,
        )

        register_skill_runtime_tools()
        runner = FCToolRunner(ToolManager)
        resp = ChatResponse(content="", finish_reason="tool_calls", tool_calls=[
            {"id": "wp2", "type": "function", "function": {
                "name": "workflow_pause",
                "arguments": '{"message": "请确认是否继续"}'}}])
        result = await runner.execute(resp)
        assert result[0] == 1, "槽位空闲时暂停正常受理"


class TestPersistedMarkers:
    """持久化标记（前端刷新后对勾/系统动作行可重建）"""

    def test_pause_markers_roundtrip(self, svc):
        svc.add_chat_message("agent", "拆分完成", confirm="请确认", pause_id="pid1")
        svc.add_chat_message(
            "user", "确认推进",
            pause_answered={"pause_id": "pid1", "value": "确认推进", "label": "确认"})
        svc.add_chat_message("user", "放行本次拦截，继续任务", kind="system_action")

        msgs = svc.get_chat_messages()
        agent_msg, answered_msg, override_msg = msgs[-3], msgs[-2], msgs[-1]
        assert agent_msg["pauseId"] == "pid1"
        assert answered_msg["pauseAnsweredId"] == "pid1"
        assert answered_msg["pauseAnsweredValue"] == "确认推进"
        assert override_msg["kind"] == "system_action"
        # 未携带标记的消息不产生空字段
        assert "pauseId" not in answered_msg
        assert "kind" not in agent_msg
