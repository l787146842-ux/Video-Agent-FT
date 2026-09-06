"""agent_loop 错误分流（任务 #26）。

钉死：
- 供应商 AdapterError（transient 重试耗尽 / permanent）只调一次 llm_call 即上抛，
  循环侧绝不 nudge（nudge 专属模型侧空/畸形输出）；
- 空/畸形输出已随批 2 改为收轮不重试（判空 = 正常收轮），与供应商错误路径仍分离。
"""
import pytest

from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.exceptions import AdapterError
from src.video_agent.state.manager import StateManager


@pytest.fixture
def executor(tmp_path):
    return StateOperationExecutor(StateManager(str(tmp_path)))


def make_error_llm(err, calls):
    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        raise err
    return llm_call


async def test_transient_adapter_error_not_nudged(executor):
    """transient 错误（适配层重试耗尽后到达）：循环不 nudge，一次即上抛"""
    calls = {"n": 0}
    err = AdapterError("LLM 返回 HTTP 503: busy", retryable=True,
                       http_status=503, kind="upstream")
    llm = make_error_llm(err, calls)
    with pytest.raises(AdapterError) as ei:
        await run_agent_loop(
            "x", llm_call=llm, context_builder=lambda: "ctx",
            executor=executor, history=[],
        )
    assert calls["n"] == 1          # 只调一次，没有坏输出 nudge 重试
    assert ei.value.retryable is True
    assert ei.value.kind == "upstream"


async def test_permanent_adapter_error_not_nudged(executor):
    """permanent 错误（鉴权失败）：同样一次即上抛，不进 nudge 路径"""
    calls = {"n": 0}
    err = AdapterError("LLM 返回 HTTP 401: bad key", retryable=False,
                       http_status=401, kind="auth")
    llm = make_error_llm(err, calls)
    with pytest.raises(AdapterError) as ei:
        await run_agent_loop(
            "x", llm_call=llm, context_builder=lambda: "ctx",
            executor=executor, history=[],
        )
    assert calls["n"] == 1
    assert ei.value.kind == "auth"


async def test_model_refusal_error_not_nudged(executor):
    """模型明确拒答（refusal，permanent）：不 nudge，直接上抛"""
    calls = {"n": 0}
    err = AdapterError("LLM 中继拒收通知单（HTTP 403）", retryable=False,
                       http_status=403, kind="refusal")
    llm = make_error_llm(err, calls)
    with pytest.raises(AdapterError):
        await run_agent_loop(
            "x", llm_call=llm, context_builder=lambda: "ctx",
            executor=executor, history=[],
        )
    assert calls["n"] == 1


async def test_bad_output_ends_turn_separately(executor):
    """模型侧空输出（非供应商错误）：批 2 收轮语义，与错误分流互不干扰"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return "", "stop", 0, 0.0, {}

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    # 一次调用即收轮（nudge 重试已随批 2 退役）
    assert calls["n"] == 1
    assert "空响应" in result.text
