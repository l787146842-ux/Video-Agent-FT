"""814R2 钉死回归：统一闸机管线接线 + 文案外置 + 审计闭环。

事故背景：8/12 回退后 guard_pipeline（宪法 §2.0 唯一组合实现）无人调用，
双轨各自内联组装判定；gates/messages.md 文案外置断线；tracer 无闸机审计。
本测试钉死恢复后的行为，防再次断线。
"""
import pytest

from src.video_agent.core import guard_pipeline, prompt_gates
from src.video_agent.core.guard_pipeline import (
    GateVerdict,
    audit_verdicts,
    evaluate_prompt_write,
    prompt_write_verdict,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.utils.prompts import load_prompt_section

# 结构齐全的合规分镜（默认策略放行）
_OK_SHOT = (
    "镜头总时长：12秒。缓慢推入中景，主角在冰原上奔跑，怀中紧抱文物，"
    "背景崩裂成平面，光影克制，色调深青，<音效轰鸣>，no music，no subtitles。"
)
# 整段英文（8888 事故形态：语言闸应拦）
_BAD_EN_SHOT = (
    "Camera: Slow push-in wide shot, subject runs across the ice plain holding "
    "the relic, background collapsing into flat planes. Duration 12s. "
    "<low rumbling sound effects>, no music, no subtitles."
)


@pytest.fixture(autouse=True)
def _reset_tracer():
    AgentTracer.reset()
    yield
    AgentTracer.reset()


def _empty_state():
    return {"keyElements": [], "shots": [], "audioItems": [], "documents": []}


class TestUnifiedPipeline:
    def test_ok_prompt_passes(self):
        out = evaluate_prompt_write(_OK_SHOT, "shot", _empty_state())
        assert out.ok is True
        assert out.warnings == []

    def test_bad_prompt_rejected_with_message(self):
        out = evaluate_prompt_write(_BAD_EN_SHOT, "shot", _empty_state())
        assert out.ok is False
        assert out.reject_message
        assert out.hard_errors

    def test_user_override_downgrades_to_warning(self):
        out = evaluate_prompt_write(
            _BAD_EN_SHOT, "shot", _empty_state(), gate_override="all",
        )
        assert out.ok is True
        assert out.overridden is True
        assert any("仅为警告" in w for w in out.warnings)

    def test_element_image_flow_gate_warn_only(self):
        """流程闸只警告不拦人（4444 语义）"""
        state = _empty_state()
        state["keyElements"] = [{"id": "ke-1", "title": "A", "drafts": [{"id": "d1"}]}]
        out = evaluate_prompt_write(
            _OK_SHOT, "shot", state, element_image_missing=True,
        )
        assert out.ok is True, "元素图缺失只警告，不得拦截写入"
        assert prompt_gates.SHOT_SEQUENCE_GATE_ERROR in out.warnings

    def test_verdicts_structured(self):
        out = evaluate_prompt_write(_BAD_EN_SHOT, "shot", _empty_state())
        assert any(
            isinstance(v, GateVerdict) and v.rule_id == "skill.prompt_structure" and not v.ok
            for v in out.verdicts
        )

    def test_prompt_write_verdict_wrapper_consistent(self):
        """单 verdict 便捷出口与组合实现判定一致"""
        v_bad = prompt_write_verdict(_BAD_EN_SHOT, "shot", _empty_state())
        assert v_bad.ok is False
        v_ok = prompt_write_verdict(_OK_SHOT, "shot", _empty_state())
        assert v_ok.ok is True

    def test_dual_track_same_source(self):
        """双轨同源：FC 轨与文本轨的判定函数是同一个（防再次各自组装）"""
        import inspect

        from src.video_agent.core import fc_tool_runner
        from src.video_agent.web import action_executor

        fc_src = inspect.getsource(fc_tool_runner.FCToolRunner._prompt_gate)
        te_src = inspect.getsource(action_executor.StudioActionExecutor._gate_check)
        assert "guard_pipeline.evaluate_prompt_write" in fc_src
        assert "guard_pipeline.evaluate_prompt_write" in te_src


class TestMessagesExternalized:
    def test_gate_constants_from_messages_md(self):
        pairs = [
            (prompt_gates.SPEC_GATE_ERROR, "SPEC_GATE"),
            (prompt_gates.STORYBOARD_PENDING_GATE_ERROR, "STORYBOARD_PENDING"),
            (prompt_gates.KEY_ELEMENT_FIRST_GATE_ERROR, "KEY_ELEMENT_FIRST"),
            (prompt_gates.SHOT_SEQUENCE_GATE_ERROR, "SHOT_SEQUENCE"),
            (prompt_gates.GENERATION_CONFIRM_GATE_ERROR, "GENERATION_CONFIRM"),
            (prompt_gates.GENERATION_CONFIRM_GATE_BLOCKED, "GENERATION_CONFIRM_BLOCKED"),
        ]
        for const, section in pairs:
            assert const == load_prompt_section("gates/messages.md", section), section

    def test_structure_pause_cards_from_messages_md(self):
        msg, opts = prompt_gates.structure_paused_confirmation({"keyElement"})
        assert msg == prompt_gates.STORYBOARD_STRUCTURE_PAUSED_MSG
        assert opts == prompt_gates.STORYBOARD_STRUCTURE_OPTIONS
        msg2, opts2 = prompt_gates.structure_paused_confirmation({"shot"})
        assert msg2 == prompt_gates.SHOT_STRUCTURE_PAUSED_MSG
        assert opts2 == prompt_gates.SHOT_STRUCTURE_OPTIONS

    def test_registry_covers_layers(self):
        assert prompt_gates.GATE_RULES["platform.gen_confirm"].layer == "platform"
        assert prompt_gates.GATE_RULES["skill.require_subtitle"].layer == "skill"


class TestGateAudit:
    def test_record_gate_recent_and_step(self):
        tracer = AgentTracer.get_instance()
        tracer.start_trace("hi")
        tracer.start_step()
        tracer.record_gate("skill.prompt_structure", "skill", False, message="x" * 300)
        recent = tracer.get_recent_gates(10)
        assert recent and recent[0]["rule_id"] == "skill.prompt_structure"
        assert len(recent[0]["message"]) <= 200, "message 应截断"
        tracer.end_step(1, actions_applied=0)
        rec = tracer.finish_trace()
        assert rec["steps"][0]["gates"], "step 应归档闸机判定"

    def test_audit_verdicts_writes_trace(self):
        tracer = AgentTracer.get_instance()
        tracer.start_trace("hi")
        tracer.start_step()
        audit_verdicts([GateVerdict("skill.prompt_structure", "skill", True)], skill_name="S")
        assert tracer.get_recent_gates(5)[0]["skill_name"] == "S"

    def test_gates_endpoint(self):
        from fastapi.testclient import TestClient

        from src.video_agent.web.app import app

        client = TestClient(app)
        resp = client.get("/api/agent/gates")
        assert resp.status_code == 200
        data = resp.json()
        assert "recent" in data and isinstance(data["rules"], list)
        rule_ids = {r["rule_id"] for r in data["rules"]}
        assert "platform.gen_confirm" in rule_ids
