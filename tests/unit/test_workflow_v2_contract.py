# -*- coding: utf-8 -*-
"""Workflow Runtime v2 契约不变量（重构计划批0：schema + reducer 不变量测试）。

钉死（ADR-0003 v2，Codex 重构计划§一/§二/§三）：
① WorkflowDefinition：字段缺失/重复 node_id/悬空依赖/循环依赖 → 注册期拒绝；
② EventLedger：run 内 sequence 单调、幂等键重放返回同事件、载荷冲突报
   EventIdempotencyConflict；
③ commit_turn：同 turn_id 重放幂等（不重复写文档/事件）、run_version 并发
   校验、artifact 文档同事务落 documents+run.artifacts+ArtifactCommitted、
   decision_request → pending_decision+waiting_user、next_transition 推进
   completed_nodes/current_node/StageSucceeded、中途异常状态回滚；
④ WorkflowRuntime：缺原料 start_run → waiting_user+InputRequested；
   resolve_decision 旧 token 拒绝；recover_run 恢复 sequence/status；
⑤ registry.sync_all 单文件非法不截断批次（Codex 中断1 修复钉死）。
"""
import pytest

from src.video_agent.core.workflow_contract import (
    WorkflowDefinition,
    WorkflowDefinitionError,
    default_v2_workflow,
)
from src.video_agent.core.workflow_events import (
    EventIdempotencyConflict,
    EventLedger,
)
from src.video_agent.core.turn_commit import (
    TurnResult,
    WorkflowConcurrencyError,
    commit_turn,
)
from src.video_agent.core.workflow_runtime import WorkflowRuntime


def _node(nid, deps=(), **kw):
    base = {"node_id": nid, "executor": "x", "deterministic": True,
            "prerequisites": list(deps), "done_predicate": {"type": "state"},
            "artifact_schema": {}, "decision_schema": {},
            "approval_policy": {}, "retry_policy": {}, "next_transition": {}}
    base.update(kw)
    return base


def _sidecar(nodes):
    return {"workflow": {"workflow_id": "wf", "revision": "1", "nodes": nodes}}


# ---------- ① WorkflowDefinition ----------

def test_definition_requires_all_node_fields():
    with pytest.raises(WorkflowDefinitionError):
        WorkflowDefinition.from_sidecar(_sidecar([{"node_id": "a"}]))


def test_definition_rejects_duplicate_node_id():
    with pytest.raises(WorkflowDefinitionError):
        WorkflowDefinition.from_sidecar(_sidecar([_node("a"), _node("a")]))


def test_definition_rejects_unknown_prerequisite():
    with pytest.raises(WorkflowDefinitionError):
        WorkflowDefinition.from_sidecar(_sidecar([_node("a", ("ghost",))]))


def test_definition_rejects_cycle():
    with pytest.raises(WorkflowDefinitionError):
        WorkflowDefinition.from_sidecar(
            _sidecar([_node("a", ("b",)), _node("b", ("a",))]))


def test_definition_hash_stable_and_revision_kept():
    d1 = WorkflowDefinition.from_sidecar(_sidecar([_node("a")]))
    d2 = WorkflowDefinition.from_sidecar(_sidecar([_node("a")]))
    assert d1.content_hash == d2.content_hash
    d3 = default_v2_workflow("skill-x")
    assert d3.revision == "2" and len(d3.nodes) == 8


# ---------- ② EventLedger ----------

def test_ledger_sequence_monotonic_per_run():
    st = {}
    ledger = EventLedger(st)
    e1 = ledger.append("RunStarted", run_id="r1", idempotency_key="k1")
    e2 = ledger.append("StageStarted", run_id="r1", idempotency_key="k2")
    e3 = ledger.append("RunStarted", run_id="r2", idempotency_key="k3")
    assert (e1.sequence, e2.sequence) == (1, 2)
    assert e3.sequence == 1  # 跨 run 独立计数


def test_ledger_idempotent_replay_same_payload():
    st = {}
    ledger = EventLedger(st)
    e1 = ledger.append("ToolSucceeded", run_id="r1", idempotency_key="k",
                       payload={"a": 1})
    e2 = ledger.append("ToolSucceeded", run_id="r1", idempotency_key="k",
                       payload={"a": 1})
    assert e1.event_id == e2.event_id
    assert len(st["workflow_events"]) == 1


def test_ledger_idempotency_conflict_on_payload_diff():
    st = {}
    ledger = EventLedger(st)
    ledger.append("ToolSucceeded", run_id="r1", idempotency_key="k",
                  payload={"a": 1})
    with pytest.raises(EventIdempotencyConflict):
        ledger.append("ToolSucceeded", run_id="r1", idempotency_key="k",
                      payload={"a": 2})


# ---------- ③ commit_turn ----------

def test_commit_turn_idempotent_replay():
    st = {}
    c1 = commit_turn(st, TurnResult(turn_id="t1", body="hi",
                                    artifacts=[{"name": "a.md", "kind": "document",
                                                "content": "x"}]), persist=False)
    docs = len(st["documents"])
    events = len(st["workflow_events"])
    c2 = commit_turn(st, TurnResult(turn_id="t1", body="hi",
                                    artifacts=[{"name": "a.md", "kind": "document",
                                                "content": "x"}]), persist=False)
    assert c2.idempotent is True
    assert len(st["documents"]) == docs
    assert len(st["workflow_events"]) == events
    assert c1.run["run_version"] == c2.run["run_version"]


def test_commit_turn_version_concurrency():
    st = {}
    commit_turn(st, TurnResult(turn_id="t1", body="a"), persist=False)
    with pytest.raises(WorkflowConcurrencyError):
        commit_turn(st, TurnResult(turn_id="t2", body="b", run_version=0),
                    persist=False)


def test_commit_turn_artifact_and_transition():
    st = {}
    c = commit_turn(st, TurnResult(
        turn_id="t1", body="分析完成",
        artifacts=[{"name": "analysis.json", "kind": "artifact"}],
        next_transition={"completed_node": "analyze_script",
                         "next_node": "collect_spec"}), persist=False)
    run = st["workflow_run"]
    assert "analyze_script" in run["completed_nodes"]
    assert run["current_node"] == "collect_spec"
    assert "analysis.json" in run["artifacts"]
    types = [e.event_type for e in c.events]
    assert "ArtifactCommitted" in types and "StageSucceeded" in types \
        and types[-1] == "TurnCommitted"


def test_commit_turn_decision_opens_waiting_user():
    st = {}
    c = commit_turn(st, TurnResult(
        turn_id="t1", body="请确认",
        decision_request={"token": "tok1", "prompt": "确认？",
                          "options": [{"value": "yes"}, {"value": "no"}]}),
        persist=False)
    assert st["workflow_run"]["status"] == "waiting_user"
    assert st["workflow_run"]["pending_decision"]["token"] == "tok1"
    assert any(e.event_type == "DecisionOpened" for e in c.events)


def test_commit_turn_rolls_back_on_conflict_inside():
    st = {}
    # 预置同幂等键不同载荷：commit 内部 ledger append 将冲突 → 状态回滚
    EventLedger(st).append("ToolSucceeded", run_id="run_x",
                           idempotency_key="t9:timeline:0", payload={"x": 1})
    st["workflow_run"] = {"run_id": "run_x"}
    with pytest.raises(EventIdempotencyConflict):
        commit_turn(st, TurnResult(turn_id="t9", body="boom",
                                   timeline_events=[{"event_type": "ToolSucceeded",
                                                     "payload": {"x": 2}}]),
                    persist=False)
    # 回滚钉死：冲突事件的载荷未写入、turn 未登记
    assert len(st["workflow_events"]) == 1
    assert not any(isinstance(t, dict) and t.get("turn_id") == "t9"
                   for t in st.get("workflow_turns") or [])


# ---------- ④ WorkflowRuntime ----------

def test_runtime_start_run_waiting_user_without_input():
    st = {"usedSkills": ["AI-短剧一站式生成"]}
    rt = WorkflowRuntime(st, "AI-短剧一站式生成")
    run = rt.start_run(input_present=False)
    assert run["status"] == "waiting_user"
    assert run["pending_decision"]
    ledger = EventLedger(st)
    types = [e.event_type for e in ledger.by_run(run["run_id"])]
    assert "RunStarted" in types and "InputRequested" in types


def test_runtime_resolve_decision_rejects_stale_token():
    st = {}
    rt = WorkflowRuntime(st, "AI-短剧一站式生成")
    run = rt.start_run(input_present=False)
    from src.video_agent.core.turn_commit import WorkflowCommitError
    with pytest.raises(WorkflowCommitError):
        rt.resolve_decision("wrong-token", "yes")


def test_runtime_recover_run_restores_sequence_and_status():
    st = {}
    rt = WorkflowRuntime(st, "AI-短剧一站式生成")
    run = rt.start_run(input_present=False)
    seq = run["event_sequence"]
    st["workflow_run"]["event_sequence"] = 0  # 模拟旧视图
    rec = rt.recover_run()
    assert rec["event_sequence"] == seq
    assert rec["status"] == "waiting_user"


# ---------- ⑤ 注册隔离 ----------

def test_sync_run_backfills_legacy_run_without_clearing():
    """重构计划批4：在途旧 run 一次性导入——新字段补齐，
    artifacts/completed_nodes 不清空（禁止 clear 式回滚）。"""
    from src.video_agent.core import workflow_runtime

    st = {"workflow_run": {"run_id": "run_old", "current_node": "analyze_script",
                           "completed_nodes": ["analyze_script"],
                           "artifacts": ["a.md"]},
          "usedSkills": ["AI-短剧一站式生成"]}
    run = workflow_runtime.sync_run(st, "AI-短剧一站式生成")
    assert run["artifacts"] == ["a.md"]
    for key in ("run_version", "event_sequence", "status", "node_attempts"):
        assert key in run, f"旧 run 缺字段补齐: {key}"


def test_sync_all_skips_invalid_file_without_aborting_batch(tmp_path, monkeypatch):
    from src.video_agent.web import skill_docs as sd
    from src.video_agent.skill_runtime import registry

    d = tmp_path / "skills"
    d.mkdir()
    (d / "good.md").write_text("# 好技能\n> 调用规则：测试\n正文", encoding="utf-8")
    # 非法标识（含空格/特殊字符的 slug 由文件名带入）→ _load_entry 校验失败
    (d / "bad slug!.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    try:
        registry.sync_all(force=True)
        assert registry.resolve_entry("good") is not None
    finally:
        registry.reset_registry()
