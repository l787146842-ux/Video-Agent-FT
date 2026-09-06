# -*- coding: utf-8 -*-
"""五项修法批 4 钉死回归：思考回传 llm_reasoning_passthrough（default-off）。

调研结论（2026-09-07，智谱开放平台官方文档）：GLM 4.5+ 默认支持交错思考，
工具循环场景官方要求把 assistant 消息的 reasoning_content 完整、未修改地
回传 API（流式从 delta.reasoning_content 累积）；不回传丧失推理连续性与
缓存命中收益。据此实现 default-off 闸门的三层组合：
① 请求侧（openai_compat）：关=剥离 assistant 历史消息的 reasoning_content
  （防残留字段外泄拒收端点）；开=原样下发；非流式响应捕获思考内容；
② 会话消息结构（add_chat_message）：非空才落 reasoning_content 字段；
③ 历史组装（truncate_history）：闸门开时 assistant 历史消息透传该字段。
"""
import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.config import settings
from src.video_agent.core.agent_loop import AgentLoopResult, run_agent_loop
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.planner_output import assemble_response
from src.video_agent.state.manager import StateManager

BASE_URL = "https://api.test-provider.com/v1"


@pytest.fixture
def _gate_on():
    old = settings.llm_reasoning_passthrough
    object.__setattr__(settings, "llm_reasoning_passthrough", True)
    yield
    object.__setattr__(settings, "llm_reasoning_passthrough", old)


def test_default_off():
    """default-off：思考回传默认关闭（用户裁决：系统侧不把调参负担推给用户）"""
    from dataclasses import fields

    from src.video_agent.config import Settings

    f = {x.name: x for x in fields(Settings)}["llm_reasoning_passthrough"]
    assert f.default_factory() is False


# ---------- ① 请求侧（openai_compat） ----------


@respx.mock
async def test_chat_captures_reasoning_content():
    """非流式响应的 reasoning_content 随 ChatResponse 捕获（回传与否归闸门）"""
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "答案", "reasoning_content": "推理过程…"},
                         "finish_reason": "stop"}]}
        ))
    a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="k", model="glm-4.6")
    resp = await a.chat([{"role": "user", "content": "问"}])
    assert resp.reasoning_content == "推理过程…"
    assert resp.content == "答案"
    await a.close()


@respx.mock
async def test_gate_off_strips_reasoning_from_payload():
    """闸门关（默认）：assistant 历史消息携带的 reasoning_content 不进 payload，
    且调用方历史本体不被改写（浅拷贝替换）"""
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        ))
    a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="k", model="glm-4.6")
    history = [
        {"role": "user", "content": "问"},
        {"role": "assistant", "content": "占位", "reasoning_content": "思考"},
    ]
    await a.chat(history)
    sent = json.loads(route.calls.last.request.content)
    assert "reasoning_content" not in sent["messages"][1]
    assert history[1]["reasoning_content"] == "思考", "调用方历史不得被改写"
    await a.close()


@respx.mock
async def test_gate_on_passes_reasoning_through(_gate_on):
    """闸门开：assistant 历史消息的 reasoning_content 原样下发（GLM 交错思考）"""
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        ))
    a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="k", model="glm-4.6")
    await a.chat([
        {"role": "user", "content": "问"},
        {"role": "assistant", "content": "占位", "reasoning_content": "思考"},
    ])
    sent = json.loads(route.calls.last.request.content)
    assert sent["messages"][1]["reasoning_content"] == "思考"
    await a.close()


# ---------- ② 工具轮占位附着（agent_loop，GLM 工具循环主场景） ----------


@pytest.fixture
def executor(tmp_path):
    return StateOperationExecutor(StateManager(str(tmp_path)))


def _loop_llm(calls):
    async def llm_call(system_prompt, messages, stream_hook=None):
        calls.append([dict(m) for m in messages])
        if len(calls) == 1:
            # FC 工具轮：fc_applied=1 + 该轮思考内容
            return "", "tool_calls", 1, 0.0, {
                "reasoning_content": "第一轮思考", "token_usage": 0, "cached_tokens": 0}
        # 末轮（纯文本收尾轮）同样产出思考内容（末轮胜出语义的持久化数据源）
        return "完成", "stop", 0, 0.0, {
            "reasoning_content": "第二轮思考", "token_usage": 0, "cached_tokens": 0}

    return llm_call


async def test_tool_round_placeholder_carries_reasoning_when_on(executor, _gate_on):
    """闸门开：FC 工具轮占位 assistant 消息携带该轮思考内容（GLM 要求与
    工具结果同回合保持推理连续）"""
    calls = []
    result = await run_agent_loop(
        "x", llm_call=_loop_llm(calls), context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert result.reasoning_content == "第二轮思考", "末轮胜出（与最终可见回复配对）"
    second_round = calls[1]
    asst = [m for m in second_round if m.get("role") == "assistant"]
    assert asst and asst[-1].get("reasoning_content") == "第一轮思考"


async def test_tool_round_placeholder_strips_reasoning_when_off(executor):
    """闸门关（默认）：工具轮占位不携带 reasoning_content（零外流）"""
    calls = []
    result = await run_agent_loop(
        "x", llm_call=_loop_llm(calls), context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert result.reasoning_content == "第二轮思考"  # 内存捕获仍在
    second_round = calls[1]
    asst = [m for m in second_round if m.get("role") == "assistant"]
    assert asst and "reasoning_content" not in asst[-1]


# ---------- ②' 会话消息结构（add_chat_message） ----------


def test_add_chat_message_stores_reasoning(tmp_path):
    """会话消息结构：reasoning_content 非空才落字段（供 truncate_history 透传）"""
    svc = StateManager(str(tmp_path))
    svc.add_chat_message("agent", "回复", reasoning_content="思考")
    svc.add_chat_message("agent", "无思考")
    msgs = svc.get_chat_messages()
    assert msgs[-2].get("reasoning_content") == "思考"
    assert "reasoning_content" not in msgs[-1]


# ---------- ③ 历史组装（truncate_history） ----------


def test_truncate_history_passthrough_gated():
    """truncate_history：闸门开时透传 assistant 思考内容；关时剥离"""
    from src.video_agent.web.chat_opening import truncate_history

    messages = [
        {"role": "user", "content": "问"},
        {"role": "assistant", "content": "回复", "reasoning_content": "思考"},
    ]
    out_off = truncate_history([dict(m) for m in messages])
    assert "reasoning_content" not in out_off[1]

    old = settings.llm_reasoning_passthrough
    object.__setattr__(settings, "llm_reasoning_passthrough", True)
    try:
        out_on = truncate_history([dict(m) for m in messages])
        assert out_on[1]["reasoning_content"] == "思考"
    finally:
        object.__setattr__(settings, "llm_reasoning_passthrough", old)


# ---------- 轮末组装透传（planner_output） ----------


def test_assemble_response_passes_reasoning(tmp_path):
    """轮末组装：loop_result.reasoning_content 非空才透传 PlannerResponse"""
    svc = StateManager(str(tmp_path))
    executor = StateOperationExecutor(svc)
    resp = assemble_response(
        AgentLoopResult(text="完成", reasoning_content="思考"),
        executor=executor, response_factory=lambda **kw: kw,
    )
    assert resp["reasoning_content"] == "思考"
    empty = assemble_response(
        AgentLoopResult(text="完成"), executor=executor,
        response_factory=lambda **kw: kw,
    )
    assert "reasoning_content" not in empty, "空思考不透传（stub factory 兼容）"
