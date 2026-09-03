# -*- coding: utf-8 -*-
"""Q22 裁决（2026-09-01）错误恢复校准钉死：
① 止损计数可观测：同工具累计失败次数随时间线条目可见；
② 花钱生成失败不静默：用户可见警告 + 轮级登记 + 轮末机械附一键重试选项卡；
③ 选项卡不叠加：暂停确认轮/已有重试建议不重复附。
（错误留证=结构化回喂、高成本生成前置确认=生成确认闸，均已覆盖免除，见宪法 §2.1 gen_confirm/costly 安全底线。）
"""
import asyncio
import json

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.agent_loop import AgentLoopResult
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.planner_output import append_costly_retry_action
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.tools.base import ToolResult


class _CostlyFailToolManager:
    """image_generate（花钱）必失败；is_costly_tool 按真口径声明。"""

    async def invoke_tool(self, name, args):
        if name == "image_generate":
            return ToolResult(success=False, error="供应商余额不足，生成被拒")
        return ToolResult(success=True, data={})

    def is_costly_tool(self, name):
        return name == "image_generate"


def _gen_response(n_calls: int = 1) -> ChatResponse:
    return ChatResponse(content="", tool_calls=[
        {"id": f"c{i}", "type": "function", "function": {
            "name": "image_generate",
            "arguments": json.dumps({"target": "all_keyElements"})}}
        for i in range(n_calls)
    ])


def _run(runner: FCToolRunner, response: ChatResponse, monkeypatch):
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    tracer = AgentTracer.get_instance()
    tracer.start_trace("q22-test")  # 无活跃 trace 时 record_action 不入队
    tracer.start_step()
    return asyncio.run(runner.execute(response))


def _fail_entries():
    tracer = AgentTracer.get_instance()
    return [
        a for a in tracer._pending_actions
        if a.get("name") == "image_generate" and a.get("ok") is False
    ]


# ---------- ① 止损计数可观测 ----------

def test_fail_count_visible_in_trace_summary(monkeypatch):
    """失败条目：时间线条目摘要携带累计失败次数（止损计数可观测）。
    注：同批首次失败即触发批级回滚中止（既有行为），故跨批观察累计。"""
    runner = FCToolRunner(tool_manager=_CostlyFailToolManager())
    _run(runner, _gen_response(1), monkeypatch)
    fails = _fail_entries()
    assert fails and "累计失败 1 次" in fails[-1]["summary"]


def test_fail_count_accumulates_across_batches(monkeypatch):
    """跨批累积：第二次 execute 的同工具失败计数不归零。"""
    runner = FCToolRunner(tool_manager=_CostlyFailToolManager())
    _run(runner, _gen_response(1), monkeypatch)
    _run(runner, _gen_response(1), monkeypatch)
    fails = _fail_entries()
    # 第二批的失败条目携带跨批累计计数（同 runner 实例；
    # start_trace 重置轮前缓冲，故只断言最新条目）
    assert fails and "累计失败 2 次" in fails[-1]["summary"]


# ---------- ② 花钱生成失败不静默 ----------

def test_costly_failure_user_visible_warning_and_register(monkeypatch):
    """花钱工具失败：用户可见警告随 warnings 上抛 + 轮级登记供轮末选项卡。"""
    runner = FCToolRunner(tool_manager=_CostlyFailToolManager())
    applied, confirmation, *_rest = _run(runner, _gen_response(1), monkeypatch)
    warnings = _rest[6]  # FCExecuteResult.warnings（位置解保兼容面）
    assert any("花钱生成失败" in w for w in warnings)
    assert runner.costly_failures == ["image_generate"]


def test_non_costly_failure_not_registered(monkeypatch):
    """非花钱工具失败：不进轮级登记（选项卡只挂花钱面，不泛滥）。"""

    class _PlainFailTM(_CostlyFailToolManager):
        def is_costly_tool(self, name):
            return False

    runner = FCToolRunner(tool_manager=_PlainFailTM())
    _run(runner, _gen_response(1), monkeypatch)
    assert runner.costly_failures == []


# ---------- ③ 轮末重试选项卡 ----------

def test_append_costly_retry_action_appends():
    """花钱失败且无既有建议 → 附一键重试（机械重发语义）。"""
    r = AgentLoopResult()
    assert append_costly_retry_action(r, ["image_generate"]) is True
    assert r.suggested_actions == [{"kind": "retry", "label": "重试", "value": ""}]


def test_append_costly_retry_skips_on_confirmation():
    """暂停确认轮不叠加（用户在定夺，不双入口干扰）。"""
    r = AgentLoopResult()
    r.confirmation = "请确认生成方案"
    assert append_costly_retry_action(r, ["image_generate"]) is False
    assert r.suggested_actions == []


def test_append_costly_retry_skips_existing_retry():
    """已有重试建议不重复附。"""
    r = AgentLoopResult()
    r.suggested_actions.append({"kind": "retry", "label": "重试", "value": ""})
    assert append_costly_retry_action(r, ["image_generate"]) is False
    assert len(r.suggested_actions) == 1


def test_append_costly_retry_no_failures_noop():
    """无花钱失败 → 零行为变化。"""
    r = AgentLoopResult()
    assert append_costly_retry_action(r, []) is False
    assert r.suggested_actions == []
