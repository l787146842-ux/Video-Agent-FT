"""audit-0819e 阶段 2/3 钉死回归：控制流统一（确定性分诊 + 步间回收）。

1111 事故根治：概率语料路由已删（S04 下账），分诊只认客观状态事实；
模型循环每个 FC 批落盘后外层循环再评估（单一就绪单元语义），
确定性阶段就绪/应发机械卡即回收控制权——交接不再等于失控。
"""
import pytest

from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.planner import Planner
from src.video_agent.state.manager import StateManager
from src.video_agent.web.action_executor import StudioActionExecutor

_SKILL = "控制流测试技能"


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def planner(svc):
    return Planner(state_manager=svc, llm_adapter=None, tool_manager=None)


# ---------- 阶段 2：确定性分诊（零语料） ----------

def test_triage_pending_confirmation_is_advance(planner, svc):
    """待确认暂停的回应 = 续进（客观事实，不猜措辞）"""
    svc.state_dict["interaction"] = {"awaiting_confirmation": True}
    assert planner._triage_control("好", _SKILL) == "advance"
    assert planner._triage_control("嗯，就这样吧", _SKILL) == "advance"


def test_triage_adhoc_title_mention_is_handoff(planner, svc):
    """暂停中点名资产 = 改指示 → 交接模型循环（客观标题命中，非语料）"""
    svc.state_dict["interaction"] = {"awaiting_confirmation": True}
    svc.state_dict["keyElements"] = [{"title": "程心"}]
    assert planner._triage_control("把程心的描述改一下", _SKILL) == "handoff"


def test_triage_question_is_handoff(planner, svc):
    assert planner._triage_control("什么是关键元素？", _SKILL) == "handoff"


def test_triage_kickoff_with_materials(planner, svc):
    """管线未启动 + 原料就位 → 开局接管（编排器直跑首个确定性阶段）"""
    svc.state_dict["uploadedDocs"] = [{"id": "d1", "name": "剧本.md", "content": "x"}]
    assert planner._triage_control("AI-短剧一站式生成", _SKILL) == "advance"


def test_triage_started_free_message_is_handoff(planner, svc):
    """管线已启动、无待办、非机械文案 → 交接（歧义不猜意图）"""
    svc.state_dict["analysis"] = {"summary": "x"}
    assert planner._triage_control("帮我想个海报创意", _SKILL) == "handoff"


def test_triage_system_continue_button_is_advance(planner, svc):
    """suggested_actions continue 按钮机械文案 = 确定性续进"""
    svc.state_dict["analysis"] = {"summary": "x"}
    assert planner._triage_control("继续完成", _SKILL) == "advance"


def test_corpus_symbols_deleted():
    """防复活：概率语料路由符号禁止回到 Planner（S04 已下账）"""
    assert not hasattr(Planner, "_ADVANCE_CORPUS")
    assert not hasattr(Planner, "_ADHOC_VERBS")
    assert not hasattr(Planner, "_route_orchestrator")


# ---------- 阶段 3：步间回收（单一就绪单元语义） ----------

@pytest.fixture
def executor(svc):
    return StudioActionExecutor(svc)


@pytest.mark.asyncio
async def test_reclaim_interrupts_loop_with_spec_card(executor):
    """1111 现场钉死：模型循环 FC 批落盘后，外层循环发现应发规格向导卡
    → 立即回收控制权，循环终止并把卡片带回（越阶不再可能发生）"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return ("处理中", "tool_calls", 1)  # 恒 FC 批 → 原本会无限多步

    reclaim_count = {"n": 0}

    async def between_steps(step):
        reclaim_count["n"] += 1
        return {
            "confirmation": "请选择成片规格参数",
            "confirmation_options": [{"label": "16:9 横屏", "description": ""}],
            "reason": "spec_pending",
        }

    result = await run_agent_loop(
        "开始", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[], between_steps=between_steps,
    )
    assert calls["n"] == 1, "第一步落盘后必须立即回收，不得继续烧模型轮次"
    assert reclaim_count["n"] == 1
    assert result.confirmation == "请选择成片规格参数"
    assert result.confirmation_options == [{"label": "16:9 横屏", "description": ""}]


@pytest.mark.asyncio
async def test_reclaim_none_continues_loop(executor):
    """回收评估返回 None（创作型阶段就绪）→ 循环照常继续"""
    replies = [("处理中", "tool_calls", 1), ("完成了", "stop", 0)]
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        r = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return r

    async def between_steps(step):
        return None

    result = await run_agent_loop(
        "开始", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[], between_steps=between_steps,
    )
    assert calls["n"] == 2, "回收返回 None 时不得中断多步链"
    assert not result.confirmation


@pytest.mark.asyncio
async def test_reclaim_error_does_not_break_loop(executor):
    """回收钩子异常 fail-open：不阻断循环（闸机失败-open 惯例）"""
    replies = [("处理中", "tool_calls", 1), ("完成了", "stop", 0)]
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        r = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return r

    async def between_steps(step):
        raise RuntimeError("模拟编排器评估异常")

    result = await run_agent_loop(
        "开始", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[], between_steps=between_steps,
    )
    assert calls["n"] == 2
    assert not result.confirmation
