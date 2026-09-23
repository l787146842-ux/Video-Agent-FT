"""Seedance 2.0 MultiModalToVideo 媒体列表格式 + MMG 中转站格式 + 分镜参考自动挂接"""
import json

import httpx
import pytest

from src.video_agent.adapters import video_compat
from src.video_agent.adapters.video_compat import OpenAICompatVideoAdapter
from src.video_agent.exceptions import AdapterError
from src.video_agent.web.generation import collect_shot_video_refs, is_audio_url


def _adapter_with_handler(handler, video_request_mode="classic"):
    """构造注入 MockTransport 的适配器（捕获请求体做断言）"""
    adapter = OpenAICompatVideoAdapter(
        base_url="http://test.local/v1", api_key="k", model="m",
        video_request_mode=video_request_mode,
    )
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=adapter.base_url
    )
    return adapter


@pytest.mark.asyncio
async def test_media_refs_uses_seedance_multimodal_format():
    """有参考素材时：走 /contents/generations/tasks + content 数组（多参考图+音频）"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "task-123"})

    adapter = _adapter_with_handler(handler)
    resp = await adapter.generate(
        prompt="镜头一：中景，侦探推门而入。no subtitles, no music",
        media_refs=[
            {"url": "http://img/hero.png", "kind": "image", "role": "first_frame"},
            {"url": "http://img/office.png", "kind": "image", "role": "reference"},
            {"url": "http://aud/voice.mp3", "kind": "audio", "role": "reference_audio"},
        ],
        duration=10, resolution="720p", aspect_ratio="16:9",
    )
    assert resp.task_id == "task-123" and resp.status == "processing"
    assert captured["path"] == "/v1/contents/generations/tasks"
    body = captured["body"]
    assert body["model"] == "m"
    assert body["duration"] == 10 and body["ratio"] == "16:9"
    content = body["content"]
    assert content[0] == {"type": "text", "text": "镜头一：中景，侦探推门而入。no subtitles, no music"}
    images = [c for c in content if c["type"] == "image_url"]
    audios = [c for c in content if c["type"] == "audio_url"]
    assert len(images) == 2
    assert images[0]["role"] == "first_frame"
    # reference 归一化为 Seedance 的 reference_image
    assert images[1]["role"] == "reference_image"
    assert len(audios) == 1 and audios[0]["role"] == "reference_audio"
    assert audios[0]["audio_url"]["url"] == "http://aud/voice.mp3"


@pytest.mark.asyncio
async def test_no_media_refs_keeps_legacy_format():
    """无参考素材时：保持经典 /videos/generations + input.img_url 格式"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"task_id": "t-9"})

    adapter = _adapter_with_handler(handler)
    await adapter.generate(image_url="http://img/frame.png", prompt="推进镜头")
    assert captured["path"] == "/v1/videos/generations"
    assert captured["body"]["input"] == {"prompt": "推进镜头", "img_url": "http://img/frame.png"}


def test_normalize_media_refs_legacy_first_frame_compat():
    """经典首帧参数未出现在 media_refs 时自动前置为 first_frame（升级不回退）"""
    refs = OpenAICompatVideoAdapter._normalize_media_refs(
        [{"url": "http://img/b.png", "kind": "image", "role": "reference"}],
        "http://img/a.png",
    )
    assert refs[0] == {"url": "http://img/a.png", "kind": "image", "role": "first_frame"}
    assert refs[1]["role"] == "reference_image"
    # 去重：同一 URL 不重复
    refs2 = OpenAICompatVideoAdapter._normalize_media_refs(
        [{"url": "http://img/a.png", "kind": "image", "role": "first_frame"}],
        "http://img/a.png",
    )
    assert len(refs2) == 1
    # 音频按扩展名自动识别 kind
    refs3 = OpenAICompatVideoAdapter._normalize_media_refs(
        [{"url": "http://aud/v.mp3"}], "",
    )
    assert refs3[0]["kind"] == "audio" and refs3[0]["role"] == "reference_audio"


def test_is_audio_url():
    assert is_audio_url("http://x/a.mp3")
    assert is_audio_url("/workspace/assets/voice.WAV?token=1")
    assert not is_audio_url("http://x/a.png")
    assert not is_audio_url("")


def test_collect_shot_video_refs_scene_images_and_timbre_audio():
    """分镜参考自动挂接：shotRefs 元素概念图 + refAssets/audioUrl 音色参考音频"""
    state = {
        "keyElements": [
            {"id": "ke-1", "title": "Element_侦探", "drafts": [
                {"id": "d-ke1", "imgUrl": "http://img/hero.png"},
            ]},
            {"id": "ke-2", "title": "Element_办公室", "drafts": [
                {"id": "d-ke2", "imgUrl": "http://img/office.png"},
            ]},
        ],
        "shots": [],
        "audioItems": [],
    }
    group = {"id": "shot-1", "shotRefs": ["Element_侦探", "Element_办公室"]}
    draft = {
        "id": "d-shot1",
        "refAssets": ["http://aud/voice.mp3", "http://img/extra.png"],
        "audioUrl": "http://aud/voice.mp3",  # 与 refAssets 重复，应去重
    }
    images, audios = collect_shot_video_refs(state, group, draft)
    assert [r["url"] for r in images] == ["http://img/hero.png", "http://img/office.png"]
    assert all(r["role"] == "reference" for r in images)
    assert len(audios) == 1
    assert audios[0] == {"url": "http://aud/voice.mp3", "role": "reference_audio"}


def test_collect_shot_video_refs_no_shot_refs():
    """无 shotRefs 时只挂音色参考音频"""
    draft = {"id": "d-1", "refAssets": [], "audioUrl": "http://aud/timbre.m4a"}
    images, audios = collect_shot_video_refs({}, None, draft)
    assert images == []
    assert [a["url"] for a in audios] == ["http://aud/timbre.m4a"]


@pytest.mark.asyncio
async def test_openai_mode_mmg_submit_format():
    """openai 模式（MMG）：POST /videos + 幂等键头 + 参考素材 Base64 内联，非法时长取最近合法值"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "img" and request.url.path in ("/frame.png", "/ref2.png"):
            # 远程参考素材由本服务先下载内联（提交前校验可访问性）
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nfake-png",
                                  headers={"content-type": "image/png"})
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        captured["idem"] = request.headers.get("Idempotency-Key", "")
        return httpx.Response(200, json={"id": "task_abc123", "status": "queued"})

    adapter = _adapter_with_handler(handler, video_request_mode="openai")
    resp = await adapter.generate(
        image_url="https://img/frame.png",
        prompt="镜头缓慢推进，少女转身看向镜头",
        media_refs=[
            {"url": "https://img/frame.png", "kind": "image", "role": "first_frame"},
            {"url": "https://img/ref2.png", "kind": "image", "role": "reference"},
            {"url": "/workspace/assets/local.png", "kind": "image", "role": "reference"},  # 本地素材应被跳过
        ],
        duration=6, resolution="720p", aspect_ratio="16:9",
    )
    assert resp.task_id == "task_abc123" and resp.status == "processing"
    assert captured["path"] == "/v1/videos"
    assert captured["idem"].startswith("video_")
    body = captured["body"]
    assert body["model"] == "m"
    assert body["duration"] == 5  # 6 → 最近合法值 5
    assert body["aspect_ratio"] == "9:16"  # 16:9 → 强制 9:16
    assert body["resolution"] == "720p"
    # 远程/本地素材统一转 Base64 内联，不把可能过期的外链透传给 MMG
    assert "reference_urls" not in body
    refs = body.get("references") or []
    assert len(refs) == 2
    assert all(ref.startswith("data:image/png;base64,") for ref in refs)


@pytest.mark.asyncio
async def test_openai_mode_mmg_dead_remote_ref_raises_clear_error():
    """openai 模式（MMG）：参考素材外链已失效（HTTP 404）时，提交前给出明确错误"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "img" and request.url.path == "/dead.png":
            return httpx.Response(404)
        return httpx.Response(500)

    adapter = _adapter_with_handler(handler, video_request_mode="openai")
    with pytest.raises(AdapterError) as exc_info:
        await adapter.generate(
            prompt="人物走向镜头",
            media_refs=[
                {"url": "https://img/dead.png", "kind": "image", "role": "reference"},
            ],
            duration=5, resolution="720p", aspect_ratio="9:16",
        )
    msg = str(exc_info.value)
    assert "参考素材无法下载" in msg and "https://img/dead.png" in msg and "404" in msg


@pytest.mark.asyncio
async def test_openai_mode_mmg_poll_and_download(tmp_path, monkeypatch):
    """openai 模式：轮询 GET /videos/{id}，completed 后经 /content 下载到本地素材目录"""
    monkeypatch.setattr(video_compat, "ASSETS_DIR", tmp_path)
    mp4_bytes = b"\x00" * 2048  # >1KB 才算有效

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/videos/task_abc123":
            return httpx.Response(200, json={
                "id": "task_abc123", "object": "video",
                "status": "completed", "progress": 100,
                "video_url": "https://internal/should-be-ignored.mp4",  # 兼容字段应被忽略
            })
        if request.url.path == "/v1/videos/task_abc123/content":
            return httpx.Response(200, content=mp4_bytes,
                                  headers={"content-type": "video/mp4"})
        return httpx.Response(404)

    adapter = _adapter_with_handler(handler, video_request_mode="openai")
    resp = await adapter.fetch_result("task_abc123")
    assert resp.status == "completed"
    assert resp.video_url.startswith("/workspace/assets/video_task_abc123_")
    # 文件确实落盘
    saved = [p for p in tmp_path.iterdir() if p.suffix == ".mp4"]
    assert len(saved) == 1 and saved[0].read_bytes() == mp4_bytes


@pytest.mark.asyncio
async def test_openai_mode_mmg_content_not_ready_keeps_processing(monkeypatch):
    """completed 但 /content 返回 502（成片未就绪）：继续轮询而非失败"""
    async def _fast_sleep(_s):
        return None
    monkeypatch.setattr("asyncio.sleep", _fast_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/videos/task_x":
            return httpx.Response(200, json={"id": "task_x", "status": "completed"})
        return httpx.Response(503)

    adapter = _adapter_with_handler(handler, video_request_mode="openai")
    resp = await adapter.fetch_result("task_x")
    assert resp.status == "processing"


@pytest.mark.asyncio
async def test_openai_mode_mmg_failed_error_message():
    """failed 状态：提取 error.message（MMG 的 error 是对象）"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "task_y", "status": "failed",
            "error": {"code": "task_failed", "message": "参考图下载失败"},
        })

    adapter = _adapter_with_handler(handler, video_request_mode="openai")
    resp = await adapter.fetch_result("task_y")
    assert resp.status == "failed" and "参考图下载失败" in (resp.error_msg or "")


@pytest.mark.asyncio
async def test_non_json_response_raises_friendly_error():
    """200 但返回 HTML（如网关 SPA 回退）时：抛带现场信息的 AdapterError 而非裸 JSONDecodeError"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<!doctype html><html></html>",
                              headers={"content-type": "text/html"})

    adapter = _adapter_with_handler(handler)
    with pytest.raises(AdapterError) as exc_info:
        await adapter.generate(image_url="http://img/f.png", prompt="x")
    assert "非 JSON" in str(exc_info.value)
