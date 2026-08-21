"""audit-0819d 四维对齐收尾改造钉死回归（ADR-0001 执行记录三）：

1. 适配器 response_format 下发 + 400 兼容探针（剥离字段重试 + 探针记忆）；
2. 执行器严格解析：围栏/正文包裹的 JSON 一律拒收（宽容兜底已删），
   纯 JSON 直达；失败记遥测；
3. 防复活钉死：S17 宽容正则（\[[\s\S]*\] 抠取）不得回到 exec_common。
"""
import json

import pytest

from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.skill_runtime import exec_common


# ---------- 1. 适配器：response_format 下发与兼容探针 ----------

class _FakeResp:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {
            "choices": [{"message": {"content": "{\"ok\": 1}"}, "finish_reason": "stop"}],
        }
        self.text = text or json.dumps(self._body)

    def raise_for_status(self):
        import httpx
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self,  # type: ignore
            )

    def json(self):
        return self._body


class _FakeClient:
    """按脚本逐次返回响应（模拟 400 探针场景）"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.payloads = []
        self.is_closed = False

    async def post(self, url, json=None):
        # 存副本：探针剥离会就地改原 dict，存引用会把历史请求也改掉
        self.payloads.append(dict(json))
        return self._responses.pop(0)

    async def aclose(self):
        self.is_closed = True


@pytest.mark.asyncio
async def test_response_format_in_payload(monkeypatch):
    adapter = OpenAICompatChatAdapter("http://x", model="m")
    client = _FakeClient([_FakeResp()])
    monkeypatch.setattr(adapter, "_get_client", lambda timeout=120: client)
    await adapter.chat([{"role": "user", "content": "hi"}],
                       response_format={"type": "json_object"})
    assert client.payloads[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@pytest.mark.allow_degradation
async def test_response_format_400_probe_strips_and_retries(monkeypatch):
    """端点 400 拒收 response_format → 剥离字段重试一次并记忆（同实例不再下发）"""
    adapter = OpenAICompatChatAdapter("http://x", model="m")
    body_400 = '{"error": "unsupported parameter: response_format"}'
    client = _FakeClient([_FakeResp(400, text=body_400), _FakeResp()])
    monkeypatch.setattr(adapter, "_get_client", lambda timeout=120: client)
    resp = await adapter.chat([{"role": "user", "content": "hi"}],
                              response_format={"type": "json_object"})
    assert resp.content  # 降级重试成功
    assert "response_format" in client.payloads[0]
    assert "response_format" not in client.payloads[1], "探针剥离后重试不得再携带"
    # 探针记忆：第三次调用不再下发
    client._responses.append(_FakeResp())
    await adapter.chat([{"role": "user", "content": "hi"}],
                       response_format={"type": "json_object"})
    assert "response_format" not in client.payloads[2]


# ---------- 2. 执行器严格解析（宽容兜底已删） ----------

def test_strict_parse_accepts_pure_json_array():
    text = '[{"action":"add_group","title":"程心"}]'
    assert exec_common._parse_actions_from_text(text) == [
        {"action": "add_group", "title": "程心"},
    ]


@pytest.mark.allow_degradation
def test_strict_parse_rejects_fenced_json():
    """围栏包裹 = 端点未遵守 json_object：拒收（按零进展交拒因重试），不宽容抠取"""
    text = '```studio-actions\n[{"action":"add_group"}]\n```'
    assert exec_common._parse_actions_from_text(text) == []


@pytest.mark.allow_degradation
def test_strict_parse_rejects_prose_wrapped_json():
    """正文包裹 JSON（旧裸数组正则的宽容对象）同样拒收"""
    text = '好的，结果如下：\n[{"action":"add_group"}]\n以上。'
    assert exec_common._parse_actions_from_text(text) == []


@pytest.mark.allow_degradation
def test_strict_parse_records_degradation_telemetry():
    from src.video_agent.core import live_metrics

    before = sum(
        r["count"] for r in live_metrics.get_degradations()
        if r["point"] == "executor.json_strict_parse_failed"
    )
    exec_common._parse_actions_from_text("not json at all")
    after = sum(
        r["count"] for r in live_metrics.get_degradations()
        if r["point"] == "executor.json_strict_parse_failed"
    )
    assert after == before + 1


# ---------- 3. 防复活钉死 ----------

def test_lenient_array_regex_not_restored():
    r"""S17 拆除留痕：宽容数组抠取正则（\[[\s\S]*\]）不得回到 exec_common"""
    import inspect

    src = inspect.getsource(exec_common)
    assert r"\[[\s\S]*\]" not in src, "宽容数组正则已随 audit-0819d 删除，禁止复活"
    assert "parse_actions_from_reply" not in src, (
        "执行器不得再经 web/action_parser 宽容解析链"
    )


def test_alias_layers_not_restored():
    """S15/S16/确认别名工具拆除留痕：相关符号禁止复活（audit-0819d 用户裁决全删）"""
    import importlib

    agent_loop = importlib.import_module("src.video_agent.core.agent_loop")
    assert not hasattr(agent_loop, "split_actions"), "S16 别名归一已删，禁止复活"
    assert not hasattr(agent_loop, "_extract_confirmation"), "S16 别名归一已删，禁止复活"

    skill_docs = importlib.import_module("src.video_agent.web.skill_docs")
    assert not hasattr(skill_docs, "build_foreign_tool_note"), "S15 工具名翻译层已删，禁止复活"
    assert not hasattr(skill_docs, "FOREIGN_TOOL_MAP"), "S15 工具名翻译层已删，禁止复活"

    doc_tools = importlib.import_module("src.video_agent.tools.document_tools")
    assert not hasattr(doc_tools, "RequestConfirmationTool"), (
        "暂停确认单一正名 = workflow_pause，别名工具禁止复活"
    )
