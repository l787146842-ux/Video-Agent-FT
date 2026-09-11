"""轮末策略状态机回归（I-1 收敛 + partial_fail 退役后 2 条策略）。

覆盖：
1. 策略表完整性——2 条策略、优先级唯一且为现行顺序
   （闸机自愈/结构审阅死副本随 2026-09-03 I-1 收敛退役；轮末工具失败
   汇总策略同批退役——生产恒不可达，工具成败归 FC 轨 fc_feedback 逐步回喂）；
2. 逐策略最小用例（虚报审计/假停兜底）；
3. 仲裁可观测——候选与胜出者经 tracer.record_card_decision 入 step；
4. 登记期依赖自检强化（I-1.4）——
   a) requires 引用不存在字段 → 报错；
   b) getattr(ctx, ..., 默认值) 死规则入口形态 → 报错；
   c) requires 与实际 ctx 访问不符（幽灵依赖 / 隐藏依赖）→ 报错；
   d) 访问已退役/不存在属性 → 报错；
   e) 合法策略通过。
"""
import asyncio
from typing import Any, Dict

import pytest

from src.video_agent.core import round_end_policies as rep
from src.video_agent.core.round_end_policies import (
    RoundEndContext,
    RoundEndPolicy,
    run_round_end_policies,
)
from src.video_agent.core.tracer import AgentTracer


class FakeExecutor:
    """最小执行器桩：承载策略所需属性（状态/闸机/日志）。"""

    def __init__(self, state=None):
        self.state = state if state is not None else {"storyboard": []}
        self.gate_enabled = False
        self.gate_override: Any = False

    def _describe_action(self, action: Dict[str, Any]) -> str:
        return str(action.get("action", ""))


def _run(ctx: RoundEndContext, policies=None, tracer=None) -> RoundEndContext:
    async def emit(event):
        pass

    return asyncio.run(run_round_end_policies(ctx, emit, tracer=tracer, policies=policies))


def test_r1_policy_table_shape():
    """策略表 = 2 条，优先级唯一且仲裁顺序确定。

    （2026-09-03 I-1：闸机自愈+结构审阅死副本退役；轮末工具失败汇总策略同批
    退役；2026-09-10 阶段规则去代码化批：完成盖章闸 completion_stamp_gate /
    unstamped_stop_notice 两条随盖章退役删除。）"""
    table = rep.ROUND_END_POLICIES
    assert len(table) == 2
    ids = [p.policy_id for p in sorted(table, key=lambda p: p.priority)]
    assert ids == [
        "false_claim_audit", "aborted_continuation_audit",
    ]
    priorities = [p.priority for p in table]
    assert len(set(priorities)) == 2, "优先级必须唯一（仲裁顺序确定性）"


def test_r1_no_ledger_field_after_retirement():
    """轮末工具失败汇总策略退役后，RoundEndContext 不再承载 ledger 字段
    （生产恒不可达的死输入随策略一并删除，不留悬空字段）。"""
    field_names = {f.name for f in rep.dc_fields(RoundEndContext)}
    assert "ledger" not in field_names


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
    """仲裁可观测：arbitrable 策略命中时候选+胜出者经 tracer 入 step。

    I-1 收敛后策略表无 arbitrable 策略（结构审阅死副本退役），
    用自定义 arbitrable 策略验证 tracer 接线仍通。"""
    AgentTracer.reset()
    tracer = AgentTracer.get_instance()
    tracer.start_trace("R1 测试")
    tracer.start_step()

    async def _apply_confirm(ctx, emit):
        ctx.confirmation = "测试暂停"

    custom = [
        RoundEndPolicy("test_arb", rep.KIND_ARBITRABLE, 10,
                       lambda c: True, _apply_confirm,
                       requires=("confirmation",)),
    ]
    ctx = RoundEndContext(step=1, executor=FakeExecutor(), content="")
    _run(ctx, policies=custom, tracer=tracer)
    tracer.end_step(1, actions_applied=0, finish_reason="confirmation")
    record = tracer.finish_trace(total_actions=0)
    cards = record["steps"][0]["card_decisions"]
    assert len(cards) == 1
    assert cards[0]["winner"] == "test_arb"
    assert "test_arb" in cards[0]["candidates"]
    AgentTracer.reset()


# ---------- 登记期依赖自检强化（I-1.4）----------
# 用模块级命名函数（inspect.getsource 干净可解析）构造待检策略。

def _cond_false(ctx):
    return False


async def _apply_noop(ctx, emit):
    return None


def _cond_getattr_default(ctx):
    # 死规则入口形态：getattr 带默认值摸字段（真死因，旧自检零覆盖）
    return bool(getattr(ctx, "content", ""))


def _cond_reads_skill(ctx):
    return bool(ctx.skill)


def _cond_reads_unknown(ctx):
    return bool(ctx.retired_field_xyz)


def test_r1_self_check_rejects_missing_field():
    """(a) requires 声明不存在字段 → RuntimeError。"""
    bad = RoundEndPolicy("bad", rep.KIND_POST_PROCESS, 999,
                         _cond_false, _apply_noop,
                         requires=("nonexistent_field_xyz",))
    with pytest.raises(RuntimeError, match="nonexistent_field_xyz"):
        rep._validate_policy_table([bad])


def test_r1_self_check_rejects_getattr_default():
    """(b) getattr(ctx, ..., 默认值) 死规则入口形态 → RuntimeError。

    这正是上一代死副本的真死因形态：executor 是合法字段、
    requires=('executor',) 能 100% 通过旧自检，但 getattr 摸其已退役
    子属性拿默认假值使策略静默恒假。强化后机械拦截。"""
    bad = RoundEndPolicy("bad", rep.KIND_POST_PROCESS, 999,
                         _cond_getattr_default, _apply_noop,
                         requires=())
    with pytest.raises(RuntimeError, match="getattr"):
        rep._validate_policy_table([bad])


def test_r1_self_check_rejects_hidden_dependency():
    """(c1) 访问了输入依赖字段但未登记进 requires（隐藏依赖）→ RuntimeError。"""
    bad = RoundEndPolicy("bad", rep.KIND_POST_PROCESS, 999,
                         _cond_reads_skill, _apply_noop,
                         requires=())
    with pytest.raises(RuntimeError, match="skill"):
        rep._validate_policy_table([bad])


def test_r1_self_check_rejects_ghost_dependency():
    """(c2) requires 声明了实际未访问的字段（幽灵依赖）→ RuntimeError。"""
    bad = RoundEndPolicy("bad", rep.KIND_POST_PROCESS, 999,
                         _cond_false, _apply_noop,
                         requires=("content",))
    with pytest.raises(RuntimeError, match="content"):
        rep._validate_policy_table([bad])


def test_r1_self_check_rejects_unknown_attr_access():
    """(d) 直接访问 RoundEndContext 不存在的属性（如已退役字段）→ RuntimeError。"""
    bad = RoundEndPolicy("bad", rep.KIND_POST_PROCESS, 999,
                         _cond_reads_unknown, _apply_noop,
                         requires=())
    with pytest.raises(RuntimeError, match="retired_field_xyz"):
        rep._validate_policy_table([bad])


def test_r1_self_check_passes_valid():
    """(e) requires 与实际访问一致的合法策略通过（不抛异常）。"""
    good = RoundEndPolicy("good", rep.KIND_POST_PROCESS, 999,
                          _cond_reads_skill, _apply_noop,
                          requires=("skill",))
    rep._validate_policy_table([good])
