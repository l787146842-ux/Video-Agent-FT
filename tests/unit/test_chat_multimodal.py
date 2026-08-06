"""交错多模态内容构建：content_parts 保持文字↔媒体的排版对应关系

P1-6 拆分后多模态构建逻辑位于 multimodal_builder 模块。
"""
import src.video_agent.web.multimodal_builder as cs


def _fake_fetch(url: str):
    """造一个 fetch_remote_image_data_uri 替身：模拟服务端代下载成功"""
    async def _fetch(u: str) -> str:
        if u == url:
            stem = u.rsplit("/", 1)[-1].split(".")[0]
            return f"data:image/png;base64,{stem}"
        return ""
    return _fetch


async def test_interleaved_text_image_order(monkeypatch):
    """文字-图片-文字按顺序交错，图片插在文字之间而非全部追加在末尾"""
    monkeypatch.setattr(cs, "fetch_remote_image_data_uri", _fake_fetch("https://cdn/a.png"))
    parts = [
        {"type": "text", "text": "请看"},
        {"type": "image", "url": "https://cdn/a.png", "name": "图A"},
        {"type": "text", "text": "的画面"},
    ]
    result = await cs._build_interleaved_content(parts)
    assert isinstance(result, list)
    assert result[0] == {"type": "text", "text": "请看"}
    assert result[1]["type"] == "image_url"
    assert result[1]["image_url"]["url"] == "data:image/png;base64,a"
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


async def test_video_with_poster_injects_frame_image(monkeypatch):
    """视频带首帧海报图时，除标记外额外注入 image_url，让模型「看到」画面"""
    monkeypatch.setattr(cs, "fetch_remote_image_data_uri", _fake_fetch("https://cdn/frame.png"))
    parts = [
        {"type": "text", "text": "看这个"},
        {"type": "video", "url": "/workspace/v.mp4", "name": "分镜1", "thumb": "https://cdn/frame.png"},
    ]
    result = await cs._build_interleaved_content(parts)
    assert isinstance(result, list)
    # 标记文本 + 首帧图片（服务端代下载后的 data URI）都被注入
    assert any(p.get("type") == "image_url" and p["image_url"]["url"] == "data:image/png;base64,frame" for p in result)
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


async def test_build_multimodal_prefers_content_parts(monkeypatch):
    """build_multimodal_content 有 content_parts 时优先走交错路径"""
    monkeypatch.setattr(cs, "fetch_remote_image_data_uri", _fake_fetch("https://cdn/x.png"))
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


async def test_extra_bound_images_appended(monkeypatch):
    """已绑定素材图片追加到交错内容末尾（远程图服务端代下载后内联）"""
    monkeypatch.setattr(cs, "fetch_remote_image_data_uri", _fake_fetch("https://cdn/bound.png"))
    parts = [{"type": "text", "text": "你好"}]
    result = await cs._build_interleaved_content(parts, "", ["https://cdn/bound.png"])
    assert isinstance(result, list)
    assert result[-1]["type"] == "image_url"
    assert result[-1]["image_url"]["url"] == "data:image/png;base64,bound"


async def test_build_multimodal_merges_bound_images(monkeypatch):
    """content_parts 路径仍注入 images 参数（已绑定素材），不丢失原有能力"""
    monkeypatch.setattr(cs, "fetch_remote_image_data_uri", _fake_fetch("https://cdn/bound.png"))
    parts = [{"type": "text", "text": "你好"}]
    result = await cs.build_multimodal_content("x", [], ["https://cdn/bound.png"], parts)
    assert isinstance(result, list)
    assert any(p.get("type") == "image_url" for p in result)


async def test_build_multimodal_dedupes_inline_and_bound(monkeypatch):
    """内联图片与已绑定素材重复时不重复注入"""
    monkeypatch.setattr(cs, "fetch_remote_image_data_uri", _fake_fetch("https://cdn/a.png"))
    parts = [{"type": "image", "url": "https://cdn/a.png", "name": "A"}]
    result = await cs.build_multimodal_content("x", [], ["https://cdn/a.png"], parts)
    img_count = sum(1 for p in result if p.get("type") == "image_url")
    assert img_count == 1
