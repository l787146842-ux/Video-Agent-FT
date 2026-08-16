"""四轮 R2 回归：双轨 flow gate 判定收敛（guard_pipeline.evaluate_flow_gate 唯一实现）。

钉死：
1. 同一越阶操作分别走文本轨分类（classify_action）与 FC 轨分类（classify_fc），
   evaluate_flow_gate 返回的 verdict 逐字段一致（语义单一来源）；
2. 放行场景双轨一致返回 None；
3. 拦截 verdict 入审计（rule_id=skill.flow.checkpoint）；
4. 消费点唯一性（G4）：agent_loop / fc_tool_runner 源码均经 evaluate_flow_gate，
   不再各自内联 check_op+block_reason 组装判定。
"""
import re
from pathlib import Path

from src.video_agent.core import guard_pipeline
from src.video_agent.core.flow_gates import FlowGateSet
from src.video_agent.core.tracer import AgentTracer

ROOT = Path(__file__).resolve().parents[2]


def _spec_gate_set() -> FlowGateSet:
    """规格前置门禁（814G5 执行侧强制同款）：规格未定稿拦结构操作。"""
    return FlowGateSet.ensure_spec_gate(None)


def test_r2_dual_track_flow_gate_verdict_identical():
    """同一越阶结构操作：文本轨与 FC 轨 verdict 逐字段一致。"""
    gates = _spec_gate_set()
    state = {"documents": []}  # 无规格文档 → 应拦截

    # 文本轨：studio-actions 动作分类
    text_op = gates.classify_action({"action": "storyboard_shots"})
    # FC 轨：工具调用分类
    fc_op = gates.classify_fc("storyboard_shots", {})
    assert text_op == fc_op, "两轨操作分类必须同值（判定前提一致）"

    v_text = guard_pipeline.evaluate_flow_gate(
        gates, text_op, state, action_name="storyboard_shots", skill_name="测试Skill",
    )
    v_fc = guard_pipeline.evaluate_flow_gate(
        gates, fc_op, state, action_name="storyboard_shots", skill_name="测试Skill",
    )
    assert v_text is not None and v_fc is not None
    assert v_text.rule_id == v_fc.rule_id == "skill.flow.checkpoint"
    assert v_text.layer == v_fc.layer == "skill"
    assert v_text.ok is False and v_fc.ok is False
    assert v_text.ok == v_fc.ok
    assert v_text.message == v_fc.message, "拦截原因必须逐字节一致（同一源）"
    assert "流程门禁拦截" in v_text.message


def test_r2_dual_track_flow_gate_pass_identical():
    """规格已定稿：两轨一致放行（None）。"""
    gates = _spec_gate_set()
    # 构造规格已定稿的客观状态（spec_doc_finalized 判定路径同 prompt_gates）
    state = {
        "documents": [
            {"name": "Final_Video_Spec.md", "content": "视频标题：测试\n总时长：60秒\n"},
        ],
        "interaction": {"spec_doc_finalized": True},
    }
    text_op = gates.classify_action({"action": "storyboard_shots"})
    fc_op = gates.classify_fc("storyboard_shots", {})
    assert guard_pipeline.evaluate_flow_gate(gates, text_op, state) is None
    assert guard_pipeline.evaluate_flow_gate(gates, fc_op, state) is None


def test_r2_flow_gate_verdict_audited():
    """拦截 verdict 经 audit_verdicts 入 trace（前端 chips 同源）。"""
    AgentTracer.reset()
    tracer = AgentTracer.get_instance()
    tracer.start_trace("R2 测试")
    tracer.start_step()
    gates = _spec_gate_set()
    op = gates.classify_fc("storyboard_shots", {})
    verdict = guard_pipeline.evaluate_flow_gate(
        gates, op, {"documents": []}, action_name="storyboard_shots", skill_name="测试Skill",
    )
    assert verdict is not None
    tracer.end_step(1, actions_applied=0, finish_reason="gate")
    record = tracer.finish_trace(total_actions=0)
    gate_entries = record["steps"][0]["gates"]
    assert any(
        g["rule_id"] == "skill.flow.checkpoint" and not g["ok"]
        and g["skill_name"] == "测试Skill"
        for g in gate_entries
    )
    AgentTracer.reset()


def test_r2_single_implementation_consumption():
    """G4 消费点唯一性：两轨源码均经 evaluate_flow_gate 判定；
    轨道文件内不再出现 check_op+block_reason 内联组装（防镜像回潮）。"""
    al_src = (ROOT / "src/video_agent/core/agent_loop.py").read_text(encoding="utf-8")
    fcr_src = (ROOT / "src/video_agent/core/fc_tool_runner.py").read_text(encoding="utf-8")
    assert "guard_pipeline.evaluate_flow_gate(" in al_src
    assert "guard_pipeline.evaluate_flow_gate(" in fcr_src
    # 两轨不得再各自内联判定组装（classify_* 分类器保留，属轨道特化）
    for src in (al_src, fcr_src):
        assert not re.search(r"\.check_op\(", src), "check_op 只允许出现在 guard_pipeline/flow_gates"
        assert ".block_reason(" not in src, "block_reason 只允许出现在 guard_pipeline/flow_gates"
