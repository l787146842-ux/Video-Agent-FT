"""audit-0819 两项 P0 修复的钉死回归：

- audit-0819-leak：FC 轨正文必须经 strip_action_blocks 清洗（双轨一致，Rule 2），
  studio-actions 块不得泄漏进用户可见正文；
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


# ---------- audit-0819-leak：FC 轨正文清洗 ----------

async def test_fc_track_strips_action_blocks(executor):
    """FC 分支（fc_applied>0）返回的正文含 studio-actions 块时必须被剥离。"""
    body = "已为你完成本轮操作，故事板已更新。"
    leaked = (
        body
        + '\n```studio-actions\n[{"action":"request_confirmation","message":"请确认"}]\n```'
    )

    async def llm_call(system_prompt, messages, stream_hook=None):
        return leaked, "stop", 1, 0.0  # fc_applied=1 → 走 FC 分支

    result = await run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert body in result.text
    assert "studio-actions" not in result.text
    assert "request_confirmation" not in result.text


async def test_fc_track_clean_content_unchanged(executor):
    """干净正文经清洗为恒等变换（strip 语义），不丢字。"""
    body = "普通回复，无任何动作块。"

    async def llm_call(system_prompt, messages, stream_hook=None):
        return body, "stop", 1, 0.0

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert result.text.strip() == body


async def test_text_track_strips_action_blocks(executor):
    """文本轨同一内容同样不泄漏（双轨一致断言）。"""
    body = "暂停前说明。"
    content = (
        body
        + '\n```studio-actions\n[{"action":"request_confirmation","message":"请确认"}]\n```'
    )

    async def llm_call(system_prompt, messages, stream_hook=None):
        return content, "stop", 0  # fc_applied=0 → 文本轨

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert "studio-actions" not in result.text
    assert body in result.text
    # request_confirmation 被解析为暂停信号
    assert result.confirmation


# ---------- 无效动作块处置（4-4 双轨退役后：拒因重试自愈环已删，直接丢弃告警） ----------

async def test_invalid_action_block_dropped_with_warning(executor):
    """无效 studio-actions 块：不执行、不重试，丢弃并告警（ADR-0001）。"""
    bad = ('正文\n```studio-actions\n[invalid json\n```', "stop")
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return bad[0], bad[1], 0

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1, "拒因重试已随 4-4 退役删除，不得额外烧轮次"
    assert result.applied_actions == 0
    assert any("解析失败" in w for w in result.warnings)


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
