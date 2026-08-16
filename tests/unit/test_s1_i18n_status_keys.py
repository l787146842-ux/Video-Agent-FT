"""五轮 S1/#1：i18n 残留清偿回归（源码扫描断言，R4 自验证模式）。

四轮 R3/#5 宣称 SSE status 全量 i18n 化，但 planner 队列级 status 三处与
前端 chat.ts meta 行残留硬编码中文（五轮审核 #1 实测漂移）。本测试钉死：
1. planner.handle_message_stream 的队列级 status 一律经 status_event（key+params）；
2. chat_service 的 status/actions_applied 分支透传 payload（key 不丢）；
3. 前端 locale 字典含对应 key（四段链后端→前端同键）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 队列级 status 的四个 i18n key（planner 发射、前端字典同名消费）
QUEUE_STATUS_KEYS = (
    "agent.roundStart",
    "agent.planning",
    "agent.actionsApplied",
    "agent.executing",
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _stream_region(planner_src: str) -> str:
    """截取 handle_message_stream 函数体（到下一个同级方法定义为止）"""
    start = planner_src.index("async def handle_message_stream")
    end = planner_src.index("# ---------- 内部方法 ----------", start)
    return planner_src[start:end]


def test_s1_planner_queue_status_carry_keys():
    region = _stream_region(_read("src/video_agent/core/planner.py"))
    for key in QUEUE_STATUS_KEYS:
        assert f'"{key}"' in region, f"队列级 status 缺 i18n key: {key}"
    # 不得残留无 payload 的裸 status PlannerEvent（旧硬编码形态）
    assert 'PlannerEvent(type="status", text="正在执行操作…")' not in region
    # 每个队列级 status 的 PlannerEvent 必须携带 payload（status_event 整体）
    assert region.count("payload=sev") >= 2


def test_s1_chat_service_passthrough_status_payload():
    src = _read("src/video_agent/web/chat_service.py")
    # status 分支：payload 优先透传（key+params 不丢）
    assert 'await emit(event.payload or {"type": SSE_STATUS, "text": event.text})' in src
    # actions_applied 分支：status_event 透传
    assert '_ap.get("status_event")' in src


def test_s1_frontend_locale_has_queue_status_keys():
    locale = _read("src/web/lib/locale.ts")
    for key in QUEUE_STATUS_KEYS:
        assert f"'{key}'" in locale, f"前端 locale 缺后端同名 key: {key}"


def test_s1_frontend_meta_uses_locale_keys():
    chat = _read("src/web/stores/chat.ts")
    for key in ("rp.msg.metaTime", "rp.msg.metaRounds", "rp.msg.metaUpdated"):
        assert f"'{key}'" in chat, f"chat.ts meta 未走 locale: {key}"
    locale = _read("src/web/lib/locale.ts")
    for key in ("rp.msg.metaTime", "rp.msg.metaRounds", "rp.msg.metaUpdated"):
        assert f"'{key}'" in locale, f"locale 字典缺 meta key: {key}"


def test_s1_agent_loop_status_all_keyed():
    """G4 同类覆盖：agent_loop 不得残留无 key 的裸 status 发射（R3 基线不回潮）"""
    src = _read("src/video_agent/core/agent_loop.py")
    assert '{"type": SSE_STATUS, "text":' not in src
