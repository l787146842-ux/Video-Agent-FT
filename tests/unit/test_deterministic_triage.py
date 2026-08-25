"""批 12 快路径降级钉死回归：抢先权退场，否决权/兜底卡保留。

正向设计（模型主动权 + 平台否决权）：
- 分诊/自动执行/步间收权三件删除（防复活锁源）；
- 轮始闸预检只装配原料闸/规格闸兜底卡，其余交接模型循环；
- 轮内暂停纪律：workflow_pause 后同批续执行被拒收；
- 顺序由 stage_precondition 闸否决越阶（既有，不在本文件重复钉）。
"""
import inspect

import pytest

from src.video_agent.core import stage_probes as po
from src.video_agent.core.planner import Planner
from src.video_agent.state.manager import StateManager

_SKILL = "AI-短剧一站式生成"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    yield instance
    StateManager.reset_instance()


# ---------- 防复活：抢先权符号禁止回到控制流 ----------

def test_preemption_symbols_deleted():
    """分诊/快路径驱动/步间收权符号禁止复活（批 12 已下账）"""
    assert not hasattr(Planner, "_triage_control")
    assert not hasattr(Planner, "_run_orchestrator_path")
    assert not hasattr(po, "run_deterministic_stage")
    assert not hasattr(po, "orchestrate_turn")
    assert not hasattr(po, "compose_pause_card")
    from src.video_agent.core import agent_loop, planner_triage
    assert "between_steps" not in inspect.signature(agent_loop.run_agent_loop).parameters
    assert not hasattr(planner_triage, "make_reclaim_hook")
    assert not hasattr(planner_triage, "triage_control")


def test_pause_window_gate_present():
    """轮内暂停纪律闸在场（workflow_pause 后同批续执行拒收）"""
    from src.video_agent.core import fc_tool_runner
    src = inspect.getsource(fc_tool_runner)
    assert "_PAUSE_WINDOW_READONLY" in src
    assert "paused_this_batch" in src


# ---------- 闸预检语义：只装配兜底卡，永不执行/抢先 ----------

@pytest.mark.asyncio
async def test_precheck_script_pending_when_material_missing(svc):
    """需剧本 Skill + 剧本缺失 → 原料闸提醒卡（兜底，非执行）"""
    out = await po.gate_precheck(svc, _SKILL, "开始制作")
    assert out is not None and out.kind == "script_pending"


@pytest.mark.asyncio
async def test_precheck_waive_intent_uses_raw_text(svc):
    """豁免意图（只认显式话术）→ 交接模型循环并留痕 script_waived"""
    out = await po.gate_precheck(svc, _SKILL, "waive_script")
    assert out is None
    assert (svc.state_dict.get("interaction") or {}).get("script_waived") is True


@pytest.mark.asyncio
async def test_precheck_upload_ack_card(svc):
    out = await po.gate_precheck(svc, _SKILL, "upload_script")
    assert out is not None and out.kind == "script_ack"


@pytest.mark.asyncio
async def test_precheck_spec_pending_after_analysis(svc):
    """分析完成 + 规格未定 → 规格向导卡（不执行、不抢先）"""
    svc.state_dict["uploadedDocs"] = [{"id": "d1", "name": "剧本.md", "content": "x"}]
    svc.state_dict["analysis"] = {"summary": "一句话"}
    out = await po.gate_precheck(svc, _SKILL, "继续")
    assert out is not None and out.kind == "spec_pending"


@pytest.mark.asyncio
async def test_precheck_handoff_when_no_gate_fires(svc):
    """无兜底卡触发 → None = 交接模型循环（模型持主动权）"""
    svc.state_dict["interaction"] = {"script_waived": True}
    svc.state_dict["analysis"] = {"summary": "一句话"}
    svc.state_dict["documents"] = [{
        "name": "Final_Video_Spec.md", "content": "规格", "confirmed": True,
    }]
    out = await po.gate_precheck(svc, _SKILL, "继续")
    assert out is None


# ---------- 轮内暂停纪律：workflow_pause 后同批拒续 ----------

@pytest.mark.asyncio
async def test_pause_window_rejects_same_batch_continuation(svc):
    """模型不暂停的越权形态被轮内否决：workflow_pause 后同批续执行拒收"""
    import json as _json

    from src.video_agent.adapters.base_chat import ChatResponse
    from src.video_agent.core.fc_tool_runner import FCToolRunner
    from src.video_agent.state.manager import StateManager
    from src.video_agent.tools.base import ToolResult

    invoked = []

    class StubManager:
        async def invoke_tool(self, name, args):
            invoked.append(name)
            return ToolResult(success=True, data={"paused": True, "message": "x"})

    StateManager.reset_instance()
    StateManager._instance = svc
    runner = FCToolRunner(StubManager())
    resp = ChatResponse(
        content="", finish_reason="tool_calls",
        tool_calls=[
            {"id": "c1", "function": {"name": "workflow_pause",
                                      "arguments": _json.dumps({"message": "请确认"})}},
            {"id": "c2", "function": {"name": "storyboard_key_elements",
                                      "arguments": _json.dumps({"skill_name": _SKILL})}},
        ])
    out = await runner.execute(resp, injected_skill=_SKILL)
    assert invoked == ["workflow_pause"], "暂停后同批续执行必须被拒收"
    tool_results = out[6]
    assert any(
        "请求用户确认" in str(t.get("error") or "") for t in tool_results
    ), tool_results
    StateManager.reset_instance()
