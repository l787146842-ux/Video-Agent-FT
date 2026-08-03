"""交错多模态内容构建：content_parts 保持文字↔媒体的排版对应关系

P1-6 拆分后多模态构建逻辑位于 multimodal_builder 模块。
"""
import src.video_agent.web.multimodal_builder as cs


async def test_interleaved_text_image_order():
    """文字-图片-文字按顺序交错，图片插在文字之间而非全部追加到末尾"""
    parts = [
        {"type": "text", "text": "请看"},
        {"type": "image", "url": "https://cdn/a.png", "name": "图A"},
        {"type": "text", "text": "的画面"},
    ]
    result = await cs._build_interleaved_content(parts)
    assert isinstance(result, list)
    assert result[0] == {"type": "text", "text": "请看"}
    assert result[1]["type"] == "image_url"
    assert result[1]["image_url"]["url"] == "https://cdn/a.png"
    assert result[2] == {"type": "text", "text": "的画面"}


async def test_video_audio_become_text_markers():
    """视频/音频无法被 vision 直读，转为文本标记并保留交错位置"""
    parts = [
        {"type": "text", "text": "分镜"},
        {"type": "video", "url": "/workspace/v.mp4", "name": "分镜1"},
        {"type": "audio", "url": "/workspace/a.mp3", "name": "配乐"},
    ]
    result = await cs._build_interleaved_content(parts)
    # 无图片注入 → 降级纯文本，但标记保留
    assert isinstance(result, str)
    assert "[video: 分镜1]" in result
    assert "[audio: 配乐]" in result


async def test_video_with_poster_injects_frame_image():
    """视频带首帧海报图时，除标记外额外注入 image_url，让模型「看到」画面"""
    parts = [
        {"type": "text", "text": "看这个"},
        {"type": "video", "url": "/workspace/v.mp4", "name": "分镜1", "thumb": "https://cdn/frame.png"},
    ]
    result = await cs._build_interleaved_content(parts)
    assert isinstance(result, list)
    # 标记文本 + 首帧图片都被注入
    assert any(p.get("type") == "image_url" and p["image_url"]["url"] == "https://cdn/frame.png" for p in result)
    assert any(p.get("type") == "text" and "[video: 分镜1]" in p.get("text", "") for p in result)


async def test_pure_text_degrades_to_string():
    parts = [{"type": "text", "text": "你好"}]
    result = await cs._build_interleaved_content(parts)
    assert result == "你好"


async def test_trailing_note_appended():
    """文档附件说明追加到末尾"""
    parts = [{"type": "text", "text": "正文"}]
    result = await cs._build_interleaved_content(parts, trailing_note="文档全文内容")
    assert "正文" in result
    assert "文档全文内容" in result


async def test_local_image_converted_to_data_uri(monkeypatch):
    """/workspace/ 本地图片转 base64 data URI 注入"""
    monkeypatch.setattr(cs, "_read_image_data_uri", lambda url: "data:image/png;base64,AAA")
    parts = [{"type": "image", "url": "/workspace/assets/a.png", "name": "A"}]
    result = await cs._build_interleaved_content(parts)
    assert isinstance(result, list)
    assert result[0]["image_url"]["url"] == "data:image/png;base64,AAA"


async def test_build_multimodal_prefers_content_parts():
    """build_multimodal_content 有 content_parts 时优先走交错路径"""
    parts = [
        {"type": "text", "text": "图"},
        {"type": "image", "url": "https://cdn/x.png", "name": "X"},
    ]
    result = await cs.build_multimodal_content("被忽略的纯文本", [], [], parts)
    assert isinstance(result, list)
    assert any(p.get("type") == "image_url" for p in result)


async def test_build_multimodal_fallback_without_parts():
    """无 content_parts 时回退原逻辑（无图片 → 纯文本）"""
    result = await cs.build_multimodal_content("你好", [], [])
    assert result == "你好"


async def test_extra_bound_images_appended():
    """已绑定素材图片追加到交错内容末尾"""
    parts = [{"type": "text", "text": "你好"}]
    result = await cs._build_interleaved_content(parts, "", ["https://cdn/bound.png"])
    assert isinstance(result, list)
    assert result[-1]["type"] == "image_url"
    assert result[-1]["image_url"]["url"] == "https://cdn/bound.png"


async def test_build_multimodal_merges_bound_images():
    """content_parts 路径仍注入 images 参数（已绑定素材），不丢失原有能力"""
    parts = [{"type": "text", "text": "你好"}]
    result = await cs.build_multimodal_content("x", [], ["https://cdn/bound.png"], parts)
    assert isinstance(result, list)
    assert any(p.get("type") == "image_url" for p in result)


async def test_build_multimodal_dedupes_inline_and_bound():
    """内联图片与已绑定素材重复时不重复注入"""
    parts = [{"type": "image", "url": "https://cdn/a.png", "name": "A"}]
    result = await cs.build_multimodal_content("x", [], ["https://cdn/a.png"], parts)
    img_count = sum(1 for p in result if p.get("type") == "image_url")
    assert img_count == 1
