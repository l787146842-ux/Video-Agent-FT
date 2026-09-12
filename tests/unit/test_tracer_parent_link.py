# -*- coding: utf-8 -*-
"""批①D 回归：子代理与父同 context 内联跑时，父轮 trace 必须完整落盘（D2/D1），
且子 trace 携 parent_trace_id 血缘（D3）。

钉死 6666 复盘的断链 bug：run_subagent 在父轮同一 asyncio task 内 await，
子的 start_trace/finish_trace 若覆盖父绑定 → 主轮 trace 永不落盘（审计断链）。
"""
from src.video_agent.core.tracer import AgentTracer


def _fresh(tmp_path):
    AgentTracer.reset()
    tracer = AgentTracer.get_instance()
    # 落盘重定向到临时目录：不污染生产 data/agent_traces.jsonl
    tracer._persist_path = tmp_path / "agent_traces.jsonl"
    return tracer


def test_nested_child_restores_parent_frame_and_lineage(tmp_path):
    """子 finish 后父 current 仍在 → 父 finish 正常落盘；子记父 trace_id。"""
    tracer = _fresh(tmp_path)
    ptid = tracer.start_trace("parent")
    tracer.start_step()
    tracer.record_action("model_reasoning", ok=True)

    # 模拟 _launch_subagent：子在同一 context 内联跑完
    with tracer.child_trace_scope():
        tracer.start_trace("child")
        tracer.start_step()
        tracer.record_action("storyboard_create_group", ok=True)
        child_rec = tracer.finish_trace(total_actions=1)

    # D3：子 trace 记住委派它的父 trace_id
    assert child_rec["parent_trace_id"] == ptid, "子 trace 未落 parent_trace_id"

    # D2/D1：子结束后父绑定完好，父轮 step 与落盘不受影响
    tracer.end_step(1, actions_applied=1, finish_reason="fc_done")
    parent_rec = tracer.finish_trace(total_actions=1)
    assert parent_rec.get("trace_id") == ptid, "父轮 trace 被子代理冲掉、未落盘"
    assert parent_rec["steps"], "父轮 step 丢失"
    names = [a["name"] for s in parent_rec["steps"] for a in s["actions"]]
    assert names == ["model_reasoning"], f"父轮时间线被子代理动作污染: {names}"
    # 顶层轮不应有 parent_trace_id
    assert not parent_rec.get("parent_trace_id"), "顶层轮不应带 parent_trace_id"


def test_finish_without_parent_frame_clears_current(tmp_path):
    """顶层顺序轮次（父态 current 已 None）：不回退，行为等价旧语义。"""
    tracer = _fresh(tmp_path)
    t1 = tracer.start_trace("turn1")
    tracer.start_step()
    tracer.end_step(1, actions_applied=0, finish_reason="stop")
    assert tracer.finish_trace(total_actions=0)["trace_id"] == t1

    # 第二轮：inherited.current 已 None ⇒ 不挂父帧、不落 parent_trace_id
    t2 = tracer.start_trace("turn2")
    tracer.start_step()
    tracer.end_step(1, actions_applied=0, finish_reason="stop")
    rec2 = tracer.finish_trace(total_actions=0)
    assert rec2["trace_id"] == t2
    assert not rec2.get("parent_trace_id"), "顺序顶层轮不应被误判为子代理"
