# -*- coding: utf-8 -*-
"""批 6 集成回归：批级检查点+条件回滚（L1 · 高风险批）。

钉死三个场景（缺陷现场 = 取消留半截态）：
① 批内取消留半截态 → 状态回滚到批前快照（GenerationCancelled 照常穿透上抛）；
② 纯状态写批失败 → 回滚；
③ 含外部副作用批（文档写入成功）后续失败 → 不回滚只留痕。

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
