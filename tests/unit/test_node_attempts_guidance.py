"""P3-16：node_attempts 计数与「重试/换渠道」引导卡派生。

边界语义（任务书口径）：
- 失败 1 次不派生（阈值默认 2）；失败 2 次派生；
- 派生只产出引导数据（flowEvents 模型可见 + run.retry_guidance 结构化），
  不推进 run 进度（current_node/completed_nodes/run_version 零变更）；
- 同签名幂等不重复入账；计数变化重入账；成功后清账不再派生；
- 接线：FC 轨执行器真实执行失败入账（闸拒收不入账），成功清账。

ADR-0004 合规：本链路上 runtime 从不发起执行器调用——
记账（bump/clear）与派生（derive_retry_guidance）皆为数据操作，
重试/换渠道动作由模型发起工具调用（planner_triage 交接模型循环）。
"""
import json

import pytest

from src.video_agent.core import pipeline_orchestrator as po
from src.video_agent.core import planner_triage, workflow_runtime
from src.video_agent.state.manager import StateManager

_SKILL = "AI-短剧一站式生成"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    yield instance
    StateManager.reset_instance()


def _quiet_gates(svc):
    """原料闸/规格闸全静默（只观测重试引导一支的行为）"""
    svc.state_dict["interaction"] = {"script_waived": True}
    svc.state_dict["analysis"] = {"summary": "一句话"}
    svc.state_dict["documents"] = [{
        "name": "Final_Video_Spec.md", "content": "规格", "confirmed": True,
    }]


def _seed_run(svc, attempts):
    svc.state_dict["workflow_run"] = {
        "run_id": "run_t", "workflow_id": _SKILL,
        "current_node": "storyboard_shots",
        "completed_nodes": ["analyze_script"],
        "node_attempts": attempts,
        "run_version": 3, "status": "ready",
    }


def _guidance_events(svc):
    return [
        e for e in (svc.state_dict.get("flowEvents") or [])
        if e.get("kind") == "retry_guidance"
    ]


# ---------- 记账原语 ----------

class TestNodeAttemptsBookkeeping:
    def test_bump_increments_and_records_error(self):
        st = {"workflow_run": {"run_id": "r1", "node_attempts": {}}}
        assert workflow_runtime.bump_node_attempt(st, "script_analyze", "LLM 超时") == 1
        assert workflow_runtime.bump_node_attempt(st, "script_analyze", "LLM 再超时") == 2
        entry = st["workflow_run"]["node_attempts"]["script_analyze"]
        assert entry["count"] == 2
        assert entry["last_error"] == "LLM 再超时"
        assert entry["updated_at"]

    def test_bump_without_run_is_noop(self):
        st = {}
        assert workflow_runtime.bump_node_attempt(st, "script_analyze") == 0
        assert "workflow_run" not in st  # 无 run 不建壳

    def test_clear_removes_entry(self):
        st = {"workflow_run": {"run_id": "r1", "node_attempts": {"x": {"count": 2}}}}
        assert workflow_runtime.clear_node_attempt(st, "x") is True
        assert workflow_runtime.clear_node_attempt(st, "x") is False


# ---------- 引导卡派生边界 ----------

class TestRetryGuidanceDerivation:
    @pytest.mark.asyncio
    async def test_one_failure_no_guidance(self, svc):
        """失败 1 次不派生（阈值默认 2）"""
        _quiet_gates(svc)
        _seed_run(svc, {"storyboard_shots": {"count": 1, "last_error": "e"}})
        out = await po.gate_precheck(svc, _SKILL, "继续")
        assert out is None
        assert _guidance_events(svc) == []
        assert "retry_guidance" not in svc.state_dict["workflow_run"]

    @pytest.mark.asyncio
    async def test_two_failures_derives_guidance(self, svc):
        """失败 2 次派生：引导数据入账，run 进度零变更（模型未行动不推进）"""
        _quiet_gates(svc)
        _seed_run(svc, {"storyboard_shots": {"count": 2, "last_error": "429 限流"}})
        out = await po.gate_precheck(svc, _SKILL, "继续")
        assert out is not None and out.kind == "retry_guidance"
        assert "storyboard_shots" in out.message
        assert "换渠道" in out.message and "429 限流" in out.message
        # 引导数据双通道：flowEvents（模型可见）+ run.retry_guidance（结构化）
        fe = _guidance_events(svc)
        assert len(fe) == 1 and "storyboard_shots" in fe[0]["detail"]
        g = svc.state_dict["workflow_run"]["retry_guidance"]
        assert g["signature"] == "storyboard_shots:2"
        assert g["entries"] == [{"node": "storyboard_shots", "count": 2, "last_error": "429 限流"}]
        # ADR-0004：只产数据不推进——进度/版本/状态零变更
        run = svc.state_dict["workflow_run"]
        assert run["current_node"] == "storyboard_shots"
        assert run["completed_nodes"] == ["analyze_script"]
        assert run["run_version"] == 3 and run["status"] == "ready"

    @pytest.mark.asyncio
    async def test_same_signature_idempotent(self, svc):
        """同一账（签名未变）多轮只入账一次，引导持续在场"""
        _quiet_gates(svc)
        _seed_run(svc, {"script_analyze": {"count": 2, "last_error": "x"}})
        out1 = await po.gate_precheck(svc, _SKILL, "继续")
        out2 = await po.gate_precheck(svc, _SKILL, "继续")
        assert out1.kind == out2.kind == "retry_guidance"
        assert len(_guidance_events(svc)) == 1  # 不重复入账

    @pytest.mark.asyncio
    async def test_count_change_rebooks(self, svc):
        """计数变化（签名变）→ 重新入账新引导"""
        _quiet_gates(svc)
        _seed_run(svc, {"script_analyze": {"count": 2, "last_error": "x"}})
        await po.gate_precheck(svc, _SKILL, "继续")
        svc.state_dict["workflow_run"]["node_attempts"]["script_analyze"]["count"] = 3
        out = await po.gate_precheck(svc, _SKILL, "继续")
        assert out.kind == "retry_guidance"
        assert len(_guidance_events(svc)) == 2
        assert svc.state_dict["workflow_run"]["retry_guidance"]["signature"] == "script_analyze:3"

    @pytest.mark.asyncio
    async def test_threshold_config_respected(self, svc, set_global_setting):
        """阈值可配：调到 3 后失败 2 次不派生"""
        set_global_setting("node_retry_guidance_threshold", 3)
        _quiet_gates(svc)
        _seed_run(svc, {"storyboard_shots": {"count": 2, "last_error": "e"}})
        assert await po.gate_precheck(svc, _SKILL, "继续") is None

    @pytest.mark.asyncio
    async def test_success_clears_guidance_chain(self, svc):
        """成功清账后不再派生，且引导数据可被同步清除"""
        _quiet_gates(svc)
        _seed_run(svc, {"storyboard_shots": {"count": 2, "last_error": "e"}})
        await po.gate_precheck(svc, _SKILL, "继续")
        # 模拟执行器成功后的清账链（fc_tool_runner 成功分支同法）
        assert workflow_runtime.clear_node_attempt(svc.state_dict, "storyboard_shots")
        svc.state_dict["workflow_run"].pop("retry_guidance", None)
        svc.clear_flow_events("retry_guidance")
        assert await po.gate_precheck(svc, _SKILL, "继续") is None
        assert _guidance_events(svc) == []

    @pytest.mark.asyncio
    async def test_triage_hands_off_to_model_loop(self, svc):
        """planner_triage：retry_guidance 一律交接模型循环（不出暂停卡、
        不抢对话；重试动作由模型发起工具调用，ADR-0004）"""
        _quiet_gates(svc)
        _seed_run(svc, {"script_analyze": {"count": 2, "last_error": "x"}})
        called = []
        resp = await planner_triage.run_gate_precheck(
            svc, _SKILL, "继续",
            lambda **kw: called.append("factory"),
            lambda r: called.append("pause"))
        assert resp is None and called == []


# ---------- FC 轨接线：真实执行失败入账 / 成功清账 ----------

class TestFcRunnerWiring:
    @pytest.mark.asyncio
    async def test_executor_failure_books_attempt(self, svc):
        """执行器真实执行失败 → node_attempts 入账 1 次"""
        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.base import ToolResult

        _quiet_gates(svc)
        _seed_run(svc, {})

        class StubManager:
            async def invoke_tool(self, name, args):
                return ToolResult(success=False, error="供应商 429 限流")

        StateManager.reset_instance()
        StateManager._instance = svc
        try:
            runner = FCToolRunner(StubManager())
            resp = ChatResponse(
                content="", finish_reason="tool_calls",
                tool_calls=[{"id": "c1", "function": {
                    "name": "storyboard_shots",
                    "arguments": json.dumps({"skill_name": _SKILL})}}])
            await runner.execute(resp, injected_skill=_SKILL)
        finally:
            StateManager.reset_instance()

        attempts = (svc.state_dict.get("workflow_run") or {}).get("node_attempts") or {}
        entry = attempts.get("storyboard_shots") or {}
        assert entry.get("count") == 1
        assert "429" in str(entry.get("last_error") or "")

    @pytest.mark.asyncio
    async def test_executor_success_clears_attempt_and_guidance(self, svc):
        """执行器成功 → 清账 + 清引导标记与模型可见 flowEvents"""
        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.base import ToolResult

        _quiet_gates(svc)
        _seed_run(svc, {"storyboard_shots": {"count": 2, "last_error": "e"}})
        svc.state_dict["workflow_run"]["retry_guidance"] = {"signature": "storyboard_shots:2"}
        svc.record_flow_event("retry_guidance", "旧引导")

        class StubManager:
            async def invoke_tool(self, name, args):
                return ToolResult(success=True, data={"applied": 1})

        StateManager.reset_instance()
        StateManager._instance = svc
        try:
            runner = FCToolRunner(StubManager())
            resp = ChatResponse(
                content="", finish_reason="tool_calls",
                tool_calls=[{"id": "c1", "function": {
                    "name": "storyboard_shots",
                    "arguments": json.dumps({"skill_name": _SKILL})}}])
            await runner.execute(resp, injected_skill=_SKILL)
        finally:
            StateManager.reset_instance()

        run = svc.state_dict.get("workflow_run") or {}
        assert "storyboard_shots" not in (run.get("node_attempts") or {})
        assert "retry_guidance" not in run
        assert _guidance_events(svc) == []
