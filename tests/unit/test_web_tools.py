# -*- coding: utf-8 -*-
"""联网工具（web_search / web_fetch）单测——全程 mock，不真联网。

覆盖：
- 结果塑形 format_search_output：声明/答案/源清单/截断提示/引用指令；
- map_anthropic_response：web_search_tool_result 解析、citation 摘要、
  url 去重、条数封顶置 truncated；
- 多 query 合并 _merge_results：去重封顶；
- WebSearchTool：缺 key 诚实拒执行 / 正常路径（mock httpx）/ 上游失败映射；
- WebFetchTool：url 协议校验 / HTML 转文本 / max_chars 截断 / HTTP 失败。
"""
import httpx
import pytest

from src.video_agent.config import settings
from src.video_agent.tools.web_tools import (
    WEB_SEARCH_MAX_RESULTS,
    WebFetchTool,
    WebSearchTool,
    _html_to_text,
    _merge_results,
    format_search_output,
    map_anthropic_response,
)


# ---------- 塑形 ----------

def test_format_search_output_full_shape():
    text = format_search_output({
        "content": "答案摘要",
        "truncated": True,
        "sources": [
            {"url": "https://a.example/x", "title": "甲", "snippet": "摘要一", "publishedAt": "2 天前"},
            {"url": "https://b.example/y", "title": "", "snippet": "", "publishedAt": ""},
        ],
    })
    assert "外部网络内容" in text
    assert "答案摘要" in text
    assert "- [甲](https://a.example/x) — 摘要一 (2 天前)" in text
    assert "- [https://b.example/y](https://b.example/y)" in text
    assert "只显示了前 2 条" in text
    assert "markdown 链接" in text


def test_format_search_output_empty():
    text = format_search_output({"sources": [], "truncated": False})
    assert "No results found." in text
    assert "外部网络内容" in text


# ---------- Anthropic 响应解析 ----------

def test_map_anthropic_response_parses_and_dedupes():
    payload = {"content": [
        {"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": "https://a", "title": "A", "page_age": "1 天前"},
            {"type": "web_search_result", "url": "https://a", "title": "A dup"},
            {"type": "web_search_result", "url": "https://b", "title": "B"},
        ]},
        {"type": "text", "text": "正文", "citations": [
            {"url": "https://a", "cited_text": "甲的引文"},
        ]},
    ]}
    r = map_anthropic_response(payload, WEB_SEARCH_MAX_RESULTS)
    urls = [s["url"] for s in r["sources"]]
    assert urls == ["https://a", "https://b"]  # 去重保序
    assert r["sources"][0]["snippet"] == "甲的引文"
    assert r["sources"][0]["publishedAt"] == "1 天前"
    assert r["truncated"] is False


def test_map_anthropic_response_caps_and_truncates():
    items = [{"type": "web_search_result", "url": f"https://x/{i}"} for i in range(12)]
    payload = {"content": [{"type": "web_search_tool_result", "content": items}]}
    r = map_anthropic_response(payload, 8)
    assert len(r["sources"]) == 8
    assert r["truncated"] is True


def test_merge_results_dedupes_and_flags():
    merged = _merge_results([
        {"sources": [{"url": "https://a"}, {"url": "https://b"}], "truncated": False, "content": "答案"},
        {"sources": [{"url": "https://b"}, {"url": "https://c"}], "truncated": False, "content": ""},
    ])
    assert [s["url"] for s in merged["sources"]] == ["https://a", "https://b", "https://c"]
    assert merged["content"] == "答案"


# ---------- WebSearchTool ----------

@pytest.fixture
def _no_key():
    object.__setattr__(settings, "web_search_api_key", "")


def _resp(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status, json=payload,
                          request=httpx.Request("POST", "https://fake/messages"))


async def test_search_without_key_fails_honestly(_no_key):
    res = await WebSearchTool().aexecute(WebSearchTool().get_input_schema()(queries=["测试"]))
    assert not res.success
    assert "WEB_SEARCH_API_KEY" in res.error
    assert res.error_code == "validation"


async def test_search_ok_with_mock(monkeypatch):
    object.__setattr__(settings, "web_search_api_key", "sk-test")
    payload = {"content": [
        {"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": "https://a", "title": "A"},
        ]},
        {"type": "text", "text": "摘要答案"},
    ]}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _resp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    res = await WebSearchTool().aexecute(WebSearchTool().get_input_schema()(queries=["DeepSeek 最新模型"]))
    assert res.success
    assert "外部网络内容" in res.data["output"]
    assert "摘要答案" in res.data["output"]
    assert res.data["sources"][0]["url"] == "https://a"


async def test_search_upstream_error_maps_retryable(monkeypatch):
    object.__setattr__(settings, "web_search_api_key", "sk-test")

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _resp({"error": {"message": "配额超限"}}, status=429)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    res = await WebSearchTool().aexecute(WebSearchTool().get_input_schema()(queries=["x"]))
    assert not res.success
    assert res.error_code == "upstream"
    assert res.retryable is True


# ---------- WebFetchTool ----------

async def test_fetch_rejects_non_http_scheme():
    res = await WebFetchTool().aexecute(WebFetchTool().get_input_schema()(url="ftp://x"))
    assert not res.success and res.error_code == "validation"


async def test_fetch_html_to_text_with_truncation(monkeypatch):
    html = "<html><head><style>x{}</style></head><body><p>第一段</p><script>bad()</script><p>第二段</p></body></html>"

    class FakeResp:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = html

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    # 转换后正文约 9 字符（"第一段\n \n第二段"），max_chars=5 触发正文截断
    res = await WebFetchTool().aexecute(WebFetchTool().get_input_schema()(url="https://a", max_chars=5))
    assert res.success
    out = res.data["output"]
    assert "第一段" in out and "bad()" not in out
    assert res.data["truncated"] is True and "内容已截断" in out


async def test_fetch_http_error(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return httpx.Response(
            status_code=404, request=httpx.Request("GET", "https://a"))

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    res = await WebFetchTool().aexecute(WebFetchTool().get_input_schema()(url="https://a"))
    assert not res.success and res.error_code == "upstream"


# ---------- HTML 转文本 ----------

def test_html_to_text_strips_script_and_collapses():
    html = "<div><style>s{}</style><script>var x=1;</script><p>你好</p><p>世界</p></div>"
    text = _html_to_text(html)
    assert "你好" in text and "世界" in text
    assert "var x" not in text and "<" not in text
