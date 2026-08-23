"""tool_args_preview 裁剪脱敏纯函数域（任务 #2 时间线分级展开）。

钉死契约：
① document_write.content 长文本只留前 300 字预览（全文不出后端）；
② base64/data_uri 媒体负载键与 data: URI 值一律剔除为占位符；
③ 整体 args JSON 体积上限（超限降档截断/裁字段）；
④ 不修改调用方原 args（返回新 dict）；
⑤ 裸 base64 值形状启发式（FIX-6）：长≥128 且前 512 字符全为 base64
   字母表的字符串剔除；中文创作提示词/代码片段不误伤。
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


# ---------- ⑤ 裸 base64 值形状启发式（FIX-6） ----------


def test_bare_base64_under_generic_key_redacted():
    """通用键名下无 data: 前缀的裸 base64：长≥128 即剔除（不外泄截断预览）。"""
    payload = "iVBORw0KGgoAAAANSUhEUg" * 20  # 440 字纯 base64 字母表
    out = redact_tool_args("some_tool", {"content": payload})
    assert out["content"] == REDACTED_PLACEHOLDER
    # MIME 分块形态（含换行空白）同口径剔除
    chunked = "\n".join("QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" for _ in range(10))
    out2 = redact_tool_args("some_tool", {"field": chunked})
    assert out2["field"] == REDACTED_PLACEHOLDER


def test_short_base64_like_string_not_redacted():
    """长度 <128 不触发启发式（短值非媒体负载，保留原值）。"""
    out = redact_tool_args("some_tool", {"content": "iVBORw0KGgoAAAANSUhEUg"})
    assert out["content"] == "iVBORw0KGgoAAAANSUhEUg"


def test_long_chinese_prompt_not_false_positive():
    """中文创作提示词（长文）不误判为 base64：走截断预览而非剔除。"""
    prompt = "请生成一个赛博朋克风格的未来城市夜景镜头，" * 20  # 440 字
    out = redact_tool_args("write_media_prompt", {"prompt": prompt})
    assert out["prompt"] != REDACTED_PLACEHOLDER
    assert out["prompt"].startswith(prompt[:PREVIEW_CHAR_LIMIT])


def test_long_code_snippet_not_false_positive():
    """代码片段（含括号/引号等标点）不误判：保留截断预览。"""
    snippet = "def f(x):\n    return {'k': x + 1}\n" * 20  # 680 字含标点
    out = redact_tool_args("document_write", {"content": snippet})
    assert out["content"] != REDACTED_PLACEHOLDER
    assert out["content"].startswith(snippet[:PREVIEW_CHAR_LIMIT])
