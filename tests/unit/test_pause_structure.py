"""暂停回应结构化闭环（对标 AskUserQuestion 范式）。

confirm 产生源（FC workflow_pause / 轮末策略卡）在汇流点一统一签发 pause_id
并登记 interaction.active_pause；原料闸/规格闸提醒类兜底卡已出槽（批 B，
不登记不签发，正文注入 + quick-actions 芯片）；用户点选回应经
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


class TestOrchestratorConfluenceSlotFree:
    """汇流点二：提醒类兜底卡出槽（批 B）——不签发 pause_id、不登记
    active_pause；提醒文案归正文通道（下一轮经 history 模型可见），
    候选项降级为 quick-actions 芯片（点击 = 普通用户消息）。"""

    async def test_handoff_returns_none(self, svc, monkeypatch):
        from src.video_agent.core import stage_probes as po

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

        # 三态消费（问即停，决策史见 git tag adr-archive-20260901）：点选缺省 accept，随标记落盘可重建
        assert marker == {"pause_id": "abc123", "value": "确认推进",
                          "label": "确认", "decision": "accept"}
        assert "active_pause" not in (svc.state_dict.get("interaction") or {})
        assert (svc.state_dict.get("interaction") or {})\
            .get("last_pause_decision") == "accept"

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
    """单一活跃暂停槽位防御断言（问即停）：已有未消费暂停时
    重复 workflow_pause 照常发行（新卡覆盖旧卡解除死锁），只告警 +
    trace 留痕，不再以拒因回喂模型；发行确认后暂停三态事务写入。"""

    @pytest.fixture(autouse=True)
    def _ensure_platform_tools(self):
        # 显式重注册：同 worker 其它用例的 ToolManager.reset() 可能清空全局
        # 注册表，确认闸读 approval_tier 后未注册即拦，本类不依赖导入副作用
        #（与 test_batch_c_active_skill_and_self_heal 同口径）
        from src.video_agent.tools.document_tools import register_document_tools

        register_document_tools()

    @pytest.mark.asyncio
    async def test_duplicate_pause_overrides_old_card(self, svc):
        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.manager import ToolManager

        inter = svc.state_dict.setdefault("interaction", {})
        inter["active_pause"] = {"pause_id": "existing1", "message": "m", "options": []}

        runner = FCToolRunner(ToolManager)
        resp = ChatResponse(content="", finish_reason="tool_calls", tool_calls=[
            {"id": "wp1", "type": "function", "function": {
                "name": "workflow_pause",
                "arguments": '{"message": "再暂停一次"}'}}])
        result = await runner.execute(resp)
        applied, confirmation = result[0], result[1]
        assert applied == 1, "防御断言只告警留痕，不再拒收（解除死锁）"
        assert confirmation, "重复暂停照常上抛 confirmation（新卡覆盖旧卡）"
        new_pid = result.pause_id
        assert new_pid and new_pid != "existing1"
        active = (svc.state_dict.get("interaction") or {}).get("active_pause") or {}
        assert active.get("pause_id") == new_pid, "新卡登记覆盖旧卡"
        assert active.get("message") == confirmation

    @pytest.mark.asyncio
    async def test_pause_issues_atomic_state_when_slot_free(self, svc):
        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.manager import ToolManager

        runner = FCToolRunner(ToolManager)
        resp = ChatResponse(content="", finish_reason="tool_calls", tool_calls=[
            {"id": "wp2", "type": "function", "function": {
                "name": "workflow_pause",
                "arguments": '{"message": "请确认是否继续"}'}}])
        result = await runner.execute(resp)
        assert result[0] == 1, "槽位空闲时暂停正常受理"
        # 事务性写入（问即停）：三态在发行确认后一次原子落盘，
        # 工具体不写状态；卡片文案与登记同源同口径
        inter = svc.state_dict.get("interaction") or {}
        assert result.pause_id, "发行点必须签发 pause_id"
        assert inter.get("awaiting_confirmation") is True
        assert inter.get("confirmation_message") == result[1]
        active = inter.get("active_pause") or {}
        assert active.get("pause_id") == result.pause_id
        assert active.get("message") == result[1]

    @pytest.mark.asyncio
    async def test_pause_breaks_same_batch(self, svc):
        """问即停：暂停发行成功即结束本批，同批后续调用不执行也不回喂拒因"""
        import json as _json

        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.base import ToolResult

        invoked = []

        class StubManager:
            async def invoke_tool(self, name, args):
                invoked.append(name)
                return ToolResult(success=True, data={"paused": True})

        runner = FCToolRunner(StubManager())
        resp = ChatResponse(content="", finish_reason="tool_calls", tool_calls=[
            {"id": "c1", "function": {"name": "workflow_pause",
                                      "arguments": _json.dumps({"message": "请确认"})}},
            {"id": "c2", "function": {"name": "storyboard_create_group",
                                      "arguments": "{}"}},
        ])
        out = await runner.execute(resp)
        assert invoked == ["workflow_pause"], "暂停后同批后续调用不执行（问即停）"
        assert all(t.get("ok") for t in out[6]), "悬挂调用不产生拒因回喂"
        assert out[1], "暂停文案照常上抛"

    @pytest.mark.asyncio
    async def test_defensive_assertion_hit_keeps_state_clean(self, svc):
        """防御断言命中时状态干净（批 A 遗留债回归）：重复暂停照常受理发行，
        暂停三态以新卡为准一次事务覆写，无「状态说已暂停、结果被拒」的混合死态；
        消费侧标记（last_pause_decision）只由消费写入，发行不污染。"""
        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.manager import ToolManager

        inter = svc.state_dict.setdefault("interaction", {})
        inter["awaiting_confirmation"] = True
        inter["confirmation_message"] = "旧卡文案"
        inter["active_pause"] = {"pause_id": "old123", "message": "旧卡文案", "options": []}

        runner = FCToolRunner(ToolManager)
        resp = ChatResponse(content="", finish_reason="tool_calls", tool_calls=[
            {"id": "wp3", "type": "function", "function": {
                "name": "workflow_pause",
                "arguments": '{"message": "第二次暂停请求"}'}}])
        result = await runner.execute(resp)

        assert result.applied == 1, "防御断言只告警留痕，发行不被拒收"
        pause_tr = [t for t in result.tool_results if t.get("name") == "workflow_pause"]
        assert pause_tr and pause_tr[0].get("ok"), "工具本体照常受理（无拒因回喂残留）"
        new_pid = result.pause_id
        assert new_pid and new_pid != "old123"
        inter_after = svc.state_dict.get("interaction") or {}
        active = inter_after.get("active_pause") or {}
        assert active.get("pause_id") == new_pid, "active_pause 以新卡覆写（旧卡无残留）"
        assert active.get("message") == result.confirmation
        assert inter_after.get("awaiting_confirmation") is True
        assert inter_after.get("confirmation_message") == result.confirmation, \
            "暂停三态同源一致（无混合死态）"
        assert "last_pause_decision" not in inter_after, \
            "消费侧标记只由消费写入，发行路径不污染"


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
