"""tool_args_preview 裁剪脱敏纯函数域（任务 #2 时间线分级展开）。

钉死契约：
① document_write.content 长文本只留前 300 字预览（全文不出后端）；
② base64/data_uri 媒体负载键与 data: URI 值一律剔除为占位符；
③ 整体 args JSON 体积上限（超限降档截断/裁字段）；
④ 不修改调用方原 args（返回新 dict）。
"""
from src.video_agent.core.tool_args_preview import (
    MAX_ARGS_JSON_BYTES, PREVIEW_CHAR_LIMIT, REDACTED_PLACEHOLDER,
    redact_tool_args, truncate_text,
)


def test_long_content_truncated_to_preview():
    content = "剧本正文" * 500  # 2000 字
    out = redact_tool_args("document_write", {"name": "剧本.md", "content": content})
    assert out["name"] == "剧本.md"
    assert len(out["content"]) < len(content)
    assert out["content"].startswith(content[:PREVIEW_CHAR_LIMIT])
    assert "已截断" in out["content"] and "2000" in out["content"]


def test_short_content_kept_intact():
    out = redact_tool_args("document_write", {"name": "a.md", "content": "短内容"})
    assert out["content"] == "短内容"


def test_base64_and_data_uri_redacted():
    out = redact_tool_args("view_storyboard_media", {
        "image_base64": "iVBORw0KGgoAAAANSUhEUg" * 20,
        "data_uri": "data:image/png;base64,AAA",
        "items": [{"b64_payload": "xxx", "title": "镜头1"}],
        "media": "data:image/jpeg;base64,/9j/4AAQ",
        "name": "预览",
    })
    assert out["image_base64"] == REDACTED_PLACEHOLDER
    assert out["data_uri"] == REDACTED_PLACEHOLDER
    assert out["items"][0]["b64_payload"] == REDACTED_PLACEHOLDER
    assert out["items"][0]["title"] == "镜头1"
    assert out["media"] == REDACTED_PLACEHOLDER
    assert out["name"] == "预览"


def test_total_json_size_within_budget():
    args = {f"field_{i}": "长" * 400 for i in range(20)}
    out = redact_tool_args("canvas_batch_add_nodes", args)
    import json
    size = len(json.dumps(out, ensure_ascii=False, default=str).encode("utf-8"))
    assert size <= MAX_ARGS_JSON_BYTES


def test_original_args_not_mutated():
    args = {"content": "x" * 900, "image_base64": "AAA"}
    snapshot = dict(args)
    redact_tool_args("document_write", args)
    assert args == snapshot


def test_empty_and_non_dict_args():
    assert redact_tool_args("document_write", {}) == {}
    assert redact_tool_args("document_write", None) == {}  # type: ignore[arg-type]


def test_truncate_text_helper():
    assert truncate_text("abc") == "abc"
    out = truncate_text("a" * 301)
    assert out.startswith("a" * PREVIEW_CHAR_LIMIT)
    assert "共 301 字" in out
