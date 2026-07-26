"""run_agent_loop：多步 continue 协议、截断告警、上限终止"""
import pytest

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.web.agent_loop import run_agent_loop
from src.video_agent.web.state_service import StudioStateService


@pytest.fixture
def svc(tmp_path):
    return StudioStateService(base_dir=tmp_path)


@pytest.fixture
def executor(svc):
    return StudioActionExecutor(svc)


def make_llm(replies):
    """按次序返回预设回复的假 LLM；记录每轮收到的 system prompt"""
    calls = {"n": 0, "systems": []}

    async def llm_call(system_prompt, messages):
        calls["systems"].append(system_prompt)
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return reply

    return llm_call, calls


async def test_single_step_no_continue(svc, executor):
    reply = ('创建完成\n```studio-actions\n'
             '[{"action":"add_group","group_type":"shot","title":"分镜A","draft":{"label":"d","prompt":"p"}}]\n```', "stop")
    llm, calls = make_llm([reply])
    result = await run_agent_loop(
        "拆解", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.steps == 1
    assert result.applied_actions == 1
    assert calls["n"] == 1
    assert "创建完成" in result.text


async def test_continue_triggers_second_round(svc, executor):
    r1 = ('第一轮\n```studio-actions\n'
          '[{"action":"add_group","group_type":"shot","title":"S1","draft":{"label":"d","prompt":"p"}},'
          '{"action":"continue","reason":"继续补充"}]\n```', "stop")
    r2 = ('第二轮完成\n```studio-actions\n'
          '[{"action":"add_group","group_type":"shot","title":"S2","draft":{"label":"d","prompt":"p"}}]\n```', "stop")
    llm, calls = make_llm([r1, r2])
    result = await run_agent_loop(
        "拆解全部", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.steps == 2
    assert result.applied_actions == 2  # continue 本身不计数
    assert calls["n"] == 2
    titles = [g["title"] for g in svc.state["shots"]]
    assert "S1" in titles and "S2" in titles


async def test_max_steps_cap(svc, executor):
    looping = ('循环\n```studio-actions\n[{"action":"continue","reason":"永远继续"}]\n```', "stop")
    llm, calls = make_llm([looping])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[], max_steps=3,
    )
    assert result.steps == 3
    assert calls["n"] == 3
    assert any("上限" in w for w in result.warnings)


async def test_truncation_warning(svc, executor):
    truncated = ('被截断的回复\n```studio-actions\n[{"action":"add_group","title":"未闭合', "length")
    llm, _ = make_llm([truncated])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.steps == 1
    assert any("截断" in w for w in result.warnings)
    assert any("解析失败" in w for w in result.warnings)
    assert result.applied_actions == 0


async def test_context_refreshed_each_round(svc, executor):
    ctx_calls = {"n": 0}

    def context_builder():
        ctx_calls["n"] += 1
        return f"ctx-{ctx_calls['n']}"

    r1 = ('a\n```studio-actions\n[{"action":"continue"}]\n```', "stop")
    r2 = ("done", "stop")
    llm, calls = make_llm([r1, r2])
    await run_agent_loop(
        "x", llm_call=llm, context_builder=context_builder, executor=executor, history=[],
    )
    # 每轮都要重建上下文，且两轮拿到的不同
    assert calls["systems"] == ["ctx-1", "ctx-2"]
