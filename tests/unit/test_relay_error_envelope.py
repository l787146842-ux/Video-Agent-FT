# -*- coding: utf-8 -*-
"""批 A/B 钉死回归：中继错误信封识别 + 气泡长词换行 + 人话翻译优先级。

1111 二轮事故 lineage：9router 把上游 403/10605 slow 队列拒收缝进 200 流
当「模型内容」，我们适配器见 200 即信 → 垃圾递模型/绿勾/正文裸 JSON 戳出气泡。
批 A 在适配器层识别信封即抛错（retryable=False，不重试）；批 B 气泡强制换行。
"""
from pathlib import Path

import pytest

from src.video_agent.adapters import openai_compat as oc
from src.video_agent.exceptions import AdapterError

ROOT = Path(__file__).resolve().parents[2]

ENVELOPE = (
    '[qoder error 403: {"code":"403","message":"{\\"code\\":\\"10605\\",'
    '\\"message\\":\\"{\\\\\\"isQueued\\\\\\":false,\\\\\\"modelKey\\\\\\":'
    '\\\\\\"qmodel_38max\\\\\\",\\\\\\"queueCount\\\\\\":0,\\\\\\"queueType\\\\\\":\\\\\\"slow\\\\\\"}\\"}]'
)
RAW_QUEUE_JSON = (
    '{"code":"403","message":"{\\"code\\":\\"10605\\",\\"queueType\\":\\"slow\\",'
    '\\"isQueued\\":false}"}'
)


# ---------- 信封识别纯函数 ----------

def test_prefix_envelope_detected():
    assert oc.detect_relay_error_envelope(ENVELOPE) == 403


def test_raw_queue_json_detected():
    assert oc.detect_relay_error_envelope(RAW_QUEUE_JSON) == 403


def test_legit_long_content_not_flagged():
    legit = "角色分析：\n" + ("程心望着远方，" * 500)
    assert oc.detect_relay_error_envelope(legit) is None


def test_legit_bracket_start_not_flagged():
    # 合法稿以方括号开头（列表/引用）但无 error 4xx 形态 → 不误判
    assert oc.detect_relay_error_envelope("[1] 第一幕开场。" * 3) is None
    assert oc.detect_relay_error_envelope("Error 403: 页面不存在（总结）") is None


def test_short_json_without_queue_markers_not_flagged():
    assert oc.detect_relay_error_envelope('{"code":"200","ok":true}') is None


# ---------- 适配器流式路径：信封命中即抛错、不重试 ----------

@pytest.mark.asyncio
async def test_chat_stream_raises_on_envelope(monkeypatch):
    """走真实 _stream_once 解析路径：假 client 吐信封 SSE → 识别抛错"""
    import json as _json

    adapter = oc.OpenAICompatChatAdapter(
        base_url="http://127.0.0.1:1/v1", api_key="k", model="m")

    class _FakeResp:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        async def aiter_lines(self):
            yield "data: " + _json.dumps(
                {"choices": [{"delta": {"content": ENVELOPE}}]})
            yield "data: [DONE]"

        async def aread(self):
            return b""

    class _FakeCM:
        async def __aenter__(self):
            return _FakeResp()

        async def __aexit__(self, *a):
            return False

    class _FakeClient:
        def stream(self, method, path, json=None):
            return _FakeCM()

    monkeypatch.setattr(adapter, "_get_client", lambda timeout: _FakeClient())
    with pytest.raises(AdapterError) as ei:
        async for _ in adapter.chat_stream([{"role": "user", "content": "x"}]):
            pass
    assert ei.value.retryable is False
    assert ei.value.http_status == 403


# test_executor_path_surfaces_generation_error（执行器取稿出口转 GenerationError）
# 已随任务#36 B5 执行器一步退役删除：exec_common.executor_stream_text 不复存在，
# 适配器抛错语义由上方 test_chat_stream_raises_on_envelope 在适配器层钉死。

# ---------- 人话翻译：排队拒收优先于鉴权分支 ----------

def test_friendly_queue_branch_before_auth():
    from src.video_agent.web.chat_service import _friendly_stream_error

    friendly, raw = _friendly_stream_error(
        AdapterError(f"LLM 中继拒收通知单（HTTP 403）: {ENVELOPE[:120]}",
                     retryable=False, http_status=403))
    assert "排队拒收" in friendly
    assert "鉴权失败" not in friendly
    assert raw  # 原文随折叠下发


# ---------- 批 B：气泡长词换行锁源 ----------

def test_chat_markdown_wraps_long_tokens():
    # P4-23：chat.css 拆分为 @import 入口，两条换行规则现居 chat-feed.css（消息流段）
    css = (ROOT / "src/web/styles/chat-feed.css").read_text(encoding="utf-8")
    line = next(l for l in css.splitlines() if l.strip().startswith(".chat-markdown"))
    assert "overflow-wrap: anywhere" in line
    assert "word-break: break-word" in line
    uline = next(l for l in css.splitlines() if ".chat-msg.user .chat-bubble" in l)
    assert "word-break: break-word" in uline
