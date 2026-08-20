"""audit-0819 系列钉死回归：

- audit-0819-leak 演化（audit-0819b 单轨化，ADR-0001）：暂停确认不再合成
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
from src.video_agent.web.action_executor import StudioActionExecutor


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StudioActionExecutor(svc)


async def _noop_emit(event):
    pass


# ---------- audit-0819b：确认不再合成文本块（防泄漏根治） ----------

async def test_planner_does_not_synthesize_action_blocks(svc, executor, monkeypatch):
    """钉死（ADR-0001）：_handle_fc_response 不得再合成 studio-actions 块；
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
    assert fc_applied == 0                          # 确认轮不计 applied（历史语义保持）


async def test_fc_text_visible_as_is(executor):
    """单轨化：FC 轮正文原样可见（无文本块通道，无需清洗）。"""
    body = "已为你完成本轮操作，故事板已更新。"

    async def llm_call(system_prompt, messages, stream_hook=None):
        return body, "stop", 1, 0.0

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
        applied=0, total_exec=0,
    )
    _run_policies(ctx)
    assert any(a.get("kind") == "continue" for a in ctx.suggested_actions)


def test_fakestop_skips_without_skill():
    """无 Skill 的普通对话不触发（防误伤闲聊）。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="",
        content="好的，接下来我可以帮你做这些事。",
        applied=0, total_exec=0,
    )
    _run_policies(ctx)
    assert not ctx.suggested_actions


def test_fakestop_skips_when_actions_applied():
    """本轮有实际操作不算假停。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="S",
        content="马上继续！正在写入。",
        applied=2, total_exec=2,
    )
    _run_policies(ctx)
    assert not ctx.suggested_actions


def test_fakestop_skips_when_paused():
    """已发暂停卡不算假停。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="S",
        content="马上继续，但先确认一下。",
        applied=0, total_exec=0, confirmation="请确认",
    )
    _run_policies(ctx)
    assert not ctx.suggested_actions
