"""失败恢复策略分派表语义钉死（任务 #10 失败恢复分级；五项修法批 2 收轮语义）。

钉死：
1. 分派表覆盖四类失败且处置动作/重试预算符合分级结论
   （bad_output / output_truncated = end_with_notice 收轮不重试；
   tool/adapter 一律不循环重试；productive_reject 有界续轮）；
2. 未登记失败类型显式 KeyError（禁止静默兜底）；
3. 分类器优先级：供应商错误 > 空响应（按 finish_reason 分流截断/真空）；
4. agent_loop 消费分派表：空响应一次调用即收轮，绝不原样重试
   （4444 事故根因③；分派表无键时显式 KeyError，禁静默兜底）。

退役记录（2026-09-03 Q2 裁决）：闸机拦截分派键已退役（FC 轨由
fc_gates reject_message 闭环，循环层无真实输入源）。
退役记录（2026-09-07 批 2）：bad_output 的 nudge_retry 处置退役
（判空 = 正常收轮），output_truncated 新增。
"""
import pytest

from src.video_agent.core import recovery_policy as rp
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.exceptions import AdapterError
from src.video_agent.state.manager import StateManager


def test_table_covers_failure_kinds():
    assert set(rp.RECOVERY_POLICIES) == {
        rp.FAILURE_BAD_OUTPUT,
        rp.FAILURE_OUTPUT_TRUNCATED,  # 批 2：输出预算截断（finish_reason=length）
        rp.FAILURE_TOOL,
        rp.FAILURE_ADAPTER,
        rp.FAILURE_PRODUCTIVE_REJECT,  # 批 12：产出类被拒混合轮续轮预算（1000 清偿）
        rp.FAILURE_UNSTAMPED_STOP,  # 完成盖章批（dsh A2）：零动作未盖章收尾续跑预算
    }


def test_actions_and_retry_budgets():
    # 批 2：空响应/撞帽 = 收轮 + 用户可见提示，绝不循环重试
    bad = rp.recovery_for(rp.FAILURE_BAD_OUTPUT)
    assert bad.action == rp.ACTION_END_WITH_NOTICE
    assert bad.max_retries == 0
    trunc = rp.recovery_for(rp.FAILURE_OUTPUT_TRUNCATED)
    assert trunc.action == rp.ACTION_END_WITH_NOTICE
    assert trunc.max_retries == 0
    # 其余两类一律不循环重试（分级出口各自承接）
    for kind in (rp.FAILURE_TOOL, rp.FAILURE_ADAPTER):
        assert rp.recovery_for(kind).max_retries == 0
    assert rp.recovery_for(rp.FAILURE_TOOL).action == rp.ACTION_FEEDBACK_DEGRADE
    assert rp.recovery_for(rp.FAILURE_ADAPTER).action == rp.ACTION_ESCALATE
    # 批 12：产出类被拒混合轮 = 回喂自处置 + 有界续轮预算（防打转烧满 max_steps）
    prod = rp.recovery_for(rp.FAILURE_PRODUCTIVE_REJECT)
    assert prod.action == rp.ACTION_FEEDBACK_DEGRADE
    assert prod.max_retries == 2


def test_nudge_retry_action_retired():
    """批 2 退役钉死：nudge_retry 动作键与任何表条目都不再关联（防复活）。"""
    assert not hasattr(rp, "ACTION_NUDGE_RETRY")
    assert all(p.action != "nudge_retry" for p in rp.RECOVERY_POLICIES.values())


def test_every_entry_has_rationale():
    for pol in rp.RECOVERY_POLICIES.values():
        assert pol.kind in rp.RECOVERY_POLICIES
        assert pol.rationale.strip()


def test_unknown_kind_raises_not_silent():
    with pytest.raises(KeyError):
        rp.recovery_for("not_registered")


def test_classify_priority():
    err = AdapterError("boom")
    # 供应商错误最高优先（即便同时空输出）
    assert rp.classify_step_failure(
        adapter_error=err, content="", fc_applied=0) == rp.FAILURE_ADAPTER
    # 空响应按 finish_reason 分流（批 2）：length = 输出预算截断
    assert rp.classify_step_failure(
        content="   ", fc_applied=0, finish_reason="length") == rp.FAILURE_OUTPUT_TRUNCATED
    # 空响应且非 length = 真空响应
    assert rp.classify_step_failure(
        content="   ", fc_applied=0, finish_reason="stop") == rp.FAILURE_BAD_OUTPUT
    assert rp.classify_step_failure(content="   ", fc_applied=0) == rp.FAILURE_BAD_OUTPUT
    # 带工具执行的失败信号归工具失败（回喂通道承接）；length 不改判
    assert rp.classify_step_failure(content="", fc_applied=2) == rp.FAILURE_TOOL
    assert rp.classify_step_failure(
        content="", fc_applied=2, finish_reason="length") == rp.FAILURE_TOOL
    # 有正文时归工具失败（非空输出）
    assert rp.classify_step_failure(content="有正文", fc_applied=0) == rp.FAILURE_TOOL


@pytest.fixture
def executor(tmp_path):
    return StateOperationExecutor(StateManager(str(tmp_path)))


def _assert_bad_output_turn_end(result, finish_key):
    """收轮语义公共断言：一次调用、收轮文案、警告、retry 芯片、trace 键。"""
    steps = result.trace.get("steps", [])
    assert steps and steps[-1]["finish_reason"] == finish_key


async def test_loop_empty_stop_ends_turn_no_retry(executor):
    """批 2：空响应（stop）一次调用即收轮，不重试（4444 根因③）。"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return "", "stop", 0, 0.0, {}

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1, "判空收轮绝不原样重试"
    assert "空响应" in result.text
    assert result.warnings and "空响应" in result.warnings[-1]
    assert result.suggested_actions and result.suggested_actions[-1]["kind"] == "retry"
    _assert_bad_output_turn_end(result, "bad_output")


async def test_loop_truncation_ends_turn_no_retry(executor):
    """批 2：输出预算截断（finish_reason=length）收轮 + 截断文案，不重试。"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return "", "length", 0, 0.0, {}

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1, "撞帽收轮绝不原样重试（dsh 同语义）"
    assert "截断" in result.text
    assert result.warnings and "输出预算" in result.warnings[-1]
    assert result.suggested_actions and result.suggested_actions[-1]["kind"] == "retry"
    _assert_bad_output_turn_end(result, "output_truncated")


async def test_loop_all_rejected_round_not_swallowed(executor):
    """批 9 语义保住：全拒收 FC 轮（had_fc_calls=True、正文空）不落判空收轮，
    拒因回喂必须被下一轮消费（继续循环）。"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return "", "stop", 0, 0.0, {"had_fc_calls": True}
        return "好的，已按指引调整。", "stop", 0, 0.0, {}

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 2, "全拒收轮应续轮消费拒因，不按空响应收轮"
    assert "已按指引调整" in result.text


async def test_loop_nonempty_truncation_keeps_existing_warning(executor):
    """非空但 length 截断：既有轮末警告保留（批 2 既有语义不动）。"""
    async def llm_call(system_prompt, messages, stream_hook=None):
        return "可见正文", "length", 0, 0.0, {}

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert result.text == "可见正文"
    assert any("被 max_tokens 截断" in w for w in result.warnings)


async def test_loop_consumes_dispatch_table(executor, monkeypatch):
    """分派表承接点：未登记键显式 KeyError（禁静默兜底，policy-as-data）。"""
    async def llm_call(system_prompt, messages, stream_hook=None):
        return "", "stop", 0, 0.0, {}

    patched = {k: v for k, v in rp.RECOVERY_POLICIES.items()
               if k != rp.FAILURE_BAD_OUTPUT}
    monkeypatch.setattr(rp, "RECOVERY_POLICIES", patched)
    with pytest.raises(KeyError):
        await run_agent_loop(
            "x", llm_call=llm_call, context_builder=lambda: "ctx",
            executor=executor, history=[],
        )
