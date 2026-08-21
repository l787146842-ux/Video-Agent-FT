# -*- coding: utf-8 -*-
"""批4（审核整改）：Workflow Runtime 泛化不变量。

钉死：
① drive_turn 去硬编码：直跑面 = sidecar 声明 flow.direct_run_nodes，
   缺失回落 analyze_script（存量行为不变）；
② 审批直跑能力：声明审批节点入名单 → approval_pause directive；
   默认名单不含审批节点（防与模型循环暂停语义重复）；
③ compile_definition per-turn 缓存：同轮共享、clear_compile_cache 恢复；
④ record_artifact 正名：无伪轮次，run.artifacts 幂等 + ArtifactCommitted
   事件独立入账（turn_id=artifact:* 从 workflow_turns 绝迹）。
"""
import pytest

from src.video_agent.core import workflow_runtime as wr
from src.video_agent.skill_runtime import registry


SKILL = "AI-短剧一站式生成"


@pytest.fixture(autouse=True)
def _clean_cache():
    wr.clear_compile_cache()
    yield
    wr.clear_compile_cache()


def _state_with_run(current_node: str = "analyze_script") -> dict:
    return {"workflow_run": {"run_id": "run_b4", "current_node": current_node,
                             "completed_nodes": [], "run_version": 0,
                             "event_sequence": 0}}


# ---------- ① 直跑面声明驱动（去硬编码） ----------

def test_direct_run_defaults_to_analyze_when_undeclared(monkeypatch):
    monkeypatch.setattr(registry, "skill_manifest_of", lambda s: {"flow": {}})
    nodes = wr.direct_run_nodes(SKILL)
    assert nodes == frozenset({"analyze_script"})


def test_direct_run_nodes_honors_sidecar_declaration(monkeypatch):
    monkeypatch.setattr(
        registry, "skill_manifest_of",
        lambda s: {"flow": {"direct_run_nodes": ["analyze_script", "review_key_elements"]}})
    nodes = wr.direct_run_nodes(SKILL)
    assert nodes == frozenset({"analyze_script", "review_key_elements"})


def test_drive_turn_direct_run_by_declaration(monkeypatch):
    """声明内节点 + 执行器就绪 → direct_run；stage_key 按节点映射。"""
    monkeypatch.setattr(registry, "skill_manifest_of", lambda s: {"flow": {}})
    monkeypatch.setattr(registry, "script_required_active", lambda s: False)
    state = _state_with_run("analyze_script")
    directive = wr.drive_turn(state, SKILL, advance_signal="pause")
    assert directive is not None
    assert directive["kind"] == "direct_run"
    assert directive["node_id"] == "analyze_script"
    assert directive["stage_key"] == "analysis"
    assert directive["executors"]


def test_drive_turn_no_signal_no_direct_run(monkeypatch):
    """无客观推进信号的自由提问轮：交接模型循环（防提问误抓）。"""
    monkeypatch.setattr(registry, "skill_manifest_of", lambda s: {"flow": {}})
    assert wr.drive_turn(_state_with_run(), SKILL, advance_signal="") is None


# ---------- ② 审批直跑能力（预留，默认不启用） ----------

def test_approval_node_direct_run_only_when_declared(monkeypatch):
    """审批节点入声明 → approval_pause；不入声明 → None（默认防双暂停）。"""
    monkeypatch.setattr(registry, "skill_manifest_of", lambda s: {"flow": {}})
    state = _state_with_run("review_key_elements")
    assert wr.drive_turn(state, SKILL, advance_signal="pause") is None

    monkeypatch.setattr(
        registry, "skill_manifest_of",
        lambda s: {"flow": {"direct_run_nodes": ["review_key_elements"]}})
    state = _state_with_run("review_key_elements")
    directive = wr.drive_turn(state, SKILL, advance_signal="pause")
    assert directive is not None
    assert directive["kind"] == "approval_pause"
    assert directive["node_id"] == "review_key_elements"


# ---------- ③ per-turn 编译缓存 ----------

def test_compile_cache_shared_within_turn(monkeypatch):
    calls = {"n": 0}
    real_resolve = registry.resolve_entry

    def counting_resolve(name):
        calls["n"] += 1
        return real_resolve(name)

    monkeypatch.setattr(registry, "resolve_entry", counting_resolve)
    first = wr.compile_definition(SKILL)
    second = wr.compile_definition(SKILL)
    assert first is not None and calls["n"] == 1
    assert first["definition_hash"] == second["definition_hash"]
    wr.clear_compile_cache()
    wr.compile_definition(SKILL)
    assert calls["n"] == 2


# ---------- ④ record_artifact 正名 ----------

def test_record_artifact_idempotent_and_no_pseudo_turn():
    state = _state_with_run("write_spec")
    wr.record_artifact(state, SKILL, "Final_Video_Spec.md")
    wr.record_artifact(state, SKILL, "Final_Video_Spec.md")  # 幂等
    run = state["workflow_run"]
    assert run["artifacts"] == ["Final_Video_Spec.md"]
    # 伪轮次退役：不再产生 turn_id=artifact:* 的提交记录
    assert state.get("workflow_turns", []) == []
    # 全局产物账本同口径幂等
    assert [a["name"] for a in state["workflow_artifacts"]] == ["Final_Video_Spec.md"]
    # ArtifactCommitted 独立事件入账（幂等键去重）
    events = [e for e in wr.EventLedger(state).events
              if e.event_type == "ArtifactCommitted"]
    assert len(events) == 1
    assert events[0].payload.get("name") == "Final_Video_Spec.md"


def test_record_artifact_without_run_is_noop():
    state: dict = {}
    wr.record_artifact(state, SKILL, "X.md")
    assert "workflow_artifacts" not in state
