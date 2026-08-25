# -*- coding: utf-8 -*-
"""整改批 3.2：SSE 载荷编译期契约钉死。

① 在役事件常量 ↔ TS 导出帧的 type 字面量一一对应（新增事件忘登记即红）；
② 已退役事件（model_fallback 发射端删除 / step_started 内部事件）不得回流；
③ gen_api_types 输出含 SSE 分节且逐帧导出（--check 门禁的内容基础）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.gen_api_types import build_output  # noqa: E402
from src.video_agent.core import sse_events as se  # noqa: E402


def _frame_literals() -> set:
    lits = set()
    for _name, model in se.TS_EVENT_FRAMES:
        t = model.model_json_schema().get("properties", {}).get("type", {})
        v = t.get("const")
        if v is None:
            enum = t.get("enum") or []
            v = enum[0] if enum else None
        if v is not None:
            lits.add(v)
    return lits


def test_every_live_event_constant_has_frame():
    """在役事件常量全部有导出帧且字面量一致。"""
    live = {
        se.SSE_STATUS, se.SSE_DELTA, se.SSE_REASONING_DELTA,
        se.SSE_TOOL_STARTED, se.SSE_TOOL_FINISHED, se.SSE_DOC_WRITTEN,
        se.SSE_DONE, se.SSE_STOPPED, se.SSE_ERROR,
        se.SSE_ACTIONS_APPLIED, se.SSE_GUIDANCE_INJECTED,
        "replay", "task_status",          # 任务流传输层合成帧
    }
    missing = live - _frame_literals()
    assert not missing, f"在役事件缺 TS 导出帧: {sorted(missing)}"


def test_retired_or_internal_events_not_exported():
    """model_fallback 发射端已退役；step_started 为内部事件不透传——
    二者不得出现在前端契约面（防退役回流/内部泄漏）。"""
    exported = _frame_literals()
    assert se.SSE_MODEL_FALLBACK not in exported
    assert se.SSE_STEP_STARTED not in exported


def test_generated_output_contains_sse_section_and_all_frames():
    out = build_output()
    assert "SSE 事件载荷" in out
    for name, _model in se.TS_EVENT_FRAMES:
        assert f"export interface {name}" in out, f"{name} 未导出"
    # 判别列必须是必填字面量（联合类型收窄的前提）
    done_block = out.split("export interface SseDoneEvent", 1)[1]
    done_block = done_block.split("}", 1)[0]
    assert "type: 'done';" in done_block