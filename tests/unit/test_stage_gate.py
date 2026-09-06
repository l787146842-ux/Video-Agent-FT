# -*- coding: utf-8 -*-
"""轮末阶段闸测试（2026-09-06 Flova 对齐批）：执行模式确认档
（key_steps_confirm/pause_all）下里程碑翻转完成 → 平台机械签发暂停卡
（档位 > Skill 散文）；默认档/自动执行全流程不签发（行为与现状一致）。

判据口径：轮始 workflow_run0.current_node 翻转进 completed_nodes（客观探针，
账本无自报）；pause 卡 = confirmation/options + workflow_run.pending_decision
（token 前缀 review:，chat_consume.resolve_decision 消费落 DecisionResolved）。
"""
import pytest

from src.video_agent.config import settings
from src.video_agent.core.planner import Planner, PlannerContext, PlannerResponse
from src.video_agent.core.workflow_runtime import WorkflowRuntime
from src.video_agent.state.manager import StateManager

SKILL = "宣言式概念短片"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _set_mode(mode):
    old = settings.execution_mode
    object.__setattr__(settings, "execution_mode", mode)
    return old


@pytest.fixture
def restore_mode():
    old = settings.execution_mode
    yield
    object.__setattr__(settings, "execution_mode", old)


def _run_at_first_stage(svc) -> dict:
    """预建 run（无任何产物）→ current = analyze_script。"""
    rt = WorkflowRuntime(svc, SKILL)
    return rt.ensure_run()


def _mk_ctx(svc, run0: dict) -> PlannerContext:
    return PlannerContext(skill_name=SKILL, workflow_run0=dict(run0 or {}))


def test_default_mode_no_gate_but_ledger_syncs(svc, restore_mode):
    """ai_decide 默认档：阶段翻转不签发暂停卡（行为与现状一致），
    但轮末账本同步仍执行（completed_nodes 恢复推进）。"""
    assert _set_mode("ai_decide") is not None
    run0 = _run_at_first_stage(svc)
    svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}
    planner = Planner(state_manager=svc, llm_adapter=None)
    resp = PlannerResponse()
    planner._apply_stage_gate(resp, _mk_ctx(svc, run0))
    assert resp.confirmation == "" and resp.pause_kind == ""
    run = svc.state_dict.get("workflow_run") or {}
    assert "analyze_script" in (run.get("completed_nodes") or []), "账本轮末同步应推进"


def test_auto_full_mode_no_gate(svc, restore_mode):
    """auto_full：不签发阶段闸卡（直通）。"""
    _set_mode("auto_full")
    run0 = _run_at_first_stage(svc)
    svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}
    planner = Planner(state_manager=svc, llm_adapter=None)
    resp = PlannerResponse()
    planner._apply_stage_gate(resp, _mk_ctx(svc, run0))
    assert resp.confirmation == "" and resp.pause_kind == ""


def test_key_steps_gate_fires_at_spec_milestone(svc, restore_mode):
    """key_steps_confirm：规格翻转 → 新当前节点 review_spec（审批节点）
    → 机械签发卡 + review: 挂起决议。"""
    _set_mode("key_steps_confirm")
    svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}
    run0 = _run_at_first_stage(svc)
    assert run0.get("current_node") == "collect_spec"
    # 本轮写入规格文档 → spec 探针翻转，current 推进到 review_spec
    svc.state_dict["documents"] = [{
        "name": "制片规格.md", "content": "时长：60 秒\n画幅：21:9",
    }]
    planner = Planner(state_manager=svc, llm_adapter=None)
    resp = PlannerResponse()
    planner._apply_stage_gate(resp, _mk_ctx(svc, run0))
    assert "规格审核" in resp.confirmation, "审批节点应机械签发暂停卡"
    assert resp.pause_kind == "stage_done"
    labels = [o.get("label") for o in resp.confirmation_options or []]
    assert "确认，继续推进" in labels and "提出调整" in labels
    run = svc.state_dict.get("workflow_run") or {}
    pend = run.get("pending_decision") or {}
    assert pend.get("token", "").startswith("review:")
    assert pend.get("node_id") == "review_spec"
    assert run.get("status") == "waiting_user"


def test_key_steps_gate_skips_non_approval_node(svc, restore_mode):
    """key_steps_confirm：翻转后新当前节点非审批节点（如 collect_spec）
    → 不签发（里程碑口径）。"""
    _set_mode("key_steps_confirm")
    run0 = _run_at_first_stage(svc)  # current = analyze_script
    svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}
    planner = Planner(state_manager=svc, llm_adapter=None)
    resp = PlannerResponse()
    planner._apply_stage_gate(resp, _mk_ctx(svc, run0))
    # 翻转后 current = collect_spec（spec 未落盘，非审批节点）
    run = svc.state_dict.get("workflow_run") or {}
    assert run.get("current_node") == "collect_spec"
    assert resp.confirmation == ""


def test_pause_all_gate_fires_at_any_stage(svc, restore_mode):
    """pause_all：任意阶段翻转即停（每阶段审阅）。"""
    _set_mode("pause_all")
    run0 = _run_at_first_stage(svc)
    svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}
    planner = Planner(state_manager=svc, llm_adapter=None)
    resp = PlannerResponse()
    planner._apply_stage_gate(resp, _mk_ctx(svc, run0))
    assert resp.confirmation != "", "pause_all 任意节点翻转都签发"
    assert (svc.state_dict.get("workflow_run") or {}).get("pending_decision")


def test_gate_skips_when_no_stage_flip(svc, restore_mode):
    """本轮无阶段翻转（纯对话轮）→ 不签发（账本仍同步）。"""
    _set_mode("key_steps_confirm")
    run0 = _run_at_first_stage(svc)
    planner = Planner(state_manager=svc, llm_adapter=None)
    resp = PlannerResponse()
    planner._apply_stage_gate(resp, _mk_ctx(svc, run0))
    assert resp.confirmation == ""


def test_gate_skips_when_pause_slot_occupied(svc, restore_mode):
    """模型已自发暂停（response.confirmation 在场 / 暂停槽被占）→ 不重复发行。"""
    _set_mode("key_steps_confirm")
    svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}
    run0 = _run_at_first_stage(svc)
    run0["current_node"] = "collect_spec"
    svc.state_dict["documents"] = [{
        "name": "制片规格.md", "content": "时长：60 秒",
    }]
    planner = Planner(state_manager=svc, llm_adapter=None)
    # 槽位被占
    svc.state_dict["interaction"] = {"active_pause": {"pause_id": "p1"}, "awaiting_confirmation": True}
    resp = PlannerResponse()
    planner._apply_stage_gate(resp, _mk_ctx(svc, run0))
    assert resp.confirmation == ""
    # 响应已带模型确认
    svc.state_dict["interaction"] = {}
    resp2 = PlannerResponse(confirmation="模型自发暂停")
    planner._apply_stage_gate(resp2, _mk_ctx(svc, run0))
    assert resp2.pause_kind == "" and not resp2.confirmation_options


def test_resolved_decision_completes_review_node(svc, restore_mode):
    """批复闭环：review: 决议经 resolve_decision 落 DecisionResolved →
    审批节点完成入账、挂起清空、run 恢复就绪。"""
    _set_mode("key_steps_confirm")
    svc.state_dict["analysis"] = {"summary": "三体水滴", "report": "报告"}
    run0 = _run_at_first_stage(svc)
    run0["current_node"] = "collect_spec"
    svc.state_dict["documents"] = [{
        "name": "制片规格.md", "content": "时长：60 秒",
    }]
    planner = Planner(state_manager=svc, llm_adapter=None)
    resp = PlannerResponse()
    planner._apply_stage_gate(resp, _mk_ctx(svc, run0))
    pend = (svc.state_dict.get("workflow_run") or {}).get("pending_decision") or {}
    assert pend.get("token", "").startswith("review:")
    rt = WorkflowRuntime(svc, SKILL)
    rt.resolve_decision(str(pend["token"]), "confirm")
    run = svc.state_dict.get("workflow_run") or {}
    assert "review_spec" in (run.get("completed_nodes") or []), "决议落账后审批节点完成"
    assert run.get("pending_decision") is None
    assert run.get("status") == "ready"
