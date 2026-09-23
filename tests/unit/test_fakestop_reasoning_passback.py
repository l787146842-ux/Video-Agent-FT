# -*- coding: utf-8 -*-
"""I1 回流案钉死回归：假停机械续跑分支按门控补带 reasoning_content。

事故（9999 项目，T14/T15 取证）：step 1 已产出符合判据③ 5 个排除面的草拟稿
（220 中文字 / 1 标题行），但它**只存在于 `reasoning_content`**；该轮以
「不含工具调用的纯文本收尾轮」告终 → 触发假停机械续跑，而续跑分支
（`agent_loop.py` L765）**无条件**只 append `content` → **草稿不进 messages**
→ step 2 从零重拟（359 中文字 / 7 标题行）→ 落盘 503 中文字 / 7 标题行。
**真实膨胀 = 503 − 220 = +283 中文字，100% 发生在丢稿之后。**

外部对照组（本缺陷非本仓独有）：DSH 主源码踩过同构 bug 并已修复 ——
`.agents/notes/archived/bug-fix/2026-08-19-deepseek-reasoning-passback-every-turn.zh.md`
自述原适配器「只在同时携带工具调用的 assistant 轮次上，才把 `reasoning_content`
回放进历史」→ 未调工具的纯作答轮到达网关时**不带推理文本**，重建的对话与
记录的对话产生分叉（「Agent 运行的大多数轮次都会调用工具，所以这个损失只在
纯作答轮次上出现，表现为偶发」）。
修复决定 = 对**每个携带推理的 assistant 轮次**都发出 `reasoning_content`，
**与是否有工具调用无关**；**没有推理块时仍然不发出该字段**（非思考轮次行为不变）。

本修复 = 把 `agent_loop.py` L765 补齐到与同文件 FC 分支（L674–L680）**逐字同口径**
（同门控 `settings.llm_reasoning_passthrough`、同 `fc_extra` 取值、同 `.strip()` 判定）。

三形态（对齐 DSH `tests/serialize.spec.ts` 的用例划分）：
  (a) 门控开 + 有 reasoning → 续跑写入的 assistant 消息**带** `reasoning_content`
  (b) 门控开 + 无 reasoning → **不带**该字段（不凭空造空字段）
  (c) 门控关 + 有 reasoning → **不带**该字段（与 FC 分支同口径）

边界（本文件不改动既有断言）：`tests/unit/test_fc_leak_fakestop.py`
L246–L254 只断言 `role` + `content` 子串、该文件 `reasoning_content` 命中 0，
故本修复新增字段**不击穿**其既有断言。
"""
import pytest

from src.video_agent.config import settings
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.state.manager import StateManager

# 与既有假停测试同源的两条前置：Skill 在场（否则策略层不判续跑）
_SKILL = "AI-短剧一站式生成"
_TEXT_1 = "第一批已落账。继续第二批。"
_TEXT_2 = "任务已完成。"


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


@pytest.fixture
def fakestop_on():
    """假停机械续跑开关开（本文件的被测分支必须真被进入）。"""
    original = settings.fakestop_auto_resume_enabled
    object.__setattr__(settings, "fakestop_auto_resume_enabled", True)
    yield
    object.__setattr__(settings, "fakestop_auto_resume_enabled", original)


@pytest.fixture
def gate_on():
    """思考回传门控开（对应 .env 的 LLM_REASONING_PASSTHROUGH=1）。"""
    original = settings.llm_reasoning_passthrough
    object.__setattr__(settings, "llm_reasoning_passthrough", True)
    yield
    object.__setattr__(settings, "llm_reasoning_passthrough", original)


@pytest.fixture
def gate_off():
    """思考回传门控关（config.py 默认 False）。"""
    original = settings.llm_reasoning_passthrough
    object.__setattr__(settings, "llm_reasoning_passthrough", False)
    yield
    object.__setattr__(settings, "llm_reasoning_passthrough", original)


async def _run_resume_once(executor, monkeypatch, *, reasoning):
    """跑一次「假停文本轮 → 机械续跑 → 重申完成」，返回第 2 次 llm_call
    看到的 messages（续跑补链后的形态）。

    `reasoning` = 第 1 轮 llm_call 第 5 元组里的 reasoning_content 取值；
    None 表示该轮 `fc_extra` 不含该键（= 模型本轮没产思考）。
    """
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(
        al, "fallback_skill_from_state", lambda _state: _SKILL)

    fc_extra_1 = {"reasoning_content": reasoning} if reasoning is not None else {}
    seen_messages = []
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        seen_messages.append([dict(m) for m in messages])
        if calls["n"] == 1:
            return _TEXT_1, "stop", 0, 0.0, fc_extra_1
        return _TEXT_2, "stop", 0, 0.0, {}

    result = await run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    # 前置断言：续跑真的发生了（否则本文件的被测分支未被进入，测试无意义）
    assert calls["n"] == 2, f"机械续跑未发生（llm_call 次数={calls['n']}）"
    assert result.steps == 2
    return seen_messages[1]


def _resumed_assistant(messages):
    """取续跑补链写入的 assistant 消息（note 是紧随其后的 user 消息）。"""
    tail = messages[-2:]
    assert tail[0]["role"] == "assistant", "续跑未按预期补入 assistant 消息"
    assert tail[1]["role"] == "user", "续跑未按预期补入提示消息"
    return tail[0]


# ---------- 形态 (a)：门控开 + 有 reasoning → 带字段 ----------


async def test_resume_carries_reasoning_when_gate_on(
        executor, monkeypatch, fakestop_on, gate_on):
    """★ 缺陷复现点：续跑写入的 assistant 消息必须携带 reasoning_content。

    （修复前此断言 FAIL —— L765 无条件只 append content，草稿被丢弃。）
    """
    reasoning = "草拟稿：合规版规格（220 中文字 / 1 标题行）"
    messages = await _run_resume_once(
        executor, monkeypatch, reasoning=reasoning)
    asst = _resumed_assistant(messages)
    assert asst.get("reasoning_content") == reasoning, (
        "假停续跑丢弃了 reasoning_content —— 与同文件 FC 分支 L674–L680 口径不一致"
        "（本仓 9999 事故：合规草稿被丢 → 从零重拟 → +283 中文字膨胀）")


async def test_resume_keeps_content_semantics(
        executor, monkeypatch, fakestop_on, gate_on):
    """口径一致性：`content` 语义不变（仍为 `content or ""`）——只新增字段。"""
    messages = await _run_resume_once(
        executor, monkeypatch, reasoning="思考")
    asst = _resumed_assistant(messages)
    assert asst["content"] == _TEXT_1, "content 语义被改动（应保持 content or ''）"
    assert asst["role"] == "assistant"


# ---------- 形态 (b)：门控开 + 无 reasoning → 不带字段 ----------


async def test_resume_omits_field_when_no_reasoning(
        executor, monkeypatch, fakestop_on, gate_on):
    """无推理块时不发出该字段（不凭空造空字段）——对齐 DSH「没有推理块时
    仍然不发出该字段，因此非思考轮次的行为不变」。"""
    messages = await _run_resume_once(executor, monkeypatch, reasoning=None)
    asst = _resumed_assistant(messages)
    assert "reasoning_content" not in asst, (
        "无 reasoning 时不应发出 reasoning_content 字段（防凭空造空字段）")


async def test_resume_omits_field_when_reasoning_blank(
        executor, monkeypatch, fakestop_on, gate_on):
    """全空白 reasoning 视同无（与 FC 分支 L678 的 `.strip()` 判定同口径）。"""
    messages = await _run_resume_once(executor, monkeypatch, reasoning="   \n  ")
    asst = _resumed_assistant(messages)
    assert "reasoning_content" not in asst, (
        "全空白 reasoning 不应发出该字段（FC 分支 L678 用 .strip() 判定）")


# ---------- 形态 (c)：门控关 → 不带字段 ----------


async def test_resume_omits_field_when_gate_off(
        executor, monkeypatch, fakestop_on, gate_off):
    """门控关（config 默认 False）→ 不带字段，与 FC 分支同口径。"""
    messages = await _run_resume_once(
        executor, monkeypatch, reasoning="思考（门控关时不应外流）")
    asst = _resumed_assistant(messages)
    assert "reasoning_content" not in asst, (
        "门控关闭时不得回传 reasoning_content（默认 off 不外流）")


# ---------- 回归：续跑仍照常发生（本修复不改变控制流） ----------


async def test_resume_control_flow_unchanged(
        executor, monkeypatch, fakestop_on, gate_on):
    """本修复只新增字段，不改控制流：续跑次数/步数/收尾语义不变。"""
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(
        al, "fallback_skill_from_state", lambda _state: _SKILL)

    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _TEXT_1, "stop", 0, 0.0, {"reasoning_content": "思考"}
        return _TEXT_2, "stop", 0, 0.0, {"reasoning_content": "思考 2"}

    result = await run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 2 and result.steps == 2
    # 正文两段齐备（pre-resume 可见文本不丢）——与既有假停测试同断言
    assert _TEXT_1 in (result.text or "") and _TEXT_2 in (result.text or "")
    # 续跑即处置：无按钮
    assert not any(a.get("kind") == "continue" for a in result.suggested_actions)
