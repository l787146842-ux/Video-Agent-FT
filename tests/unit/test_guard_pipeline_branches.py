"""guard_pipeline 承重分支补强（P1-11b）：verdict 序列化 / 模式分档 / 审计降级。

钉死此前未覆盖分支（只加测试不改生产代码）：
① GateVerdict.to_dict 结构化序列化（含 description 取自 GATE_RULES）；
② evaluate_prompt_write 模式分档：off 直放行、非 strict 结构未过仅放行；
③ audit_verdicts 遥测降级：tracer.record_gate 抛异常不阻断主链路。
"""
import pytest

from src.video_agent.core import guard_pipeline
from src.video_agent.core.guard_pipeline import (
    GateVerdict,
    audit_verdicts,
    prompt_write_verdict,
)
from src.video_agent.core.tracer import AgentTracer


# ---------- ① GateVerdict.to_dict ----------

def test_gate_verdict_to_dict_structure():
    """结构化序列化：rule_id 归一 + description 取自规则注册表"""
    v = GateVerdict("platform.prompt_write", "platform", False, "结构不达标")
    d = v.to_dict()
    assert d["rule_id"] == "platform.prompt_write"
    assert d["layer"] == "platform"
    assert d["ok"] is False
    assert d["message"] == "结构不达标"
    # description 来自 GATE_RULES 元数据（非空说明规则已登记）
    assert isinstance(d["description"], str)


def test_gate_verdict_to_dict_unknown_rule_empty_description():
    """未登记 rule_id：description 兜底空串，不抛异常"""
    v = GateVerdict("platform.not_registered_x", "platform", True)
    d = v.to_dict()
    assert d["description"] == ""
    assert d["ok"] is True


# ---------- ② evaluate_prompt_write 模式分档 ----------

def test_mode_off_bypasses_structure_gate():
    """mode=off：结构闸直接放行（即便提示词敷衍）"""
    v = prompt_write_verdict("敷衍短句", "shot", {}, gate_enabled=True, mode="off")
    assert v.ok is True


def test_mode_warn_non_strict_passes_failed_structure():
    """mode=warn（非 strict）：结构未过不拒收，放行（仅 strict 才硬拦）"""
    v = prompt_write_verdict("敷衍短句", "shot", {}, gate_enabled=True, mode="warn")
    assert v.ok is True


def test_mode_strict_passes_without_char_floor():
    """mode=strict（对照）：字数地板退役后结构项无硬伤 → 不拒、无拒因文案。"""
    v = prompt_write_verdict("敷衍短句", "shot", {}, gate_enabled=True, mode="strict")
    assert v.ok is True
    assert not v.message


# ---------- ③ audit_verdicts 遥测降级 ----------

def test_audit_verdicts_swallows_tracer_exception(monkeypatch):
    """tracer.record_gate 抛异常：审计降级吞掉，不阻断主链路（不向上抛）"""

    def _boom(self, *args, **kwargs):
        raise RuntimeError("tracer 故障")

    monkeypatch.setattr(AgentTracer, "record_gate", _boom)
    # 不应抛出——降级吞异常即本分支契约
    audit_verdicts(
        [GateVerdict("platform.prompt_write", "platform", True)],
        action="test_action",
    )


def test_audit_verdicts_overridden_flag_passthrough(monkeypatch):
    """overridden=True 照常入审计（豁免留痕路径不吞正常调用）"""
    recorded = []

    def _rec(self, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(AgentTracer, "record_gate", _rec)
    audit_verdicts(
        [GateVerdict("platform.gen_confirm", "platform", True, "用户坚持")],
        action="gen", overridden=True,
    )
    assert recorded and recorded[0]["overridden"] is True


# ---------- 批 9：tool_risk 暂停卡同意账本（V6 计划） ----------

class TestToolRiskPauseConsent:
    """consented 命中范围由 CONSENT_CHARTER 声明（批 12 章程）：costly 生成
    ∪ 规格文档写入；其余 high 兜底拦截语义零改动（批 B 红线）；
    放行经 platform.tool_risk verdict 留痕。"""

    def test_consented_passes_costly_tool(self):
        AgentTracer.reset()
        try:
            err, warns = guard_pipeline.evaluate_tool_risk(
                "image_generate", costly=True, consented=True)
            assert err is None and warns and "consent=pause_accept" in warns[0]
            assert any(g["rule_id"] == "platform.tool_risk"
                       and g["ok"] and g["overridden"] for g in
                       AgentTracer.get_instance().get_recent_gates(20)), \
                "同意账本放行必须经 platform.tool_risk verdict 留痕"
        finally:
            AgentTracer.reset()

    def test_consented_does_not_open_non_costly_high_risk(self):
        """章程 other_high：未声明花钱且非规格写入的高危不吃同意（fail-closed）。"""
        err, _ = guard_pipeline.evaluate_tool_risk(
            "some_dangerous_op", costly=False, consented=True)
        assert err and "高风险工具确认闸拦截" in err

    def test_consented_passes_spec_write(self):
        """批 12 章程：暂停卡 accept 的同意覆盖规格文档写入（1000 清偿）——
        规格确认卡 accept 后重提 document_write 放行，verdict 留痕不变。"""
        AgentTracer.reset()
        try:
            err, warns = guard_pipeline.evaluate_tool_risk(
                "document_write", costly=False, spec_write=True, consented=True)
            assert err is None and warns and "consent=pause_accept" in warns[0]
            assert any(g["rule_id"] == "platform.tool_risk"
                       and g["ok"] and g["overridden"] for g in
                       AgentTracer.get_instance().get_recent_gates(20)), \
                "规格写入同意放行必须经 platform.tool_risk verdict 留痕"
        finally:
            AgentTracer.reset()

    def test_spec_write_without_consent_still_blocked(self):
        """批 12 章程负样本：规格写入没有同意账本命中仍拦（非无条件放行）。"""
        err, _ = guard_pipeline.evaluate_tool_risk(
            "document_write", costly=False, spec_write=True, consented=False)
        assert err and "高风险工具确认闸拦截" in err

    def test_no_consent_keeps_fail_closed(self):
        err, _ = guard_pipeline.evaluate_tool_risk(
            "image_generate", costly=True, consented=False)
        assert err and "高风险工具确认闸拦截" in err
