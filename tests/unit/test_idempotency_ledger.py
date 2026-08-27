"""轮内幂等键账本（T4）单测：去重语义与生命周期。"""
from src.video_agent.core.idempotency_ledger import IdempotencyLedger
from src.video_agent.tools.base import ToolResult


def test_same_key_returns_first_result():
    """同轮同键：返回首次结果（首次成功被缓存）"""
    ledger = IdempotencyLedger()
    first = ToolResult(success=True, data={"draft_id": "d1"})
    assert ledger.check("k1") is None  # 未登记不去重
    ledger.record("k1", first)
    second = ToolResult(success=True, data={"draft_id": "d2"})
    ledger.record("k1", second)  # 同键重复登记以首次为准
    assert ledger.check("k1") is first


def test_same_key_returns_first_failure_result():
    """首次失败也被缓存（避免重试触发重复副作用）"""
    ledger = IdempotencyLedger()
    failed = ToolResult(success=False, error="upstream error", error_code="upstream")
    ledger.record("k-err", failed)
    hit = ledger.check("k-err")
    assert hit is failed and hit.success is False


def test_empty_key_passes_through():
    """空键直通过不去重：查不命中、记不登记"""
    ledger = IdempotencyLedger()
    result = ToolResult(success=True, data={})
    assert ledger.check("") is None
    ledger.record("", result)
    assert ledger.check("") is None


def test_reset_clears_across_turns():
    """跨轮重置后同键不串：生命周期随轮"""
    ledger = IdempotencyLedger()
    ledger.record("k1", ToolResult(success=True, data={"n": 1}))
    assert ledger.check("k1") is not None
    ledger.reset()
    assert ledger.check("k1") is None


def test_distinct_keys_independent():
    """异键互不影响：各自返回各自的首次结果"""
    ledger = IdempotencyLedger()
    r1 = ToolResult(success=True, data={"n": 1})
    r2 = ToolResult(success=False, error="boom")
    ledger.record("a", r1)
    ledger.record("b", r2)
    assert ledger.check("a") is r1
    assert ledger.check("b") is r2
    assert ledger.check("c") is None
