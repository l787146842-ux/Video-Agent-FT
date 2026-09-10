# -*- coding: utf-8 -*-
"""完成盖章批（dsh A2：完成必须显式盖章 + 未盖章不放行 + 按证据汇报）回归。

钉死：
① 盖章回执 = 客观账本快照（纯事实，不判真假）；未激活 Skill 不参与阶段判定；
② task_complete 发行：runner 冻结本批（排在其后的调用不执行）+ 回喂数据带章；
③ 轮末闸机 completion_stamp_gate：零动作未盖章收尾 → 不受理并给事实回喂；
   已盖章 / 无 Skill / 预算耗尽 三种情形不续跑（预算耗尽改出事实警告）；
④ agent_loop 端到端：纯口头收尾确实续跑一步，二次仍口头 → 收尾带未完成阶段警告；
   盖章则一步即收，且无正文时用章的 summary 作可见正文；
⑤ 总开关关 = task_complete 不下发、两条轮末策略失效。
"""
import asyncio
import json

import pytest

from src.video_agent.config import settings
from src.video_agent.core import stage_probes
from src.video_agent.core.round_end_policies import (
    RoundEndContext, run_round_end_policies)
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult
from src.video_agent.tools.document_tools import register_document_tools

SKILL = "AI-短剧一站式生成"


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    # 同族口径：其它测试文件的夹具会 ToolManager.reset() 清全局注册表，
    # 本文件不依赖导入副作用
    register_document_tools()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


class _Exec:
    """最小执行器桩：只承载策略所需 state。"""

    def __init__(self, state):
        self.state = state


def _run(ctx):
    async def emit(_event):
        pass

    return asyncio.run(run_round_end_policies(ctx, emit))


# ---------- ① 客观账本回执 ----------

def test_stamp_receipt_reports_objective_ledger():
    text = stage_probes.stamp_receipt({}, SKILL)
    assert "完成章" in text, "回执取不到 STAMP_RECEIPT 分节（文案唯一源缺失）"
    assert "分镜 0 组 0 卡" in text
    assert "未完成" in text and "故事板拆解" in text


def test_stamp_receipt_lists_populated_products():
    st = {
        "analysis": {"summary": "一句话总结"},
        "keyElements": [{"id": "g1", "drafts": [{}, {}]}],
        "shots": [{"id": "g2", "drafts": [{}]}],
        "audioItems": [],
        "documents": [{"name": "制片规格.md", "content": "画幅：16:9"}],
    }
    text = stage_probes.stamp_receipt(st, SKILL)
    assert "关键元素 1 组 2 卡" in text
    assert "规格文档=在盘" in text
    assert "剧本分析=已落账" in text and "剧本分析=完成" in text


def test_stamp_receipt_without_skill_has_no_stage_judgement():
    """未激活 Skill = 不适用阶段判定（普通对话不被本机制约束）。"""
    assert stage_probes.outstanding_stages({}, "") == []
    assert "不做阶段判定" in stage_probes.stamp_receipt({}, "")


def test_nudge_is_factual():
    nudge = stage_probes.unstamped_stop_nudge({}, SKILL)
    assert "零工具调用" in nudge
    assert "task_complete" in nudge


# ---------- ② / ③ 盖章发行与上抛 ----------

class _StubTM:
    """按声明派发：task_complete 返回盖章事实，其余工具记账（用于验证冻结）。"""

    def __init__(self):
        self.invoked = []

    def get_tool(self, name):
        class _T:
            risk = "low"
            parallel_safe = False
            detail_tier = "output"
        return _T()

    async def invoke_tool(self, name, args):
        self.invoked.append(name)
        if name == "task_complete":
            return ToolResult(success=True, data={
                "stamped": True, "summary": str((args or {}).get("summary") or "")})
        return ToolResult(success=True, data={})


def _resp(*calls):
    from src.video_agent.adapters.base_chat import ChatResponse
    return ChatResponse(content="", finish_reason="tool_calls", tool_calls=[
        {"id": f"c{i}", "type": "function",
         "function": {"name": n, "arguments": json.dumps(a)}}
        for i, (n, a) in enumerate(calls)])


def test_runner_stamps_and_freezes_batch(monkeypatch):
    """runner 发行盖章：回喂数据带客观账本（供 turn_executor 认数据上抛），
    并冻结本批（排在其后的调用不执行）。"""
    from src.video_agent.core.fc_tool_runner import FCToolRunner

    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    tm = _StubTM()
    runner = FCToolRunner(tm)
    res = asyncio.run(runner.execute(_resp(
        ("task_complete", {"summary": "本轮读完剧本"}),
        ("storyboard_create_group", {}))))
    assert res.applied == 1
    data = res.tool_results[0]["data"]
    assert data["stamped"] is True and data["summary"] == "本轮读完剧本"
    assert "完成章" in data["ledger"], "盖章回执（客观账本）须随结构化数据上抛"
    assert "storyboard_create_group" not in tm.invoked, "盖章即冻结本批"


# ---------- ④ 轮末闸机 ----------

def test_gate_rejects_unstamped_zero_action_stop():
    ctx = RoundEndContext(step=1, executor=_Exec({}), skill=SKILL,
                          content="已完成 S9-S12 的搭建。", applied=0,
                          stamp_budget_left=True)
    out = _run(ctx)
    assert out.continue_turn is True
    assert out.stamp_nudge


def test_gate_skips_when_stamped():
    ctx = RoundEndContext(step=1, executor=_Exec({}), skill=SKILL,
                          content="本轮到此交付。", applied=0, stamped=True,
                          stamp_budget_left=True)
    out = _run(ctx)
    assert out.continue_turn is False
    assert out.result_warnings == []


def test_gate_skips_without_skill():
    ctx = RoundEndContext(step=1, executor=_Exec({}), skill="",
                          content="谢谢，我先了解一下你的需求。", applied=0,
                          stamp_budget_left=True)
    assert _run(ctx).continue_turn is False


def test_gate_skips_when_turn_had_actions():
    """本回合真调过工具（applied>0）= 说法有据，不续跑。"""
    ctx = RoundEndContext(step=1, executor=_Exec({}), skill=SKILL,
                          content="已建 3 组关键元素，先停一下。", applied=4,
                          stamp_budget_left=True)
    assert _run(ctx).continue_turn is False


def test_notice_after_budget_exhausted():
    ctx = RoundEndContext(step=1, executor=_Exec({}), skill=SKILL,
                          content="已完成，无需再动。", applied=0,
                          stamp_budget_left=False)
    out = _run(ctx)
    assert out.continue_turn is False, "预算耗尽不得再续跑（防打转）"
    assert any("未完成阶段" in w for w in out.result_warnings), "须留事实性警告"


def test_gate_off_when_switch_disabled():
    """总开关关 = 两条盖章策略全失效（一键回滚，不拦不告）。"""
    old = settings.completion_stamp_enabled
    object.__setattr__(settings, "completion_stamp_enabled", False)
    try:
        out = _run(RoundEndContext(step=1, executor=_Exec({}), skill=SKILL,
                                   content="已完成。", applied=0,
                                   stamp_budget_left=True))
        assert out.continue_turn is False
        assert out.result_warnings == []
        # 预算耗尽分支同样不告（开关关时不产生任何新可见行为）
        out2 = _run(RoundEndContext(step=1, executor=_Exec({}), skill=SKILL,
                                    content="已完成。", applied=0,
                                    stamp_budget_left=False))
        assert out2.result_warnings == []
    finally:
        object.__setattr__(settings, "completion_stamp_enabled", old)


# ---------- ⑤ agent_loop 端到端 ----------

async def test_agent_loop_continues_once_then_notices(svc, monkeypatch):
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(al, "fallback_skill_from_state", lambda _state: SKILL)
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return "已把分镜 S9-S12 建好了。", "stop", 0, 0.0, {}

    result = await al.run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=_Exec(svc.state_dict), history=[])
    assert calls["n"] == 2, "零动作未盖章收尾须被驳回续跑一次（不多烧）"
    assert any("未完成阶段" in w for w in result.warnings)


async def test_agent_loop_stops_immediately_when_stamped(svc, monkeypatch):
    """模型盖章 = 一次调用即收轮，不多烧一步。"""
    import src.video_agent.core.agent_loop as al

    monkeypatch.setattr(al, "fallback_skill_from_state", lambda _state: SKILL)
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return "", "tool_calls", 1, 0.0, {
            "completion_stamp": "（系统）已登记本轮完成章。",
            "completion_summary": "本轮只做了答疑，未动工作台。"}

    result = await al.run_agent_loop(
        "继续", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=_Exec(svc.state_dict), history=[])
    assert calls["n"] == 1
    assert result.applied_actions == 1
    assert result.text == "本轮只做了答疑，未动工作台。", (
        "盖章轮无正文时不得落到「已执行 N 个操作」口径（纯口头交付会误报）")


# ---------- ⑤ 总开关裁剪 ----------

def test_task_complete_excluded_when_disabled(svc):
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.tools.manager import ToolManager

    p = Planner(state_manager=svc, tool_manager=ToolManager, llm_adapter=None)
    old = settings.completion_stamp_enabled
    try:
        object.__setattr__(settings, "completion_stamp_enabled", False)
        assert "task_complete" in p._compute_excluded_tools(PlannerContext())
        object.__setattr__(settings, "completion_stamp_enabled", True)
        assert "task_complete" not in p._compute_excluded_tools(PlannerContext())
    finally:
        object.__setattr__(settings, "completion_stamp_enabled", old)
