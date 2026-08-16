"""四轮 R4 回归：SSE 事件协议四段链自动校验（6666 式断链防复发）。

遍历 web/sse_protocol.py 注册表，逐事件断言四段链完整：
1. 发射段：登记的每个后端发射方源码中存在该事件的发射（常量或字面量）；
2. 透传段：transport=passthrough 的事件出现在 chat_service 透传白名单；
3. 前端段：非 internal 事件在 use-sse.ts 存在对应 case handler；
4. 一致性：sse_events.py 的全部常量均已登记（新增事件不登记即红）。
"""
import re
from pathlib import Path

import pytest

from src.video_agent.core import sse_events
from src.video_agent.web.sse_protocol import PASSTHROUGH_EVENT_TYPES, SSE_EVENT_REGISTRY

ROOT = Path(__file__).resolve().parents[2]
VA = ROOT / "src" / "video_agent"
USE_SSE = ROOT / "src" / "web" / "hooks" / "use-sse.ts"

_chat_service_src = (VA / "web" / "chat_service.py").read_text(encoding="utf-8")
_use_sse_src = USE_SSE.read_text(encoding="utf-8")


def test_r4_registry_covers_all_event_constants():
    """一致性：sse_events 的全部 SSE_* 常量都在注册表登记（新增不登记即红）。"""
    constants = {
        v for k, v in vars(sse_events).items()
        if k.startswith("SSE_") and isinstance(v, str)
    }
    registered = {s.event_type for s in SSE_EVENT_REGISTRY}
    assert constants == registered, f"未登记事件: {constants - registered}；多余登记: {registered - constants}"


@pytest.mark.parametrize("spec", SSE_EVENT_REGISTRY, ids=lambda s: s.event_type)
def test_r4_emitter_segment(spec):
    """发射段：每个登记的发射方源码中存在该事件类型的发射痕迹
    （SSE_* 常量引用或 "type": "<event>" 字面量）。"""
    for emitter in spec.emitters:
        src = (VA / emitter).read_text(encoding="utf-8")
        const_name = next(
            (k for k, v in vars(sse_events).items() if v == spec.event_type and k.startswith("SSE_")),
            None,
        )
        has_const = bool(const_name) and const_name in src
        has_literal = f'"{spec.event_type}"' in src or f"'{spec.event_type}'" in src
        # 四轮 R3 起固定文案 status 经 sse_events.status_event() 构造发射
        has_builder = spec.event_type == "status" and "status_event(" in src
        assert has_const or has_literal or has_builder, (
            f"四段链断链（发射段）：{emitter} 不再发射 {spec.event_type}"
            f"（事故溯源：{spec.incident}）"
        )


@pytest.mark.parametrize(
    "spec", [s for s in SSE_EVENT_REGISTRY if s.transport == "passthrough"],
    ids=lambda s: s.event_type,
)
def test_r4_transport_segment(spec):
    """透传段：passthrough 事件在 chat_service 透传白名单元组内。"""
    # 白名单形如 event.type in ("reasoning_delta", "tool_started", ...)；
    # 常量形态（SSE_GUIDANCE_INJECTED）与字面量形态都接受
    const_name = next(
        (k for k, v in vars(sse_events).items() if v == spec.event_type and k.startswith("SSE_")),
        "",
    )
    in_whitelist_literal = re.search(
        rf'event\.type in \(([^)]*"{re.escape(spec.event_type)}"[^)]*)\)',
        _chat_service_src,
    )
    in_whitelist_const = re.search(
        rf"event\.type in \(([^)]*\b{re.escape(const_name)}\b[^)]*)\)",
        _chat_service_src,
    ) if const_name else None
    assert in_whitelist_literal or in_whitelist_const, (
        f"四段链断链（透传段）：chat_service 白名单缺 {spec.event_type}"
        f"（事故溯源：{spec.incident}——6666 即此段断链导致文档卡片延迟）"
    )
    # 注册表侧的透传清单与白名单交叉核对
    assert spec.event_type in PASSTHROUGH_EVENT_TYPES


@pytest.mark.parametrize(
    "spec", [s for s in SSE_EVENT_REGISTRY if s.transport != "internal"],
    ids=lambda s: s.event_type,
)
def test_r4_frontend_handler_segment(spec):
    """前端段：非 internal 事件在 use-sse.ts 存在 case handler。"""
    assert re.search(rf"case\s+'{re.escape(spec.frontend_case)}'\s*:", _use_sse_src), (
        f"四段链断链（前端段）：use-sse.ts 缺 case '{spec.frontend_case}'"
        f"（事件 {spec.event_type}，事故溯源：{spec.incident}）"
    )


@pytest.mark.parametrize(
    "spec", [s for s in SSE_EVENT_REGISTRY if s.transport == "internal"],
    ids=lambda s: s.event_type,
)
def test_r4_internal_events_not_front_end_dependent(spec):
    """internal 事件不得出现前端 handler（防误依赖内部事件）。"""
    assert not re.search(rf"case\s+'{re.escape(spec.event_type)}'\s*:", _use_sse_src), (
        f"{spec.event_type} 是登记的内部事件，前端不得依赖其 handler"
    )
