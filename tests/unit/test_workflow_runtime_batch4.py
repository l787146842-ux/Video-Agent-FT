# -*- coding: utf-8 -*-
"""Workflow Runtime 不变量（主体回归后；决策史见 git tag adr-archive-20260901）。

钉死：
① 直跑机制退役守卫：runtime 无自主行动符号（防复活，
   同 scripts/check_legacy_orchestration 门禁双保险）；
② DAG 编译退役（2026-09-10 阶段规则去代码化批）：compile_definition 恒 None，
   账本改按平铺节点清单跑客观探针；sync_run 仍保留 run 同步职能；
③ record_artifact 正名：无伪轮次，run.artifacts 幂等 + ArtifactCommitted
   事件独立入账（turn_id=artifact:* 从 workflow_turns 绝迹）。
"""
import pytest

from src.video_agent.core import workflow_runtime as wr
from src.video_agent.skill_runtime import registry


SKILL = "AI-短剧一站式生成"

# 退役符号名单（拼接构造，防本文件自身命中防复活门禁正则）
_RETIRED_WR = ("drive_" + "turn", "direct_run_" + "nodes")
_RETIRED_PLANNER = ("_run_direct_" + "stage", "_run_approval_" + "pause")


@pytest.fixture(autouse=True)
def _clean_cache():
    wr.clear_compile_cache()
    yield
    wr.clear_compile_cache()


def _state_with_run(current_node: str = "analyze_script") -> dict:
    return {"workflow_run": {"run_id": "run_b4", "current_node": current_node,
                             "completed_nodes": [], "run_version": 0,
                             "event_sequence": 0}}


# ---------- ① 直跑机制退役守卫（主体回归） ----------

def test_direct_run_mechanism_retired():
    """主体回归：runtime 无自主行动能力——直跑驱动符号零残留。"""
    import src.video_agent.core.planner as planner_mod
    for name in _RETIRED_WR:
        assert not hasattr(wr, name), f"workflow_runtime 残留 {name}"
    for name in _RETIRED_PLANNER:
        assert not hasattr(planner_mod.Planner, name), f"Planner 残留 {name}"
    assert not hasattr(wr.WorkflowRuntime, "dispatch"), "WorkflowRuntime 残留 dispatch"
    assert "drive_" + "turn" not in wr.__all__


def test_runtime_still_ledger_and_referee_data():
    """账本 + 裁判数据层职能保留：run 同步 / 客观探针重算 / 产物账本可用。
    （DAG 编译退役：compile_definition 恒 None，不再是判据。）"""
    assert wr.compile_definition(SKILL) is None, "DAG 编译已退役"
    state = _state_with_run()
    run = wr.sync_run(state, SKILL)
    assert run.get("run_id"), "sync_run 保留 run 同步职能"
    assert "completed_nodes" in run and "current_node" in run


# ---------- ② DAG 编译退役（原 per-turn 编译缓存随机制一并退役） ----------

def test_compile_definition_always_none(monkeypatch):
    """DAG 编译退役钉死：任何 Skill 都不再编译定义（恒 None），
    也不再触碰 registry 解析（零副作用）。"""
    calls = {"n": 0}
    real_resolve = registry.resolve_entry

    def counting_resolve(name):
        calls["n"] += 1
        return real_resolve(name)

    monkeypatch.setattr(registry, "resolve_entry", counting_resolve)
    assert wr.compile_definition(SKILL) is None
    assert wr.compile_definition("不存在的 Skill") is None
    assert calls["n"] == 0, "退役的编译路径不得再解析 Skill 注册表"


# ---------- ③ record_artifact 正名 ----------

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
