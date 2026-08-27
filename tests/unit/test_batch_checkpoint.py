"""批 6 · 批级检查点+条件回滚：保守条件矩阵与回滚卫生（core/batch_checkpoint.py）。

钉死三件事：
① should_rollback 白名单式保守条件：仅当失败/取消且无任何外部副作用标志
   （high 风险工具/生成族成败/文档写入）才允许回滚；
② 快照/恢复经 StateManager 受控写面（整态深拷贝、恢复留 undo 痕迹）；
③ 检查点失败与回滚自身失败都只记日志，不向主链路二次抛出。
"""
import copy

import pytest

from src.video_agent.core import batch_checkpoint as bc
from src.video_agent.core.fc_reconcile import BatchLedger
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult


# ---------- 风险分级桩（不新造名单：只模拟 ToolManager.get_tool_risk 接口） ----------


class _RiskStub:
    def __init__(self, risks):
        self._risks = dict(risks)

    def get_tool_risk(self, name):
        return self._risks.get(name, "high")


class _NoRiskCapability:
    """缺 get_tool_risk 能力的桩（测试侧极简 stub 的真实形态）。"""


class _FakeSvc:
    """快照/恢复受控写面桩（记录调用，供回滚卫生断言）。"""

    def __init__(self, state=None, restore_error=None):
        self.state = state if state is not None else {"keyElements": [], "marker": "pre"}
        self.restore_error = restore_error
        self.restore_refuse = False
        self.restored = []

    def snapshot_state(self):
        return copy.deepcopy(self.state)

    def restore_snapshot(self, snapshot):
        if self.restore_error is not None:
            raise self.restore_error
        self.restored.append(snapshot)
        self.state = copy.deepcopy(snapshot)
        if self.restore_refuse:
            return False  # 版本闸放弃落盘：内存已回滚、磁盘未落
        return True


def _response(*names):
    class _Resp:
        tool_calls = [
            {"id": f"c{i}", "function": {"name": n, "arguments": "{}"}}
            for i, n in enumerate(names)
        ]
    return _Resp()


# ---------- should_rollback 保守条件矩阵 ----------


@pytest.mark.parametrize("gen_succeeded,gen_failed_err,doc_written,docs_written", [
    (False, "", False, []),
    (True, "", False, []),
    (False, "生成任务已被取消", False, []),
    (False, "", True, []),
    (False, "", False, ["制片规格.md"]),
])
@pytest.mark.parametrize("tools,expected", [
    (["state_write_low"], True),        # 无副作用标志 → 回滚
    (["state_write_low", "canvas_write"], False),  # high 风险工具 → 排除
    ([], True),                          # 空批（无工具痕迹）也按白名单放行
])
def test_should_rollback_matrix(tools, expected, gen_succeeded, gen_failed_err,
                                doc_written, docs_written):
    """失败/取消 × 有/无副作用标志全组合：副作用判定只认既有数据源。"""
    risks = {"state_write_low": "low", "canvas_write": "high"}
    got = bc.should_rollback(
        failed=True, tool_names=tools, gen_succeeded=gen_succeeded,
        gen_failed_err=gen_failed_err, doc_written=doc_written,
        docs_written=docs_written, tool_manager=_RiskStub(risks))
    has_side_effect = gen_succeeded or gen_failed_err or doc_written or any(docs_written) \
        or "canvas_write" in tools
    assert got == (expected and not has_side_effect)


def test_should_rollback_success_batch_never_rolls_back():
    """批成功（未失败/未取消）一律不回滚——无论有无副作用标志。"""
    assert bc.should_rollback(failed=False, tool_names=["state_write_low"]) is False
    assert bc.should_rollback(
        failed=False, tool_names=["canvas_write"], gen_succeeded=True,
        tool_manager=_RiskStub({"canvas_write": "high"})) is False


def test_should_rollback_unregistered_tool_defaults_high():
    """未注册工具经既有 ToolManager.get_tool_risk 归 high（deny-by-default）→ 排除。"""
    assert bc.should_rollback(
        failed=True, tool_names=["definitely_not_registered_xyz"]) is False


def test_should_rollback_medium_risk_allows_rollback():
    """medium 风险（纯状态写）不视为外部副作用——白名单只排除 high。"""
    assert bc.should_rollback(
        failed=True, tool_names=["storyboard_write"],
        tool_manager=_RiskStub({"storyboard_write": "medium"})) is True


def test_should_rollback_stub_without_risk_capability_excludes():
    """风险查询能力缺失（测试桩/异常）一律保守归 high → 不回滚。"""
    assert bc.should_rollback(
        failed=True, tool_names=["whatever"], tool_manager=_NoRiskCapability()) is False
    assert bc.should_rollback(
        failed=True, tool_names=["whatever"],
        tool_manager=_RiskStubBroken()) is False


class _RiskStubBroken:
    def get_tool_risk(self, name):
        raise RuntimeError("注册表异常")


# ---------- 回滚触发边界：未执行型拒收判定（修 1） ----------


def test_is_unexecuted_rejection_gate_error():
    """闸机拒收（gate_error 非 None）从未执行 → 不触发回滚判定。"""
    ok_result = ToolResult(success=True, data={})
    fail_result = ToolResult(success=False, error="任意失败")
    assert bc.is_unexecuted_rejection("风险工具需确认", ok_result) is True
    assert bc.is_unexecuted_rejection("阶段前置不满足", fail_result) is True


def test_is_unexecuted_rejection_validation_code():
    """入参校验型拒收（error_code=validation：未知字段/白名单/格式非法）零副作用。"""
    rejected = ToolResult(success=False, error="Validation Error: 未知字段",
                          error_code="validation", retryable=False)
    assert bc.is_unexecuted_rejection(None, rejected) is True


def test_is_unexecuted_rejection_executed_failure_not_excluded():
    """确实执行过且失败的结果（未标注/非 validation 码）仍进回滚判定。"""
    plain = ToolResult(success=False, error="落盘失败")
    upstream = ToolResult(success=False, error="供应商失败",
                          error_code="upstream", retryable=True)
    assert bc.is_unexecuted_rejection(None, plain) is False
    assert bc.is_unexecuted_rejection(None, upstream) is False
    # 非 ToolResult 结果（测试 stub）不崩且不豁免（保守：进判定）
    assert bc.is_unexecuted_rejection(None, object()) is False


# ---------- 批首检查点触发条件与批内工具名提取 ----------


def test_batch_tool_names_extracts_and_skips_invalid():
    resp = _response("a_tool", "b_tool")
    resp.tool_calls.append({"id": "c9", "function": {"name": ""}})
    resp.tool_calls.append("not-a-dict")
    assert bc.batch_tool_names(resp) == ["a_tool", "b_tool"]
    assert bc.batch_tool_names(object()) == []


def test_batch_has_risky_tool_trigger_condition():
    stub = _RiskStub({"read_only": "low", "state_write": "medium", "canvas_write": "high"})
    assert bc.batch_has_risky_tool(_response("read_only"), stub) is False
    assert bc.batch_has_risky_tool(_response("read_only", "state_write"), stub) is True
    assert bc.batch_has_risky_tool(_response("canvas_write"), stub) is True
    # 无风险查询能力 → 保守视为含高危（宁可多打检查点）
    assert bc.batch_has_risky_tool(_response("mystery"), _NoRiskCapability()) is True


def test_take_checkpoint_returns_deep_snapshot():
    svc = _FakeSvc()
    snap = bc.take_checkpoint(svc)
    assert snap == svc.state and snap is not svc.state
    snap["keyElements"].append({"id": "x"})
    assert svc.state["keyElements"] == []  # 深拷贝：改快照不污染内态


def test_take_checkpoint_failure_returns_none_not_raise():
    class _Broken:
        def snapshot_state(self):
            raise RuntimeError("快照失败")
    assert bc.take_checkpoint(_Broken()) is None


# ---------- maybe_rollback：保守条件执行 + 回滚卫生 ----------


def test_maybe_rollback_restores_when_clean():
    svc = _FakeSvc()
    snap = svc.snapshot_state()
    svc.state["marker"] = "half"
    ledger = BatchLedger()
    ok = bc.maybe_rollback(
        svc, snap, failed_tool="state_write_low", ledger=ledger,
        tool_names=["state_write_low"],
        tool_manager=_RiskStub({"state_write_low": "low"}))
    assert ok is True
    assert svc.state["marker"] == "pre"
    assert svc.restored  # 恢复确实经受控写面执行


def test_maybe_rollback_blocked_by_side_effects_only_leaves_trace():
    svc = _FakeSvc()
    snap = svc.snapshot_state()
    svc.state["marker"] = "half"
    ledger = BatchLedger(gen_succeeded=True)
    ok = bc.maybe_rollback(
        svc, snap, failed_tool="next_tool", ledger=ledger,
        tool_names=["long_task", "next_tool"],
        tool_manager=_RiskStub({"long_task": "low", "next_tool": "low"}))
    assert ok is False
    assert svc.state["marker"] == "half"  # 不回滚：保留现场只留痕（生成已成功）
    assert svc.restored == []


def test_maybe_rollback_blocked_by_high_risk_tool_in_batch():
    """批内含 high 风险工具（画布写等外部副作用通道）→ 即使未记成败也不回滚。"""
    svc = _FakeSvc()
    snap = svc.snapshot_state()
    svc.state["marker"] = "half"
    ok = bc.maybe_rollback(
        svc, snap, failed_tool="next_tool", ledger=BatchLedger(),
        tool_names=["canvas_write", "next_tool"],
        tool_manager=_RiskStub({"canvas_write": "high", "next_tool": "low"}))
    assert ok is False and svc.state["marker"] == "half"
    assert svc.restored == []


def test_maybe_rollback_without_snapshot_is_noop():
    svc = _FakeSvc()
    assert bc.maybe_rollback(svc, None, failed_tool="t", tool_names=["t"]) is False
    assert svc.restored == []


def test_maybe_rollback_failure_logs_and_does_not_reraise():
    """回滚自身失败只记日志不二次抛出（半截态现场不得被回滚异常掩盖）。"""
    svc = _FakeSvc(restore_error=RuntimeError("落盘闸拒绝"))
    snap = svc.snapshot_state()
    ok = bc.maybe_rollback(svc, snap, failed_tool="t", tool_names=["t"],
                           tool_manager=_RiskStub({"t": "low"}))
    assert ok is False  # 静默返回，未抛出


def test_maybe_rollback_restore_refused_by_version_gate_reports_false():
    """修 3：restore_snapshot 返回 False（save() 被版本闸放弃落盘）时不得虚报成功：
    内存已回滚、磁盘未落 → 记 warning 并返回 False（接线点按未回滚处置）。"""
    svc = _FakeSvc()
    svc.restore_refuse = True  # 模拟版本闸放弃：内态已换、落盘被拒返回 False
    snap = svc.snapshot_state()
    svc.state["marker"] = "half"
    ok = bc.maybe_rollback(svc, snap, failed_tool="t", tool_names=["t"],
                           tool_manager=_RiskStub({"t": "low"}))
    assert ok is False
    assert svc.restored  # restore_snapshot 确实被调用过（失败来自落盘闸而非未执行）


def test_maybe_rollback_on_cancel_uses_cancelled_semantics():
    svc = _FakeSvc()
    snap = svc.snapshot_state()
    svc.state["marker"] = "half"
    ok = bc.maybe_rollback_on_cancel(
        svc, snap, cancelled_tool="long_task", ledger=BatchLedger(),
        tool_names=["long_task"], tool_manager=_RiskStub({"long_task": "low"}))
    assert ok is True
    assert svc.state["marker"] == "pre"


# ---------- StateManager 快照/恢复公开 API（Rule 3 受控写面） ----------


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def test_state_manager_snapshot_is_deep_copy(svc):
    snap = svc.snapshot_state()
    snap.setdefault("keyElements", []).append({"id": "ghost"})
    assert all(g.get("id") != "ghost"
               for g in svc.state_dict.get("keyElements", []))


def test_state_manager_restore_writes_back_with_undo_trail(svc):
    snap = svc.snapshot_state()
    svc.update("keyElements", [{"id": "g1", "title": "半截组", "drafts": []}])
    assert any(g.get("id") == "g1" for g in svc.state_dict["keyElements"])
    assert svc.restore_snapshot(snap) in (True, False)  # 落盘结果不抛
    assert all(g.get("id") != "g1"
               for g in svc.state_dict.get("keyElements", []))
    # undo 留痕：恢复本身可被 undo 复核（回到半截态）
    assert svc.can_undo is True
    svc.undo()
    assert any(g.get("id") == "g1" for g in svc.state_dict["keyElements"])
