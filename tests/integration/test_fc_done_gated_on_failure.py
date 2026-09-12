# -*- coding: utf-8 -*-
"""批②C-2 回归：本步有工具失败/被拒时，不得因模型「同一轮说了停 + 有正文」
就 fc_done 提前收尾——具体拒因必须回喂被下一轮消费（对齐 dsh「回合去留看
tool-call」+ 本项目 v6 §2/断言#1）。零工具纯口头收尾由
test_subagent_delegation::test_zero_action_stop_ends_in_one_round 反向钉死。
"""
import json

import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.storyboard_tools import register_storyboard_tools


@pytest.fixture(autouse=True)
def _ensure_tools():
    register_storyboard_tools()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    st = instance.state_dict
    for key in ("keyElements", "shots", "audioItems"):
        st[key] = []
    yield instance
    StateManager.reset_instance()


class _ScriptedAdapter(BaseChatAdapter):
    """按脚本吐响应；支持「正文 + 工具调用 + finish=stop」三态并存。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        item = self._script.pop(0) if self._script else {"text": "收到。"}
        if item.get("tool"):
            return ChatResponse(
                content=item.get("content", ""),
                # 复现 6666：模型这一轮既发工具调用、又报 stop 且带正文
                finish_reason=item.get("finish", "tool_calls"),
                tool_calls=[{"id": f"call_{len(self.calls)}", "type": "function",
                             "function": {"name": item["tool"],
                                          "arguments": json.dumps(
                                              item.get("args", {}),
                                              ensure_ascii=False)}}],
            )
        return ChatResponse(content=item.get("text", ""),
                            finish_reason=item.get("finish", "stop"))

    async def chat_stream(self, messages, **kwargs):
        response = await self.chat(messages, **kwargs)
        from src.video_agent.adapters.base_chat import StreamChunk
        if response.tool_calls:
            yield StreamChunk(type="tool_call", tool_name=str(
                (response.tool_calls[0].get("function") or {}).get("name")),
                tool_args=dict(
                    (response.tool_calls[0].get("function") or {}).get("arguments")
                    or "{}"))
        if response.content:
            yield StreamChunk(type="text_delta", text=response.content)
        yield StreamChunk(type="done", finish_reason=response.finish_reason)


async def test_failed_tool_not_ended_by_same_turn_stop(svc):
    """第一步：建组带白名单外草稿字段→工具失败；模型同轮说 stop+正文。
    断言：循环不得在第一步 break，必须再走一步把拒因喂回模型（calls==2）。"""
    adapter = _ScriptedAdapter([
        # step1：可见正文 + finish=stop + 一个会失败的建组调用
        {"content": "我先建个关键元素组。", "finish": "stop",
         "tool": "storyboard_create_group",
         "args": {"group_type": "keyElement", "title": "程心",
                  "draft": {"label": "程心", "非法字段": "x"}}},
        # step2：模型看到拒因后正常纯文本收尾
        {"text": "收到拒因，我改用合法字段重来。"},
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    await planner.handle_message(
        "拆一个关键元素", PlannerContext(use_studio_context=True))

    # 核心：第一步未被 fc_done 提前收尾 → 模型被调用了第二次
    assert len(adapter.calls) == 2, \
        "本步有工具失败却被同轮 stop 提前 fc_done 收尾（C2 未生效）"
    # 拒因（含具体字段名）已回喂进第二步 messages，模型能看到并修正
    second_call = json.dumps(adapter.calls[1], ensure_ascii=False)
    assert "非法字段" in second_call, "具体拒因未回喂，模型无从修正（C1/C2 未生效）"
