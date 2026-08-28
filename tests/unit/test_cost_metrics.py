"""B10 回归：成本看板聚合（fallback 计数 + 闸机拦截率）。"""
from src.video_agent.core.tracer import AgentTracer


def test_b10_metrics_aggregates_fallback_and_gates():
    tracer = AgentTracer.get_instance()
    tracer.start_trace("成本看板测试", user_id="test")
    tracer.start_step()
    tracer.record_gate("platform.gen_confirm", "platform", False, message="未确认")
    tracer.record_gate("skill.flow.spec_gate", "skill", True)
    tracer.record_action("image_generate", "生成设定图", 100.0, True)
    tracer.end_step(1, actions_applied=1, finish_reason="stop")
    tracer.finish_trace(total_actions=1)
    tracer.record_fallback("provB", "m1")

    m = tracer.metrics()
    assert m["fallback_count"] >= 1
    assert m["gate_total"] >= 2
    assert m["gate_intercepts"] >= 1
    assert m["gate_intercept_rate"] > 0
    assert m["traces_count"] >= 1
