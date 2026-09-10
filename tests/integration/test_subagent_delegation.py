# -*- coding: utf-8 -*-
"""正宗子代理委派 + 完成盖章 端到端回归（scripted 模型，不连真供应商）。

钉死两条链路（真过闸机、真写工作台，只把模型换成脚本）：
① 父经 FC `run_subagent` 委派 → 子在隔离上下文（独立 messages + 类型白名单）连续
   跑完并真落账 → 只回摘要给父（子的中间步不进父上下文）→ 子线程事件流自描述落流；
② 零工具纯口头"已完成"收尾**不受理**（dsh A2 未盖章不放行）：确实多走一步，
   预算耗尽后以事实性警告收尾（2222 那类空转轮不再静默结束）。
"""
import json

import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core import session_log
from src.video_agent.state import conversation_ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.analysis_tools import register_analysis_tools
from src.video_agent.tools.document_tools import register_document_tools
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.storyboard_tools import register_storyboard_tools

SKILL = "AI-短剧一站式生成"


@pytest.fixture(autouse=True)
def _ensure_tools():
    # 显式重注册全套（同 worker 其它文件会 ToolManager.reset() 清全局表，
    # 跨文件污染先例见 test_hybrid_boundaries / test_subagent_run_subagent）：
    # 委派链父子两端都要真工具在册（子在白名单内建组落账）。
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    st = instance.state_dict
    # 客观前置就位（分析已落账 + 规格在盘），但结构为空：
    # 委派与未盖章判定都只认这些客观事实
    st["usedSkills"] = [SKILL]
    st["analysis"] = {"summary": "一句话总结：程心苏醒。"}
    st["documents"] = [{"name": "制片规格.md", "content": "画幅：16:9"}]
    for key in ("keyElements", "shots", "audioItems"):
        st[key] = []
    yield instance
    StateManager.reset_instance()


class _ScriptedAdapter(BaseChatAdapter):
    """按脚本依次吐响应；记录每轮收到的 messages（父子上下文隔离的取证面）。"""

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
                content=item.get("content", ""), finish_reason="tool_calls",
                tool_calls=[{"id": f"call_{len(self.calls)}", "type": "function",
                             "function": {"name": item["tool"],
                                          "arguments": json.dumps(
                                              item.get("args", {}),
                                              ensure_ascii=False)}}],
            )
        return ChatResponse(content=item.get("text", ""), finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        response = await self.chat(messages, **kwargs)
        from src.video_agent.adapters.base_chat import StreamChunk
        if response.tool_calls:
            yield StreamChunk(type="tool_call", tool_name=str(
                (response.tool_calls[0].get("function") or {}).get("name")),
                tool_args=dict(
                    (response.tool_calls[0].get("function") or {}).get("arguments")
                    or "{}"))
        else:
            yield StreamChunk(type="text_delta", text=response.content)
        yield StreamChunk(type="done", finish_reason=response.finish_reason)


def _tool_call_names(messages) -> list:
    out = []
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            out.append(str(((tc or {}).get("function") or {}).get("name") or ""))
    return out


async def test_delegation_runs_child_in_isolated_context_and_returns_summary(svc):
    """父发 run_subagent → 子真建组落账 → 只回摘要；子的中间步不出现在父上下文。"""
    adapter = _ScriptedAdapter([
        # 1) 父：委派（带类型）
        {"tool": "run_subagent", "args": {
            "task": "按已确认规格拆解关键元素：程心、阶梯计划",
            "task_kind": "storyboard_split"}},
        # 2) 子：真调建组工具（经同一闸机链、写同一工作台）
        {"tool": "storyboard_create_group", "args": {
            "group_type": "keyElement", "title": "程心",
            "draft": {"label": "程心", "desc": "主角"}}},
        # 3) 子：摘要收尾（本轮调过工具 = 说法有据，不被盖章闸驳回）
        {"text": "已建 1 组关键元素（1 卡：程心）。"},
        # 4) 父：向用户交代
        {"text": "结构搭建已由子代理完成。"},
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    result = await planner.handle_message(
        "把剧本拆成关键元素",
        PlannerContext(skill_name=SKILL, use_studio_context=True))

    # ① 子的产物真的落进共享工作台（账本合流，B4 结论）
    ke = svc.state_dict.get("keyElements") or []
    assert any(g.get("title") == "程心" for g in ke), "子级建组未落账"
    # ② 父收到子的摘要，并向用户交付
    assert "结构搭建已由子代理完成" in (result.text or "")
    parent_last = adapter.calls[-1]
    joined = json.dumps(parent_last, ensure_ascii=False)
    assert "已建 1 组关键元素" in joined, "子的摘要未回喂进父上下文"
    # ③ 隔离：调用序列 = 父→子(2 步)→父（子在内联跑完，父等摘要）；
    #    子的建组调用只出现在子自己的历史里（calls[1]/calls[2]），
    #    父的上下文（calls[0]/calls[-1]）只有 run_subagent 那一次调用
    assert len(adapter.calls) == 4, f"调用序列不符（实为 {len(adapter.calls)}）"
    assert "storyboard_create_group" in _tool_call_names(adapter.calls[2]), \
        "测试前提：子级确已在自己上下文里发起建组调用"
    for parent_idx in (0, len(adapter.calls) - 1):
        assert "storyboard_create_group" not in _tool_call_names(adapter.calls[parent_idx]), \
            "子的中间步灌进了父上下文（隔离失效）"
    # ④ 子线程落流自描述（任务 + 过程 + 摘要），供左栏只读记录
    threads = svc.subagent_threads()
    assert len(threads) == 1, "子代理隐藏线程未创建"
    events = session_log.load_events(svc, threads[0]["conversation_id"])
    types = [e.get("type") for e in events]
    assert "user/message" in types and "assistant/message" in types
    assert any("程心" in str(e.get("content") or "")
               for e in events if e.get("type") == "assistant/message")


async def test_unstamped_zero_action_stop_is_rejected_then_warns(svc):
    """零工具纯口头"已完成"不受理：续跑一次，仍未行动则以事实警告收尾。"""
    adapter = _ScriptedAdapter([
        {"text": "已完成关键元素与分镜拆解，请查看故事板。"},   # 谎报轮（被驳回）
        {"text": "抱歉，我需要重新提交建组调用。"},             # 依旧零工具 → 收尾
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    result = await planner.handle_message(
        "继续", PlannerContext(skill_name=SKILL, use_studio_context=True))

    assert len(adapter.calls) == 2, "未盖章零动作收尾必须被驳回续跑一次"
    assert any("未完成阶段" in w for w in result.warnings), \
        "预算耗尽后须留客观未完成阶段的事实警告"
    # 一次也没建成：工作台仍为空（警告内容与事实一致，不虚报）
    assert not (svc.state_dict.get("keyElements") or [])


async def test_stamp_ends_turn_without_extra_step(svc):
    """盖章轮一步即收：不再多烧一次模型调用。"""
    adapter = _ScriptedAdapter([
        {"tool": "task_complete", "content": "本轮只答疑，未动工作台。",
         "args": {"summary": "本轮只答疑，未动工作台。"}},
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    cid = str((conversation_ops.ensure_conversations(svc)[0] or {}).get("id") or "")
    assert cid, "测试前提：会话存在（落流需绑 conversation_id）"
    result = await planner.handle_message(
        "分镜和镜头有什么区别？",
        PlannerContext(skill_name=SKILL, use_studio_context=True,
                       session_conversation_id=cid))

    assert len(adapter.calls) == 1, "盖章即收轮，不需再一次调用才停"
    assert result.applied_actions == 1
    assert "答疑" in (result.text or "")
    # 审计痕迹：turn/stamp 事件与本轮同源入流（不判真假，只留事实）
    events = session_log.load_events(svc, cid)
    assert any(e.get("type") == session_log.EV_TURN_STAMP for e in events)
    assert any(e.get("type") == session_log.EV_TURN_END for e in events)
