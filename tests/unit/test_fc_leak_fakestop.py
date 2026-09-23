"""audit-0819 系列钉死回归：

- audit-0819-leak 演化（audit-0819b 协议单轨化；决策史见 git tag adr-archive-20260901）：暂停确认不再合成
  studio-actions 文本块（防泄漏的根治：通道消失则无可泄漏），改经
  结构化第 5 元组上抛；原 strip 清洗断言随通道退役；
- audit-0819-fakestop（2026-09-14 词表退役批）：Skill 进行中的纯文本收尾轮
  结构性机械续跑（dsh Stop hook 同款）——连续第 1 轮机械续跑注入 note、
  连续第 2 轮视为真完成放行、工具轮归零 streak、cap 封死「文本↔工具」拉锯。
  词表匹配整体退役（1111 实证 5 种句式全漏网）。
"""
import asyncio

import pytest

from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.round_end_policies import (
    FAKESTOP_AUTO_RESUME_MAX,
    RoundEndContext,
    run_round_end_policies,
)
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


# ---------- 假停机械续跑：策略层单元（结构性判定，无词表） ----------


class _StubExec:
    state = {}
    skill_name = "stub-skill"

    def strip_action_blocks(self, text):
        return (text or "").strip()


def _run_policies(ctx):
    return asyncio.run(run_round_end_policies(ctx, _noop_emit))


@pytest.fixture
def resume_on():
    """开关开（frozen settings 定点突破 + 还原；默认已是开，钉死显式形态）。"""
    from src.video_agent.config import settings
    original = settings.fakestop_auto_resume_enabled
    object.__setattr__(settings, "fakestop_auto_resume_enabled", True)
    yield
    object.__setattr__(settings, "fakestop_auto_resume_enabled", original)


@pytest.fixture
def resume_off():
    """开关关：无检测语义（dsh 默认不配 hook 的放手形态）。"""
    from src.video_agent.config import settings
    original = settings.fakestop_auto_resume_enabled
    object.__setattr__(settings, "fakestop_auto_resume_enabled", False)
    yield
    object.__setattr__(settings, "fakestop_auto_resume_enabled", original)


def test_resume_marks_continue_turn_on_first_text_round(resume_on):
    """连续第 1 轮纯文本收尾（streak=0）+ Skill 激活 → 机械续跑标记。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="5 位主角已落账。继续第二批：3 位船员。",
        applied=0, resumes_used=0, text_round_streak=0,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is True
    assert not ctx.suggested_actions, "续跑即处置，无按钮（词表退役批）"


def test_second_consecutive_text_round_passes_through(resume_on):
    """连续第 2 轮纯文本（streak≥1）= 模型已按 note 重申完成 → 真完成放行。"""
    ctx = RoundEndContext(
        step=2, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="任务已完成。",
        applied=0, resumes_used=1, text_round_streak=1,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is False


def test_resume_disabled_no_detection(resume_off):
    """开关关：不做任何检测（无续跑标记、无按钮）。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="继续第二批：3 位船员。",
        applied=0, resumes_used=0, text_round_streak=0,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is False
    assert not ctx.suggested_actions


def test_resume_skips_without_skill(resume_on):
    """无 Skill 的普通对话不触发（防误伤闲聊）。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="",
        content="好的，接下来我可以帮你做这些事。",
        applied=0, resumes_used=0, text_round_streak=0,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is False


def test_resume_skips_when_paused(resume_on):
    """已发暂停卡不算假停（确认卡优先于续跑）。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="先确认一下。",
        applied=0, resumes_used=0, text_round_streak=0,
        confirmation="请确认",
    )
    _run_policies(ctx)
    assert ctx.continue_turn is False


def test_resume_skips_at_cap(resume_on):
    """达上限（resumes_used=MAX）：不再续跑（cap 封死交替拉锯），无按钮。"""
    ctx = RoundEndContext(
        step=3, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="继续：3 位船员。",
        applied=0, resumes_used=FAKESTOP_AUTO_RESUME_MAX, text_round_streak=0,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is False
    assert not ctx.suggested_actions


# ---------- K6 批：R6 子代理结构豁免退役（depth>0 同受机械续跑口径） ----------


def test_resume_fires_when_subagent_depth_positive(resume_on):
    """K6 批（R6 豁免退役）：subagent_depth=1 + Skill 模式 + streak=0 →
    闸机同口径续跑。子代理收尾改由 structured_output 打卡判定
    （完成=一次工具调用），纯文本收尾轮不再结构豁免（cap=2 封死拉锯）。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="子代理完成了第一批。",
        applied=0, resumes_used=0, text_round_streak=0,
        subagent_depth=1,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is True, "R6 退役：depth>0 同受机械续跑口径"


def test_resume_fires_when_subagent_depth_zero(resume_on):
    """R6 对照组：subagent_depth=0 + 相同条件 → 闸机续跑（确认主代理行为不变）。"""
    ctx = RoundEndContext(
        step=1, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="主代理完成了第一批。",
        applied=0, resumes_used=0, text_round_streak=0,
        subagent_depth=0,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is True, "主代理（depth=0）应触发续跑"


# ---------- 2026-09-22 批2（Q4.4）：打卡感知（不再空转两轮） ----------


def test_resume_skips_when_structured_captured(resume_on):
    """打卡成功 ⇒ 已完工，不得再判假停续跑（事故：子代理打完卡空转两轮）。

    实跑取证（4411 项目 conv-1790074054-f0e43ab0）：seq=88 打卡成功 →
    seq=93 又 1171 字 → seq=96 又 789 字，白烧 9s 并产出两份重复汇报。
    打卡轮本身就是零工具调用轮，无本标记必被旧条件误判。
    """
    ctx = RoundEndContext(
        step=6, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="22 个 shot 组全部落账核验通过。完成打卡：",
        applied=0, resumes_used=0, text_round_streak=0,
        subagent_depth=1, structured_captured=True,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is False, "已打卡不得续跑（Q4.4 事故根因）"


def test_resume_still_fires_without_capture(resume_on):
    """反向钉（防「一律不续跑」式假修）：子代理**没打卡**的纯文本收尾轮
    仍受续跑约束——否则子代理可少干活不交差（静默欠交付）。"""
    ctx = RoundEndContext(
        step=3, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="我先看看接下来做什么。",
        applied=0, resumes_used=0, text_round_streak=0,
        subagent_depth=1, structured_captured=False,
    )
    _run_policies(ctx)
    assert ctx.continue_turn is True, "未打卡的子代理仍须被续跑约束"


def test_resume_skips_capture_even_at_streak_zero(resume_on):
    """打卡优先于 streak 语义：打卡轮恒不续跑（不依赖连续轮计数）。"""
    for streak in (0, 1, 2):
        ctx = RoundEndContext(
            step=1, executor=_StubExec(), skill="AI-短剧一站式生成",
            content="完成汇报。",
            applied=0, resumes_used=0, text_round_streak=streak,
            structured_captured=True,
        )
        _run_policies(ctx)
        assert ctx.continue_turn is False, f"streak={streak} 打卡后仍续跑了"


# ---------- 2026-09-22 批3（Q4.3）：可见正文累积口径（子代理取末条） ----------


def test_accumulate_visible_main_agent_concatenates():
    """主代理：各步正文按序拼接（现状不变，防误伤主对话多段叙述）。"""
    from src.video_agent.core.round_end_policies import accumulate_visible

    out = accumulate_visible("第一步：登记完成。", "第二步：开始拆镜。", last_only=False)
    assert out == "第一步：登记完成。\n\n第二步：开始拆镜。"


def test_accumulate_visible_subagent_keeps_last_only():
    """子代理：只取最后一条非空正文（dsh assistant-output.ts 同规则）。

    4411 实跑：拼接曾把摘要吹到 2980 字（4 段近义汇报）；取末条 → 单段。
    """
    from src.video_agent.core.round_end_policies import accumulate_visible

    acc = ""
    for seg in ("已读取剧本。", "建组入参键序有要求，重建 4 组：", "22 组全部落账核验通过。"):
        acc = accumulate_visible(acc, seg, last_only=True)
    assert acc == "22 组全部落账核验通过。"
    assert "已读取剧本" not in acc, "子代理摘要不得残留中间步叙述"


def test_accumulate_visible_empty_step_keeps_previous():
    """空步不覆盖已有正文（防「末条」被空串清空）。"""
    from src.video_agent.core.round_end_policies import accumulate_visible

    assert accumulate_visible("有内容", "   ", last_only=True) == "有内容"
    assert accumulate_visible("有内容", "", last_only=True) == "有内容"
    assert accumulate_visible("", "首条", last_only=True) == "首条"


def test_false_claim_audit_applies_subagent_last_only():
    """轮末策略腿同口径：子代理轮取末条，主代理轮拼接（两腿不得各写一遍）。"""
    ctx_sub = RoundEndContext(
        step=2, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="末条汇报。", applied=0, subagent_depth=1,
    )
    ctx_sub.result_text = "中间叙述。"
    _run_policies(ctx_sub)
    assert ctx_sub.result_text == "末条汇报。"

    ctx_main = RoundEndContext(
        step=2, executor=_StubExec(), skill="AI-短剧一站式生成",
        content="末条汇报。", applied=0, subagent_depth=0,
    )
    ctx_main.result_text = "中间叙述。"
    _run_policies(ctx_main)
    assert ctx_main.result_text == "中间叙述。\n\n末条汇报。"


# ---------- agent_loop 级集成回归（生产构造点字段可达性） ----------


async def test_agent_loop_resume_then_restate_completes(executor, monkeypatch, resume_on):
    """端到端：假停文本轮 → 机械续跑（note 注入）→ 模型重申完成 → 放行收尾。
    钉死三件事：续跑发生（steps=2）、对话链完整（assistant 原文 + note
    进 messages）、result.text 两段齐备且无按钮。"""
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(
        al, "fallback_skill_from_state", lambda _state: "AI-短剧一站式生成")

    seen_messages = []
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        seen_messages.append([dict(m) for m in messages])
        if calls["n"] == 1:
            return "5 位主角已落账。继续第二批：3 位船员。", "stop", 0, 0.0, {}
        return "任务已完成。", "stop", 0, 0.0, {}

    result = await run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 2 and result.steps == 2
    # 对话链：第 2 轮 messages 尾部 = 第 1 轮 assistant 原文 + 机械提醒
    tail = seen_messages[1][-2:]
    assert tail[0]["role"] == "assistant" and "继续第二批" in tail[0]["content"]
    assert tail[1]["role"] == "user" and "未包含任何工具调用" in tail[1]["content"]
    # 正文两段齐备（pre-resume 可见文本不丢）
    assert "继续第二批" in (result.text or "") and "任务已完成" in (result.text or "")
    # 续跑即处置：无按钮
    assert not any(a.get("kind") == "continue" for a in result.suggested_actions)


async def test_agent_loop_tool_round_resets_streak(executor, monkeypatch, resume_on):
    """工具轮归零 streak：假停→续跑→工具→假停→续跑→重申完成→放行。
    全程两次续跑（未达 cap），applied 累计 3。"""
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(
        al, "fallback_skill_from_state", lambda _state: "AI-短剧一站式生成")

    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return "", "tool_calls", 2, 0.0, {}      # FC 批轮
        if calls["n"] == 2:
            return "继续下一批。", "stop", 0, 0.0, {}   # 假停 #1 → 续跑
        if calls["n"] == 3:
            return "", "tool_calls", 1, 0.0, {}      # 工具轮归零 streak
        if calls["n"] == 4:
            return "写完这批了。", "stop", 0, 0.0, {}   # 假停 #2 → 续跑
        return "任务已完成。", "stop", 0, 0.0, {}      # 连续第 2 轮 → 放行

    result = await run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 5 and result.steps == 5
    assert result.applied_actions == 3
    assert not any(a.get("kind") == "continue" for a in result.suggested_actions)


async def test_agent_loop_resume_cap_two_then_pass(executor, monkeypatch, resume_on):
    """cap 封顶：续跑×2 后第三轮纯文本直接放行（无按钮兜底，词表退役批）。"""
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(
        al, "fallback_skill_from_state", lambda _state: "AI-短剧一站式生成")

    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        if calls["n"] in (1, 3, 5):
            return f"继续：这是第 {calls['n']} 轮。", "stop", 0, 0.0, {}
        return "", "tool_calls", 1, 0.0, {}          # FC 轮归零 streak

    result = await run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 5 and result.steps == 5
    assert not any(a.get("kind") == "continue" for a in result.suggested_actions)


async def test_agent_loop_resume_disabled_single_text_round_ends(
        executor, monkeypatch, resume_off):
    """开关关：纯文本收尾轮一轮即收尾（现状语义，无检测）。"""
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(
        al, "fallback_skill_from_state", lambda _state: "AI-短剧一站式生成")

    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return "任务已完成。", "stop", 0, 0.0, {}

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1 and result.steps == 1
    assert "任务已完成" in (result.text or "")
