"""失败恢复策略分派表语义钉死（任务 #10 失败恢复分级）。

钉死：
1. 分派表覆盖四类失败且处置动作/重试预算符合分级结论
   （bad_output=nudge_retry×2；tool/gate/adapter 一律不循环重试）；
2. 未登记失败类型显式 KeyError（禁止静默兜底）；
3. 分类器优先级：供应商错误 > 闸机拦截 > 空/畸形输出；
4. agent_loop 的重试预算数据驱动：改分派表即改循环行为。
"""
import pytest

from src.video_agent.core import recovery_policy as rp
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.exceptions import AdapterError
from src.video_agent.state.manager import StateManager


def test_table_covers_four_failure_kinds():
    assert set(rp.RECOVERY_POLICIES) == {
        rp.FAILURE_BAD_OUTPUT,
        rp.FAILURE_TOOL,
        rp.FAILURE_GATE,
        rp.FAILURE_ADAPTER,
    }


def test_actions_and_retry_budgets():
    bad = rp.recovery_for(rp.FAILURE_BAD_OUTPUT)
    assert bad.action == rp.ACTION_NUDGE_RETRY
    assert bad.max_retries == 2
    # 其余三类一律不循环重试（分级出口各自承接）
    for kind in (rp.FAILURE_TOOL, rp.FAILURE_GATE, rp.FAILURE_ADAPTER):
        assert rp.recovery_for(kind).max_retries == 0
    assert rp.recovery_for(rp.FAILURE_TOOL).action == rp.ACTION_FEEDBACK_DEGRADE
    assert rp.recovery_for(rp.FAILURE_GATE).action == rp.ACTION_STRUCTURED_REPORT
    assert rp.recovery_for(rp.FAILURE_ADAPTER).action == rp.ACTION_ESCALATE


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
    # 闸机拦截次之
    assert rp.classify_step_failure(
        gate_rejections=["gate:x"], content="有正文") == rp.FAILURE_GATE
    # 空/畸形输出：无正文且无工具执行
    assert rp.classify_step_failure(content="   ", fc_applied=0) == rp.FAILURE_BAD_OUTPUT
    # 带工具执行的失败信号归工具失败（回喂通道承接）
    assert rp.classify_step_failure(content="", fc_applied=2) == rp.FAILURE_TOOL


@pytest.fixture
def executor(tmp_path):
    return StateOperationExecutor(StateManager(str(tmp_path)))


async def test_loop_retry_budget_driven_by_dispatch_table(executor, monkeypatch):
    """重试上限取自分派表（数据驱动）：bad_output max_retries=0 →
    空输出不再 nudge，一次调用即走空响应兜底路径"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return "", "stop", 0

    patched = dict(rp.RECOVERY_POLICIES)
    patched[rp.FAILURE_BAD_OUTPUT] = rp.RecoveryPolicy(
        kind=rp.FAILURE_BAD_OUTPUT,
        action=rp.ACTION_NUDGE_RETRY,
        max_retries=0,
        rationale="测试改写预算",
    )
    monkeypatch.setattr(rp, "RECOVERY_POLICIES", patched)
    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1  # 无 nudge 重试
    assert "输出异常" not in result.text  # 未入坏输出收尾文案


async def test_loop_default_budget_nudges_twice(executor):
    """默认分派表下空输出仍 nudge 重试 2 次（行为不回退）"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return "", "stop", 0

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 3  # 首调 + 2 次 nudge
    assert "输出异常" in result.text
    assert rp.recovery_for(rp.FAILURE_BAD_OUTPUT).max_retries == 2
