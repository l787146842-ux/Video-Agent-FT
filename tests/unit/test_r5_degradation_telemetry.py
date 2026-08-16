"""四轮 R5 回归（#11）：核心探测点意外降级遥测——接线断裂从静默 False 变为可观测计数。"""
import pytest

from src.video_agent.core import live_metrics
from src.video_agent.core.round_end_policies import RoundEndContext, RoundEndPolicy, run_round_end_policies
import asyncio


@pytest.fixture(autouse=True)
def _clean():
    live_metrics.reset_degradations()
    yield
    live_metrics.reset_degradations()


def test_r5_record_degradation_counts():
    live_metrics.record_degradation("agent_loop._wizard_active")
    live_metrics.record_degradation("agent_loop._wizard_active")
    live_metrics.record_degradation("planner.flow_gates_parse", project_id="p1")
    rows = live_metrics.get_degradations()
    by_point = {(r["point"], r["project_id"]): r for r in rows}
    assert by_point[("agent_loop._wizard_active", "")]["count"] == 2
    assert by_point[("planner.flow_gates_parse", "p1")]["count"] == 1


def test_r5_policy_condition_failure_records_degradation():
    """策略条件求值抛异常 → 跳过该策略 + 遥测计数（防闸机接线静默断裂）。"""

    def boom(ctx):
        raise RuntimeError("模拟接线断裂")

    applied = []

    async def ok_apply(ctx, emit):
        applied.append(True)

    policies = [
        RoundEndPolicy("broken_policy", "arbitrable", 10, boom, ok_apply),
        RoundEndPolicy("healthy_policy", "arbitrable", 20, lambda c: True, ok_apply),
    ]
    ctx = RoundEndContext(step=1)

    async def emit(event):
        pass

    asyncio.run(run_round_end_policies(ctx, emit, policies=policies))
    # 坏策略跳过、好策略照常执行
    assert applied == [True]
    rows = live_metrics.get_degradations()
    assert any(r["point"] == "round_end.broken_policy" for r in rows)


def test_r5_core_probe_points_instrumented():
    """G4 防漂移：6 个核心探测点的降级遥测埋点在源码中持续存在
    （_wizard_active 是 run_agent_loop 内闭包，无法轻量单测，以源码断言钉死）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    al_src = (root / "src/video_agent/core/agent_loop.py").read_text(encoding="utf-8")
    planner_src = (root / "src/video_agent/core/planner.py").read_text(encoding="utf-8")
    rep_src = (root / "src/video_agent/core/round_end_policies.py").read_text(encoding="utf-8")
    assert 'record_degradation("agent_loop._wizard_active")' in al_src
    assert 'record_degradation("planner.spec_gate_assembly")' in planner_src
    assert 'record_degradation("planner.flow_gates_parse")' in planner_src
    assert 'record_degradation("planner.script_gate_assembly")' in planner_src
    assert "record_degradation(f\"round_end.{policy.policy_id}\")" in rep_src
    assert 'record_degradation("round_end.stage_pause_declared")' in rep_src
    # 调试端点暴露（routes/agent.py）
    routes_src = (root / "src/video_agent/web/routes/agent.py").read_text(encoding="utf-8")
    assert "/agent/degradations" in routes_src and "get_degradations()" in routes_src
