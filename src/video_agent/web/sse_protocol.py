"""SSE 事件协议注册表（四轮 R4：6666 式四段链断链防复发机制化）。

宪法 13.7「新增 SSE 事件」条目要求四段链同步：
    工具层 emit → planner 白名单 → chat_service 透传 → 前端 handler

本注册表是该耦合点的**机器可读版**：每个事件的发射方、透传要求、前端 handler
与引入事故号集中登记；tests/unit/test_sse_protocol_chain.py 遍历断言，
任何一段断链（如前端删了 handler、透传白名单漏登记）CI 即红。

事件名常量仍以 core/sse_events.py 为唯一权威（本表只登记，不重定义）。
"""
from dataclasses import dataclass
from typing import Tuple

from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_DELTA,
    SSE_DOC_WRITTEN,
    SSE_DONE,
    SSE_ERROR,
    SSE_EXECUTING_ACTIONS,
    SSE_GUIDANCE_INJECTED,
    SSE_MODEL_FALLBACK,
    SSE_REASONING_DELTA,
    SSE_STATUS,
    SSE_STEP_STARTED,
    SSE_TOOL_FINISHED,
    SSE_TOOL_STARTED,
)


@dataclass(frozen=True)
class SseEventSpec:
    """单个 SSE 事件的协议登记项。"""
    event_type: str
    # 后端发射方模块（相对 src/video_agent，测试以源码包含 emit 该 type 断言）
    emitters: Tuple[str, ...]
    # chat_service 透传路径：passthrough=白名单元组成员 / direct=独立分支处理 /
    # internal=agent_loop 内部事件（不透传前端，登记防误加前端依赖）
    transport: str
    # 前端 use-sse.ts 的 case 标签（internal 事件为空）
    frontend_case: str
    # 引入/修复事故号（溯源用）
    incident: str


SSE_EVENT_REGISTRY: Tuple[SseEventSpec, ...] = (
    SseEventSpec(
        SSE_STATUS,
        ("core/agent_loop.py", "core/round_end_policies.py", "web/chat_service.py"),
        "direct", "status", "初始协议；四轮 R3 key+params i18n 化",
    ),
    SseEventSpec(
        SSE_DELTA, ("web/chat_service.py",),
        "direct", "delta", "初始协议",
    ),
    SseEventSpec(
        SSE_REASONING_DELTA, ("core/planner.py",),
        "passthrough", "reasoning_delta", "深度思考可视化",
    ),
    SseEventSpec(
        SSE_TOOL_STARTED, ("core/agent_loop.py", "core/fc_tool_runner.py"),
        "passthrough", "tool_started", "过程时间线",
    ),
    SseEventSpec(
        SSE_TOOL_FINISHED, ("core/agent_loop.py", "core/fc_tool_runner.py"),
        "passthrough", "tool_finished", "过程时间线",
    ),
    SseEventSpec(
        SSE_DOC_WRITTEN, ("core/agent_loop.py", "core/fc_tool_runner.py"),
        "passthrough", "doc_written", "3333/6666 事故（四段链补齐）",
    ),
    SseEventSpec(
        SSE_MODEL_FALLBACK, ("web/chat_service.py",),
        "direct", "model_fallback", "7777 事故（降级即时联动）",
    ),
    SseEventSpec(
        SSE_GUIDANCE_INJECTED, ("core/agent_loop.py",),
        "passthrough", "guidance_injected", "7777 三轮（轮间注入）",
    ),
    SseEventSpec(
        SSE_DONE, ("web/chat_service.py",),
        "direct", "done", "初始协议",
    ),
    SseEventSpec(
        SSE_ERROR, ("web/chat_service.py",),
        "direct", "error", "初始协议（P0-2 结构化故障标记）",
    ),
    SseEventSpec(
        SSE_ACTIONS_APPLIED, ("web/chat_service.py", "core/agent_loop.py"),
        "direct", "actions_applied", "初始协议（chat_service 附带状态快照）",
    ),
    SseEventSpec(
        SSE_STEP_STARTED, ("core/agent_loop.py",),
        "internal", "", "内部事件（前端忽略，登记防误依赖）",
    ),
    SseEventSpec(
        SSE_EXECUTING_ACTIONS, ("core/agent_loop.py",),
        "internal", "", "内部事件（前端忽略，登记防误依赖）",
    ),
)


# chat_service 透传白名单应包含的事件（transport=passthrough 者，
# 测试对照 chat_service 源码的透传元组断言）
PASSTHROUGH_EVENT_TYPES = tuple(
    s.event_type for s in SSE_EVENT_REGISTRY if s.transport == "passthrough"
)
