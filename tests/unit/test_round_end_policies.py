"""四轮 R1 回归：轮末策略状态机（F47 清偿）。

覆盖：
1. 策略表完整性——12 条策略、优先级唯一且为现行顺序（10→120，D1 零行为变更基线）；
2. 逐策略最小用例（gate_heal/规格收集豁免/结构自检/阶段兜底/虚报审计/流程门禁暂停）；
3. 仲裁顺序锁定——多策略同时命中时胜出者 = 重构前书写顺序（先到先得）；
4. 仲裁可观测（#4）——候选与胜出者经 tracer.record_card_decision 入 step。
"""
import asyncio
from typing import Any, Dict, List

import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core import round_end_policies as rep
from src.video_agent.core.round_end_policies import (
    RoundEndContext,
    run_round_end_policies,
)
from src.video_agent.core.tracer import AgentTracer


class FakeExecutor:
    """最小执行器桩：承载策略所需属性（状态/闸机/结构/日志）。"""

    def __init__(self, state=None):
        self.state = state if state is not None else {"storyboard": []}
        self.gate_rejections: List[str] = []
        self.skill_stages_done = set()
        self.documents_written: List[str] = []
        self.structure_kinds_created = set()
        self.gate_enabled = False
        self.gate_override: Any = False

    def strip_action_blocks(self, content: str) -> str:
        return content

    def _describe_action(self, action: Dict[str, Any]) -> str:
        return str(action.get("action", ""))


def _run(ctx: RoundEndContext, policies=None, tracer=None) -> RoundEndContext:
    async def emit(event):
        pass

    return asyncio.run(run_round_end_policies(ctx, emit, tracer=tracer, policies=policies))


def test_r1_policy_table_shape():
    """策略表 = 10 条（0817：结构自检/回退/覆盖三策略归位为阶段审阅一条），
    优先级唯一且仲裁顺序确定。"""
    table = rep.ROUND_END_POLICIES
    assert len(table) == 10
    ids = [p.policy_id for p in sorted(table, key=lambda p: p.priority)]
    assert ids == [
        "flow_gate_pause", "partial_fail_warnings", "gate_heal",
        "spec_doc_written_pause", "spec_review_pending", "spec_wizard_takeover",
        "spec_collect", "structure_stage_review",
        "stage_done_fallback", "false_claim_audit",
    ]
    priorities = [p.priority for p in table]
    assert len(set(priorities)) == 10, "优先级必须唯一（仲裁顺序确定性）"


def test_r1_gate_heal_drops_confirmation_and_continues():
    """gate_heal（8888 事故）：拦截时丢弃暂停信号、wants_continue=True、警告入账。"""
    ex = FakeExecutor()
    ctx = RoundEndContext(
        step=1, executor=ex, content="已写入 9 条",
        confirmation="请确认提示词", confirmation_options=[{"label": "确认", "description": ""}],
        total_exec=9, applied=1, gate_rejections=["提示词不合格"],
    )
    out = _run(ctx)
    assert out.gate_heal is True
    assert out.confirmation == ""
    assert out.wants_continue is True
    assert any("被流程闸机拦截" in w for w in out.result_warnings)


def test_r1_partial_fail_warning_order():
    """失败警告（优先级 15）在 gate_heal 之前求值：拦截原因版警告先入账。"""
    ex = FakeExecutor()
    ctx = RoundEndContext(
        step=2, executor=ex, content="", total_exec=3, applied=1,
        gate_rejections=["越阶写入被拒"],
    )
    out = _run(ctx)
    assert any("被流程闸机拦截" in w and "原因" in w for w in out.result_warnings)


def test_r1_spec_collect_exempt_scope_all():
    """规格收集闸 scope=all 豁免：只附警告不弹卡（用户第一）。"""
    ex = FakeExecutor()
    ex.skill_stages_done.add("script_analyze")
    ex.gate_override = "all"
    ctx = RoundEndContext(step=1, executor=ex, content="")
    out = _run(ctx)
    assert out.confirmation == ""
    assert any("豁免规格收集暂停" in w for w in out.result_warnings)


def test_r1_stage_done_fallback_requires_executor_action():
    """阶段兜底卡（5555）：执行器动作 + 未暂停才补卡；gate_heal 时不补。"""
    ex = FakeExecutor()
    ctx = RoundEndContext(
        step=1, executor=ex, content="", applied=1,
        executable=[{"action": "storyboard_shots"}],
    )
    out = _run(ctx)
    assert out.confirmation == "阶段执行完成，请审阅左侧故事板结果"
    assert len(out.confirmation_options) == 2
    # gate_heal 时兜底卡不触发
    ctx2 = RoundEndContext(
        step=1, executor=ex, content="", applied=1,
        executable=[{"action": "storyboard_shots"}],
        total_exec=2, gate_rejections=["拒收"],
    )
    out2 = _run(ctx2)
    assert out2.confirmation == ""


def test_r1_false_claim_audit_warns_but_keeps_pause():
    """虚报审计（7777×4444）：声称完成但故事板空 → 警告 + 保留暂停。"""
    ex = FakeExecutor({"storyboard": []})
    ctx = RoundEndContext(
        step=1, executor=ex, content="已完成关键元素拆解，请验收",
        confirmation="请审阅",
    )
    out = _run(ctx)
    assert any("检测到虚报" in w for w in out.result_warnings)
    assert out.confirmation == "请审阅", "系统不没收模型暂停（4444 语义）"
    assert out.result_text == "已完成关键元素拆解，请验收"


def test_r1_flow_gate_pause_hard_break():
    """flow_gate_pause（hard_break）：命中即中止，confirmation 保留模型文案优先。"""

    class FakeFlowGates:
        def consume_blocked(self):
            return True

        def pause_message(self):
            return "系统流程门禁：请先完成上一阶段"

    ex = FakeExecutor()
    ctx = RoundEndContext(
        step=1, executor=ex, content="", flow_gates=FakeFlowGates(),
        confirmation="模型自发暂停文案",
    )
    out = _run(ctx)
    assert out.hard_break is True
    assert out.hard_break_finish == "gate_pause"
    assert out.confirmation == "模型自发暂停文案"  # confirmation or pause_message


def test_r1_arbitration_order_lock():
    """仲裁顺序锁定（D1 基线）：spec_review_pending 与 stage_done_fallback 同时命中
    → 胜出者必须是优先级更高（数值更小）的 spec_review_pending（先到先得）。"""
    ex = FakeExecutor()
    ex.state.setdefault("interaction", {})["spec_review_pending"] = True
    ctx = RoundEndContext(
        step=1, executor=ex, content="", applied=1,
        executable=[{"action": "storyboard_shots"}],
    )
    out = _run(ctx)
    assert out.winner == "spec_review_pending"
    assert "spec_review_pending" in out.candidates
    # stage_done_fallback 的条件在 confirmation 已被占用后为假，不入候选
    assert "stage_done_fallback" not in out.candidates


def test_r1_card_decision_into_trace():
    """#4 仲裁可观测：候选+胜出者经 tracer 入当前 step 的 card_decisions。"""
    AgentTracer.reset()
    tracer = AgentTracer.get_instance()
    tracer.start_trace("R1 测试")
    tracer.start_step()
    ex = FakeExecutor()
    ctx = RoundEndContext(
        step=1, executor=ex, content="", applied=1,
        executable=[{"action": "storyboard_shots"}],
    )
    _run(ctx, tracer=tracer)
    tracer.end_step(1, actions_applied=1, finish_reason="confirmation")
    record = tracer.finish_trace(total_actions=1)
    cards = record["steps"][0]["card_decisions"]
    assert len(cards) == 1
    assert cards[0]["winner"] == "stage_done_fallback"
    assert "stage_done_fallback" in cards[0]["candidates"]
    AgentTracer.reset()


def test_r1_structure_override_replaces_options_only():
    """0817 用户裁决：模型自发暂停完全保留（文案+选项均不覆盖）。

    注：需 gate_enabled + strict 模式；gate_mode 依赖环境变量，此处直接构造
    条件成立的 executor 并 monkeypatch gate_mode。"""
    ex = FakeExecutor()
    ex.gate_enabled = True
    ex.structure_kinds_created = {"keyElement"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(prompt_gates, "gate_mode", lambda: "strict")
        ctx = RoundEndContext(
            step=1, executor=ex, content="",
            confirmation="模型自拟：开始生成视频",
            confirmation_options=[{"label": "模型选项", "description": ""}],
        )
        out = _run(ctx)
    assert out.confirmation == "模型自拟：开始生成视频", "文案保留"
    assert out.confirmation_options == [{"label": "模型选项", "description": ""}], "选项也保留"
