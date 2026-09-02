"""四轮 R1 回归：轮末策略状态机（F47 清偿）。

覆盖：
1. 策略表完整性——5 条策略、优先级唯一且为现行顺序（stage_done_fallback
   随 S10 退役删除，用户裁决 2026-09-02）；
2. 逐策略最小用例（gate_heal/结构审阅/虚报审计）；
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
    """策略表 = 5 条（2026-09-02 用户裁决：stage_done_fallback 随 S10 退役删除），
    优先级唯一且仲裁顺序确定。"""
    table = rep.ROUND_END_POLICIES
    assert len(table) == 5
    ids = [p.policy_id for p in sorted(table, key=lambda p: p.priority)]
    assert ids == [
        "partial_fail_warnings", "gate_heal",
        "structure_stage_review",
        "false_claim_audit", "aborted_continuation_audit",
    ]
    priorities = [p.priority for p in table]
    assert len(set(priorities)) == 5, "优先级必须唯一（仲裁顺序确定性）"


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


# test_r1_stage_done_fallback_requires_executor_action 已随 S10 退役删除
# （用户裁决 2026-09-02：退役条件指向已废编排器、永远到不了期，属违规悬置，
# 直接删除；阶段边界暂停归模型 workflow_pause 与 structure_stage_review）。


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


def test_r1_card_decision_into_trace():
    """#4 仲裁可观测：候选+胜出者经 tracer 入当前 step 的 card_decisions。

    （S10 退役后唯一 arbitrable 策略 = structure_stage_review，改用其验证仲裁入 trace）"""
    AgentTracer.reset()
    tracer = AgentTracer.get_instance()
    tracer.start_trace("R1 测试")
    tracer.start_step()
    ex = FakeExecutor()
    ex.gate_enabled = True
    ex.structure_kinds_created = {"keyElement"}
    ex._storyboard_empty_before = True
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(prompt_gates, "gate_mode", lambda: "strict")
        mp.setattr(prompt_gates, "storyboard_stage_complete", lambda *a, **k: True)
        ctx = RoundEndContext(step=1, executor=ex, content="", applied=1)
        _run(ctx, tracer=tracer)
    tracer.end_step(1, actions_applied=1, finish_reason="confirmation")
    record = tracer.finish_trace(total_actions=1)
    cards = record["steps"][0]["card_decisions"]
    assert len(cards) == 1
    assert cards[0]["winner"] == "structure_stage_review"
    assert "structure_stage_review" in cards[0]["candidates"]
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
