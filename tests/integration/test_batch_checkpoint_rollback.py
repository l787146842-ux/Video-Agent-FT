# -*- coding: utf-8 -*-
"""批 6 集成回归：批级检查点+条件回滚（L1 · 高风险批）。

钉死五个场景（缺陷现场 = 取消留半截态 + 评审修复的回滚边界）：
① 批内取消留半截态 → 状态回滚到批前快照（GenerationCancelled 照常穿透上抛）；
② 纯状态写批失败 → 回滚；
③ 含外部副作用批（文档写入成功）后续失败 → 不回滚只留痕；
④ 批内先成功后拒收（闸机拒收/入参校验拒收）→ 不回滚，成功写入保留；
⑤ 执行失败 → 回滚且中止本批后续调用，幂等账本失效（同键重提重新执行）。
另钉修 2 时序：非 high 桩工具写文档成功 + 后续失败 → 不回滚（doc_written 即时记账）。

工具桩经 StateManager.update 写状态（Rule 3 受控写面），风险分级走
既有 get_tool_risk 接口语义，不新造副作用名单。
"""
import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.adapters.cancel_token import GenerationCancelled
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


class _FakeTool:
    def __init__(self, name, risk="low"):
        self.name = name
        self.risk = risk


class _ScriptedToolManager:
    """脚本化工具管理器：提供与 ToolManager 同形的 get_tool/get_tool_risk/
    invoke_tool 接口（风险分级语义对齐 §2.7：未知归 high）。"""

    def __init__(self):
        self._tools = {}
        self._behaviors = {}

    def add(self, tool, behavior):
        self._tools[tool.name] = tool
        self._behaviors[tool.name] = behavior

    def get_tool(self, name):
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' not found.")
        return self._tools[name]

    def get_tool_risk(self, name):
        tool = self._tools.get(name)
        risk = str(getattr(tool, "risk", "") or "").strip().lower() if tool else ""
        return risk if risk in ("low", "medium", "high") else "high"

    async def invoke_tool(self, name, args):
        return await self._behaviors[name](args)


def _batch(*specs):
    return ChatResponse(content="", tool_calls=[
        {"id": f"c{i}", "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}
        for i, (name, args) in enumerate(specs)
    ])


def _assert_state_equals(svc, before):
    """批前/批后整态对照：聊天消息时间戳等不稳定字段除外逐项比对。"""
    now = svc.state_dict
    for key in before:
        if key in ("chatMessages",):
            continue
        assert now.get(key) == before[key], f"状态键 {key} 未按预期回到批前"


# ---------- ① 取消留半截态 → 状态回滚到批前快照 ----------


async def test_cancel_half_state_rolled_back_to_checkpoint(svc):
    """批内先写状态再被取消：半截写入回滚到批前快照，取消异常照常穿透。"""
    before = svc.snapshot_state()

    async def write_group(args):
        svc.update("keyElements", svc.state_dict.get("keyElements", []) + [
            {"id": "g-half", "title": "半截组", "drafts": []}])
        return ToolResult(success=True, data={})

    async def cancel_now(args):
        raise GenerationCancelled("用户停止")

    tm = _ScriptedToolManager()
    # 状态写工具对齐真实分级（写内部状态 = medium，见 storyboard_tools）——
    # 中高危才触发批首检查点，只读批不打快照。
    tm.add(_FakeTool("state_write_med", "medium"), write_group)
    tm.add(_FakeTool("long_task", "low"), cancel_now)
    runner = FCToolRunner(tool_manager=tm)

    with pytest.raises(GenerationCancelled):
        await runner.execute(_batch(("state_write_med", {}), ("long_task", {})))

    assert all(g.get("id") != "g-half"
               for g in svc.state_dict.get("keyElements", [])), "取消留半截态未回滚"
    _assert_state_equals(svc, before)


# ---------- ② 纯状态写批失败 → 回滚 ----------


async def test_pure_state_write_batch_failure_rolled_back(svc):
    """纯状态写工具先写入再报失败：无外部副作用标志 → 回滚到批前快照。"""
    before = svc.snapshot_state()

    async def write_then_fail(args):
        svc.update("shots", svc.state_dict.get("shots", []) + [
            {"id": "s-half", "title": "半截分镜", "drafts": []}])
        return ToolResult(success=False, error="落盘校验失败")

    tm = _ScriptedToolManager()
    tm.add(_FakeTool("state_write_med", "medium"), write_then_fail)
    runner = FCToolRunner(tool_manager=tm)

    result = await runner.execute(_batch(("state_write_med", {})))
    assert result.applied == 0
    assert result.tool_results and result.tool_results[0]["ok"] is False
    assert all(s.get("id") != "s-half"
               for s in svc.state_dict.get("shots", [])), "失败半截态未回滚"
    _assert_state_equals(svc, before)


# ---------- ③ 含外部副作用批失败 → 不回滚只留痕 ----------


async def test_side_effect_batch_failure_keeps_state(svc):
    """批内含 high 风险外部写入（文档写成功）后另一工具失败：
    保守条件命中副作用标志 → 不回滚，已写内容保留（只留痕）。"""
    async def write_doc(args):
        svc.update("documents", svc.state_dict.get("documents", []) + [
            {"id": "doc-keep", "name": "测试文档.md", "content": "正文"}])
        return ToolResult(success=True, data={})

    async def fail_now(args):
        return ToolResult(success=False, error="后续步骤失败")

    tm = _ScriptedToolManager()
    tm.add(_FakeTool("document_write", "high"), write_doc)
    tm.add(_FakeTool("state_write_med", "medium"), fail_now)
    runner = FCToolRunner(tool_manager=tm)

    # high 风险工具需用户一次性同意（与既有测试同口径）
    result = await runner.execute(
        _batch(("document_write", {"name": "测试文档.md"}), ("state_write_med", {})),
        gate_override="all")

    assert result.applied == 1
    assert any(d.get("name") == "测试文档.md"
               for d in svc.state_dict.get("documents", [])), (
        "含外部副作用的批被误回滚——保守条件失效")


# ---------- 接线卫生：无检查点批不受影响 ----------


async def test_low_risk_readonly_batch_no_checkpoint_no_rollback(svc):
    """全 low 风险只读批：不打检查点；失败也不回滚（无半截写入可言）。"""
    before = svc.snapshot_state()

    async def read_fail(args):
        return ToolResult(success=False, error="读取失败")

    tm = _ScriptedToolManager()
    tm.add(_FakeTool("read_only", "low"), read_fail)
    runner = FCToolRunner(tool_manager=tm)

    result = await runner.execute(_batch(("read_only", {})))
    assert result.applied == 0
    _assert_state_equals(svc, before)


# ---------- ④ 拒收不触发回滚（修 1：回滚触发边界） ----------


def _append_ke(svc, gid):
    svc.update("keyElements", svc.state_dict.get("keyElements", []) + [
        {"id": gid, "title": f"组-{gid}", "drafts": []}])


async def test_success_then_validation_rejection_no_rollback(svc):
    """批内先成功写入再遇入参校验型拒收（error_code=validation，从未执行）：
    不回滚，先前成功写入保留（拒收零副作用，与已回喂的成功状态一致）。"""
    async def write_ok(args):
        _append_ke(svc, "g-keep")
        return ToolResult(success=True, data={})

    async def validation_reject(args):
        return ToolResult(
            success=False,
            error="Validation Error: 入参含未知字段（已拒收，未执行）: foo",
            error_code="validation", retryable=False)

    tm = _ScriptedToolManager()
    tm.add(_FakeTool("state_write_med", "medium"), write_ok)
    tm.add(_FakeTool("patch_stub", "medium"), validation_reject)
    runner = FCToolRunner(tool_manager=tm)

    result = await runner.execute(
        _batch(("state_write_med", {}), ("patch_stub", {})))
    assert result.applied == 1
    assert result.tool_results[1]["ok"] is False
    assert any(g.get("id") == "g-keep"
               for g in svc.state_dict.get("keyElements", [])), (
        "入参校验拒收触发了回滚，抹掉了同批先前成功写入")


async def test_success_then_gate_rejection_no_rollback(svc, monkeypatch):
    """批内先成功写入再遇闸机拒收（gate_error，工具体未进入）：不回滚。
    闸机链经 monkeypatch 注入 medium 风险工具的拒因（避开 high 排除条件干扰）。"""
    from src.video_agent.core import fc_gates

    _real_chain = fc_gates.run_gate_chain

    def _chain_with_reject(ctx, name, args, *, paused_this_batch):
        if name == "gate_reject_med":
            return fc_gates.GateChainResult(error="闸机拒收：阶段前置条件不满足")
        return _real_chain(ctx, name, args, paused_this_batch=paused_this_batch)

    monkeypatch.setattr(fc_gates, "run_gate_chain", _chain_with_reject)

    invoked = []

    async def write_ok(args):
        _append_ke(svc, "g-gate-keep")
        return ToolResult(success=True, data={})

    async def should_not_run(args):
        invoked.append("body")
        return ToolResult(success=True, data={})

    tm = _ScriptedToolManager()
    tm.add(_FakeTool("state_write_med", "medium"), write_ok)
    tm.add(_FakeTool("gate_reject_med", "medium"), should_not_run)
    runner = FCToolRunner(tool_manager=tm)

    result = await runner.execute(
        _batch(("state_write_med", {}), ("gate_reject_med", {})))
    assert result.applied == 1
    assert invoked == []  # 闸机拒收：工具体未执行（零副作用）
    assert any(g.get("id") == "g-gate-keep"
               for g in svc.state_dict.get("keyElements", [])), (
        "闸机拒收触发了回滚，抹掉了同批先前成功写入")
    # 拒收后本批仍可继续执行（拒收不中止批：仅回滚才中止）
    assert result.tool_results[1]["ok"] is False


# ---------- ⑤ 执行失败 → 回滚且中止后续调用（修 1 后半） ----------


async def test_failure_rollback_aborts_rest_of_batch(svc):
    """批内先成功后执行失败：回滚抹掉先前写入，且中止本批后续调用（仿问即停：
    不得在已恢复状态上继续执行产生矛盾回喂）。"""
    before = svc.snapshot_state()
    invoked = []

    async def write_ok(args):
        invoked.append("first")
        _append_ke(svc, "g-wiped")
        return ToolResult(success=True, data={})

    async def write_then_fail(args):
        invoked.append("failer")
        _append_ke(svc, "g-half")
        return ToolResult(success=False, error="执行中落盘失败")

    async def should_not_run(args):
        invoked.append("after")
        return ToolResult(success=True, data={})

    tm = _ScriptedToolManager()
    tm.add(_FakeTool("state_write_med", "medium"), write_ok)
    tm.add(_FakeTool("write_fail_med", "medium"), write_then_fail)
    tm.add(_FakeTool("write_after_med", "medium"), should_not_run)
    runner = FCToolRunner(tool_manager=tm)

    result = await runner.execute(_batch(
        ("state_write_med", {}), ("write_fail_med", {}), ("write_after_med", {})))
    assert "after" not in invoked  # 回滚发生后本批后续调用中止（未执行）
    assert all(g.get("id") not in ("g-wiped", "g-half")
               for g in svc.state_dict.get("keyElements", [])), "回滚未抹掉半截写入"
    assert result.applied == 1
    assert len(result.tool_results) == 2  # 失败后中止：第三个调用无回喂条目
    _assert_state_equals(svc, before)


# ---------- 修 2：doc_written 判定时序（即时记账） ----------


def _append_doc(svc, name):
    svc.update("documents", svc.state_dict.get("documents", []) + [
        {"id": f"doc-{name}", "name": name, "content": "正文"}])


async def test_nonhigh_doc_write_then_failure_no_rollback(svc):
    """修 2 时序回归：非 high 桩工具（medium）写文档成功 + 后续执行失败：
    判定点读得到文档写标志 → 不回滚，文档保留（若批末才赋值则误回滚）。"""
    async def write_doc(args):
        _append_doc(svc, "时序文档.md")
        return ToolResult(success=True, data={})

    async def fail_now(args):
        return ToolResult(success=False, error="后续步骤失败")

    tm = _ScriptedToolManager()
    # 两个工具均非 high：若账本缺文档写标志，保守条件会放行回滚 → 误抹文档
    tm.add(_FakeTool("document_write", "medium"), write_doc)
    tm.add(_FakeTool("state_write_med", "medium"), fail_now)
    runner = FCToolRunner(tool_manager=tm)

    result = await runner.execute(
        _batch(("document_write", {"name": "时序文档.md"}), ("state_write_med", {})))
    assert result.applied == 1
    assert any(d.get("name") == "时序文档.md"
               for d in svc.state_dict.get("documents", [])), (
        "doc_written 时序缺口复发：判定点读不到文档写标志导致误回滚")
    assert result.docs_written == ["时序文档.md"]


# ---------- 修 4：回滚后失效轮内幂等账本 ----------


async def test_rollback_resets_idempotency_ledger(svc):
    """回滚实际发生 → 轮内幂等账本失效：同键重提不命中陈旧成功缓存，重新执行补写。"""
    calls = {"n": 0}

    async def write_ok(args):
        calls["n"] += 1
        _append_ke(svc, f"g-idem-{calls['n']}")
        return ToolResult(success=True, data={})

    async def fail_once_then_ok(args):
        # 首次失败触发回滚；第二批不再失败（行为按调用次数脚本化）
        if calls["n"] == 1:
            return ToolResult(success=False, error="首次执行失败")
        return ToolResult(success=True, data={})

    tm = _ScriptedToolManager()
    tm.add(_FakeTool("state_write_med", "medium"), write_ok)
    tm.add(_FakeTool("write_fail_med", "medium"), fail_once_then_ok)
    runner = FCToolRunner(tool_manager=tm)

    # 批 1：键 k1 写成功 → 后续失败触发回滚（账本失效）
    r1 = await runner.execute(_batch(
        ("state_write_med", {"idempotency_key": "k1"}),
        ("write_fail_med", {})))
    assert r1.applied == 1
    assert all(g.get("id") != "g-idem-1"
               for g in svc.state_dict.get("keyElements", []))
    # 批 2（同一轮）：同键重提若命中陈旧缓存则不会补写；失效后应重新执行
    r2 = await runner.execute(_batch(
        ("state_write_med", {"idempotency_key": "k1"})))
    assert r2.applied == 1
    assert calls["n"] == 2  # 未命中陈旧成功缓存：真实补写发生
    assert any(g.get("id") == "g-idem-2"
               for g in svc.state_dict.get("keyElements", [])), (
        "回滚后同键命中陈旧成功缓存，写入被回滚却永不补写")
