# -*- coding: utf-8 -*-
"""子代理流式通道契约单测（2026-09-21 批G，事故 4444/Q4）。

背景（4444 实跑取证，日志逐行）：
```
15:27:59.4  子代理启动
15:28:01.9  子代理 step1 成功（read_uploaded_doc + read_project_doc，2.5s）
15:29:02.0  [Retry] chat HTTP 504，第 1/2 次      ← 距 step1 完成 60.1s
15:30:03.1  [Retry] chat HTTP 504，第 2/2 次      ← 61.1s
15:31:05.2  kind=upstream → escalate → turn/end reason=error
```
子代理死在 step2、一张卡未建——批A3 补的「每批 3~5 个」分批纪律**根本没轮到
使用**，它死在第一次要出产出的那次调用上。

**根因：`planner._launch_subagent` 不传 `stream_hook`**，于是
`turn_executor.llm_call` 走 `else` 分支（非流式 `call_llm`）。三条独立证据：
① 日志是 `[Retry] chat HTTP 504`（`retry.py:79`），而 `with_retry` **只被
   非流式 `chat()` 调用**；流式路径打的是 `[OpenAICompat] 流式瞬时故障`；
② `data/sse_capture/` 该窗口 5 个文件时间戳全是主代理的流式调用，子代理零个
   （落盘只在 `_stream_once` 内）；
③ 子会话 `assistant/partial` **0 条**，主会话 **28 条**（增量落盘只在
   流式分支内）。

后果三项：无步内增量落盘（8888 事故批的保护失效）、无「已产出则不重试」
保护、无 `reasoning_delta`（思考不可见）。

本文件钉死批G 的修复，防回潮。
"""
from pathlib import Path

import pytest

from src.video_agent.core import subagent as sub
from src.video_agent.core.planner import Planner
from src.video_agent.utils import prompts as prompts_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLANNER_SRC = PROJECT_ROOT / "src" / "video_agent" / "core" / "planner.py"
TURN_EXECUTOR_SRC = PROJECT_ROOT / "src" / "video_agent" / "core" / "turn_executor.py"

_STAGE = "storyboard_key_elements"


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    prompts_mod.clear_cache()
    yield
    prompts_mod.clear_cache()


# ---------- G1：子级确实走流式通道 ----------

def test_launch_subagent_passes_stream_hook():
    """`_launch_subagent` 必须给子级传 stream_hook（否则回落非流式通道）。

    这条是**源码级钉**：真正跑一次委派需要全栈装配，而缺陷恰是「一个关键字
    参数没传」——用源码断言最直接地锁死，改回去立即失败。
    """
    src = PLANNER_SRC.read_text(encoding="utf-8")
    assert "stream_hook=_child_stream_sink" in src, (
        "子代理委派未传 stream_hook——会回落非流式通道（4444/Q4 直接病根："
        "无增量落盘、无重试豁免、无 reasoning_delta）")


def test_child_stream_sink_is_a_sink_not_a_forwarder():
    """子级 stream_hook 必须是**收口**（不透传父正文）。

    子代理只回摘要（`resp.text`），其中间正文不该在父对话气泡里重复渲染
    （一次委派两处显示同一段话）。hook 的作用只是触发流式分支本身。
    """
    src = PLANNER_SRC.read_text(encoding="utf-8")
    marker = "async def _child_stream_sink("
    assert marker in src, "缺 _child_stream_sink 定义（批G）"
    tail = src[src.index(marker):]
    body = tail[: tail.index("\n\n")] if "\n\n" in tail else tail
    # 收口实现只应 return None，不得把文本转发给任何通道
    assert "return None" in body, "子级 hook 未收口（应直接丢弃正文增量）"
    for forward in ("on_event(", "stream_hook(", "await on_delta("):
        assert forward not in body, (
            f"子级 hook 把正文转发给了 {forward}——会在父对话重复渲染子代理正文")


def test_streaming_channel_is_what_carries_reasoning_delta():
    """钉死前提：`reasoning_delta` 只在**流式分支**内发出。

    这条解释「为什么看不到子代理思考」——若将来 reasoning 事件改到非流式
    分支也发，本组断言需重新评估（同批A 对 SUBAGENT_TOOL_DENY 的处理口径）。
    """
    src = TURN_EXECUTOR_SRC.read_text(encoding="utf-8")
    idx = src.index('"reasoning_delta"')
    # 该分支位于 `if hook:` 之内（流式分支）——向上找最近的分支守卫
    head = src[:idx]
    assert "if hook:" in head, "reasoning_delta 不在流式分支内（前提已变）"
    assert head.rindex("if hook:") > head.rindex("async def llm_call"), (
        "reasoning_delta 似乎已移出 llm_call 的流式分支")


# ---------- G2：子级仍只回摘要（hook 不改变返回契约） ----------

def test_child_still_returns_summary_only():
    """委派返回仍是「子级正文摘要」——批G 只换传输通道，不改返回契约。"""
    src = PLANNER_SRC.read_text(encoding="utf-8")
    assert "（子代理未产出摘要）" in src, "子代理空摘要兜底丢失"
    assert "getattr(resp, \"text\", \"\")" in src or "getattr(resp, 'text', '')" in src, \
        "子代理返回值不再是 resp.text（返回契约被改）"


# ---------- G3：SSE 帧带 subagent 标记 ----------

def test_reasoning_delta_frame_carries_subagent_tag():
    """`reasoning_delta` 帧必须带 `subagent` 标记（批G）。

    否则前端无法把子代理思考与父代理思考分流——只开流式而不加此标记，子代理
    思考会**串台**进父代理的思考面板。故 G1 与 G3/G4 **必须同批**。
    """
    from src.video_agent.core.sse_events import SseReasoningDeltaEvent

    props = SseReasoningDeltaEvent.model_json_schema()["properties"]
    assert "subagent" in props, (
        "reasoning_delta 帧缺 subagent 标记——子代理思考会串台到父思考面板")


def test_subagent_tagged_frames_include_reasoning():
    """带 subagent 标记的帧集合必须含 reasoning_delta（全帧枚举钉）。

    4444 取证时的实况：仅 tool_started / tool_finished / actions_applied 三帧
    有该标记（见方案 §二 Q4 附表），reasoning_delta 缺失。
    """
    from src.video_agent.core import sse_events as se

    tagged = set()
    for name, model in se.TS_EVENT_FRAMES:
        props = model.model_json_schema().get("properties") or {}
        if "subagent" in props:
            tagged.add(name)
    assert "SseReasoningDeltaEvent" in tagged, (
        f"reasoning_delta 未带 subagent 标记（当前带标记的帧：{sorted(tagged)}）")
    # 防误伤：原有三帧仍带标记
    for keep in ("SseToolStartedEvent", "SseToolFinishedEvent", "SseActionsAppliedEvent"):
        assert keep in tagged, f"{keep} 丢失 subagent 标记（原有归组能力回归）"


# ---------- 阶段隔离不回归 ----------

def test_child_deny_set_unchanged_by_streaming():
    """批G 不改工具面：子级 deny 集（含 run_subagent 防递归）逐字不变。"""
    deny = sub.child_deny_set(_STAGE)
    assert "run_subagent" in deny, "结构防递归被破坏"
    assert "workflow_pause" in deny, "子级不该持有确认工具"
    assert "read_skill" in deny, "stage 模式的跨阶段预读隔离被破坏"


def test_planner_still_constructs_for_launch():
    """防误伤：Planner 类仍可正常引用（源码级改动未破坏模块导入）。"""
    assert Planner is not None
