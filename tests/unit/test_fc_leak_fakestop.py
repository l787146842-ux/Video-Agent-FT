"""audit-0819 系列钉死回归：

- audit-0819-leak 演化（audit-0819b 协议单轨化；决策史见 git tag adr-archive-20260901）：暂停确认不再合成
  studio-actions 文本块（防泄漏的根治：通道消失则无可泄漏），改经
  结构化第 5 元组上抛；原 strip 清洗断言随通道退役；
- audit-0819-fakestop：模型以延续承诺措辞收尾却零操作/无暂停时，
  轮末策略机械追加「继续」建议动作。
"""
import asyncio

import pytest

from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.round_end_policies import RoundEndContext, run_round_end_policies
from src.video_agent.state.manager import StateManager
from src.video_agent.core.action_executor import StateOperationExecutor


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


async def _noop_emit(event):
    pass


# ---------- audit-0819b：确认不再合成文本块（防泄漏根治） ----------

async def test_planner_does_not_synthesize_action_blocks(svc, executor, monkeypatch):
    """钉死（协议单轨）：_handle_fc_response 不得再合成 studio-actions 块；
    确认经 confirmation_collector 结构化上抛，正文原样返回。"""
    from src.video_agent.adapters.base_chat import ChatResponse
    from src.video_agent.core.planner import Planner

    planner = Planner(state_manager=svc, executor_factory=lambda *a, **k: executor)

    async def _fake_execute(response, **kwargs):
        return (2, "已拆解完毕，请确认", [], [], ["拆解完成"],
                [{"label": "继续下一步", "description": ""}], [], [], [], "")

    monkeypatch.setattr(planner, "_execute_fc_tools", _fake_execute)
    holder = {}
    response = ChatResponse(
        content="拆解完成，请确认。", finish_reason="stop",
        tool_calls=[{"id": "c1", "type": "function",
                     "function": {"name": "workflow_pause", "arguments": "{}"}}],
    )
    content, finish, fc_applied, _results, _warns = await planner._handle_fc_response(
        response, confirmation_collector=holder,
    )
    assert "studio-actions" not in content          # 合成块回归防护：出现即红
    assert content == "拆解完成，请确认。"            # 正文原样返回
    assert holder["message"] == "已拆解完毕，请确认"   # 确认结构化上抛
    assert holder["options"] == [{"label": "继续下一步", "description": ""}]
    # 整改批 1.2b 裁决（历史语义终结）：确认轮返回 execute 解出的真实
    # fc_applied（此处桩值 2），不再硬编 0；暂停轮工具执行事实如实入账
    assert fc_applied == 2


async def test_fc_text_visible_as_is(executor):
    """单轨化：FC 轮正文原样可见（无文本块通道，无需清洗）。"""
    body = "已为你完成本轮操作，故事板已更新。"

    async def llm_call(system_prompt, messages, stream_hook=None):
        return body, "stop", 1, 0.0, {}

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert result.text == body


# ---------- 无效/异常输出处置（单轨化后：正文即用户可见，无解析/重试） ----------


class _StubExec:
    state = {}
    skill_name = "stub-skill"

    def strip_action_blocks(self, text):
        return (text or "").strip()


def _run_policies(ctx):
    return asyncio.run(run_round_end_policies(ctx, _noop_emit))


def test_fakestop_suggests_continue():
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="明白，马上继续！正在调用剧本分析执行器：",
        applied=0,
    )
    _run_policies(ctx)
    assert any(a.get("kind") == "continue" for a in ctx.suggested_actions)


def test_fakestop_label_uses_skill_node_title():
    """任务 12：可判定 Skill 流程节点时，假停「继续」按钮 label 取节点标题。"""
    from src.video_agent.core import workflow_runtime as wr

    wr.clear_compile_cache()
    try:
        definition = wr.compile_definition("AI-短剧一站式生成")
        assert definition is not None, "测试前提：Skill 可编译"
        stub = _StubExec()
        stub.state = {"workflow_run": {
            "run_id": "run_fs", "current_node": "storyboard_shots",
            "definition_hash": definition["definition_hash"],
            "completed_nodes": [], "run_version": 0, "event_sequence": 0,
        }}
        ctx = RoundEndContext(
            step=1, executor=stub, skill="AI-短剧一站式生成",
            content="马上继续推进分镜工作。",
            applied=0,
        )
        _run_policies(ctx)
        cont = [a for a in ctx.suggested_actions if a.get("kind") == "continue"]
        assert cont and cont[0]["label"] == "分镜设计"
        assert cont[0]["value"] == "继续"
    finally:
        wr.clear_compile_cache()


def test_fakestop_skips_without_skill():
    """无 Skill 的普通对话不触发（防误伤闲聊）。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="",
        content="好的，接下来我可以帮你做这些事。",
        applied=0,
    )
    _run_policies(ctx)
    assert not ctx.suggested_actions


def test_fakestop_skips_when_actions_applied():
    """本轮有实际操作不算假停。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="S",
        content="马上继续！正在写入。",
        applied=2,
    )
    _run_policies(ctx)
    assert not ctx.suggested_actions


def test_fakestop_skips_when_paused():
    """已发暂停卡不算假停。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="S",
        content="马上继续，但先确认一下。",
        applied=0, confirmation="请确认",
    )
    _run_policies(ctx)
    assert not ctx.suggested_actions


# ---------- agent_loop 级集成回归（I-1 退役后可达性审计） ----------
# 钉死：轮末工具失败汇总策略退役后，其余策略所需字段在生产唯一
# 构造点（agent_loop 纯文本收尾分支）确被正确填充、可达策略确能触发（非写死死值）。


async def test_agent_loop_pure_text_round_reaches_fakestop(executor, monkeypatch):
    """真实纯文本收尾轮：skill/content/executor 在生产构造点正确填充，
    假停兜底 aborted_continuation_audit 端到端可达并触发（applied=0 因本轮
    确无工具执行，填 result.applied_actions 真实累计值）。"""
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(
        al, "fallback_skill_from_state", lambda _state: "AI-短剧一站式生成")

    body = "明白，马上继续！正在推进后续步骤。"

    async def llm_call(system_prompt, messages, stream_hook=None):
        # 纯文本轮：fc_applied=0、无 confirmation → 落入轮末策略求值分支
        return body, "stop", 0, 0.0, {}

    result = await run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    # 正文经 false_claim_audit 拼接收纳（result_text 路径可达）
    assert result.text == body
    # 假停兜底端到端触发：延续承诺措辞 + skill 激活 + 零操作
    assert any(a.get("kind") == "continue" for a in result.suggested_actions), \
        "纯文本轮末假停兜底未触发（策略所需字段未在生产构造点正确填充/不可达）"


async def test_agent_loop_applied_reflects_real_cumulative_count(executor, monkeypatch):
    """applied 填 result.applied_actions 真实累计值（非写死 0）：第 1 轮 FC
    执行 2 个工具、第 2 轮纯文本收尾带延续承诺措辞——因本回合确曾操作
    （applied=2），假停兜底正确**不**触发（若写死 0 会误触发）。"""
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(
        al, "fallback_skill_from_state", lambda _state: "AI-短剧一站式生成")

    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # FC 工具轮：执行 2 个工具、无正文（工具轮常态）
            return "", "tool_calls", 2, 0.0, {}
        # 纯文本收尾轮：延续承诺措辞（若 applied 写死 0 则会误触发假停）
        return "好的，马上继续推进。", "stop", 0, 0.0, {}

    result = await run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[], max_steps=4,
    )
    assert result.applied_actions == 2
    assert not any(a.get("kind") == "continue" for a in result.suggested_actions), \
        "本回合已执行工具（applied=2），假停兜底不应触发（写死 0 会误触发）"
