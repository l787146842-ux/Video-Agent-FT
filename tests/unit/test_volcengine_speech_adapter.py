"""火山豆包语音 V3 适配器单测（2026-10-29）。

覆盖：凭据解析（新版 API Key / 旧版 appid|token 双头）、鉴权头二选一、
音色设计（speaker_id + demo_audio 下载 + 状态异常）、音频生成（base64/URL 二选一）、
语音合成（speaker 映射）、长度校验、跨通道拒绝。
"""
import base64

import pytest

from src.video_agent.adapters.volcengine_speech import (
    DEFAULT_AUDIO_MODEL,
    VolcengineSpeechAdapter,
    parse_credentials,
)
from src.video_agent.exceptions import AdapterError

BASE = "https://openspeech.bytedance.com"
B64 = base64.b64encode(b"RIFF-audio").decode()


class _Resp:
    def __init__(self, payload=None, status=200, content=b""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)
        self.content = content
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class _Client:
    """同一个 client 既接 POST（业务）也接 GET（预览音频下载）。"""

    def __init__(self, post_resp, get_resp=None):
        self.post_resp = post_resp
        self.get_resp = get_resp
        self.calls = []

    async def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json, headers or {}))
        return self.post_resp

    async def get(self, url):
        self.calls.append(("GET", url, None, {}))
        return self.get_resp or _Resp(content=b"mp3-preview")


def _adapter(post_resp, *, key="sk-api-key", get_resp=None, appid=""):
    adapter = VolcengineSpeechAdapter(BASE, key, appid=appid)
    client = _Client(post_resp, get_resp)
    adapter._client = client
    return adapter, client


# ---------- 凭据与鉴权头 ----------

def test_parse_credentials_both_styles():
    # 新版 API Key：没有分隔符 → 纯 key，没有 appid
    assert parse_credentials("sk-abc") == ("sk-abc", "")
    # 旧版 appid|token（第三段 cluster 不再使用）
    assert parse_credentials("app123|tok-abc") == ("tok-abc", "app123")
    assert parse_credentials("app123|tok-abc|volcano_tts") == ("tok-abc", "app123")
    assert parse_credentials("", "appid-from-config") == ("", "appid-from-config")


def test_headers_switch_between_new_and_old_auth():
    new_adapter, _ = _adapter(_Resp(), key="sk-new")
    headers = new_adapter._headers()
    assert headers["X-Api-Key"] == "sk-new"
    assert "X-Api-App-Key" not in headers
    assert headers["X-Api-Request-Id"]  # 必须带请求 id

    old_adapter, _ = _adapter(_Resp(), key="app123|tok-old")
    headers = old_adapter._headers()
    assert headers["X-Api-App-Key"] == "app123"
    assert headers["X-Api-Access-Key"] == "tok-old"
    assert "X-Api-Key" not in headers


# ---------- 音色设计 ----------

async def test_design_voice_posts_prompt_and_downloads_preview(monkeypatch):
    adapter, client = _adapter(_Resp({
        "speaker_id": "S_new123",
        "status": 2,
        "demo_audio": "https://cdn/demo.mp3?x-expires=1",
    }))
    out = await adapter.design_voice(
        target_model="voice-design",
        voice_prompt="低沉沙哑的中年男声",
        preview_text="夜色渐浓，城市的灯火次第亮起。",
        speaker_id="S_slot1",
    )
    method, url, body, _ = client.calls[0]
    assert method == "POST" and url.endswith("/api/v3/tts/voice_design")
    assert body["prompt"]["text_prompt"] == "低沉沙哑的中年男声"
    assert body["speaker_id"] == "S_slot1"
    assert body["language"] == 0
    assert out.voice_id == "S_new123"
    assert out.preview_audio == b"mp3-preview"
    assert out.response_format == "mp3"      # 按预览 URL 后缀回报真实格式


async def test_design_voice_rejects_overlong_voice_prompt():
    adapter, client = _adapter(_Resp())
    with pytest.raises(AdapterError, match="音色描述最长 200 字"):
        await adapter.design_voice(
            target_model="voice-design", voice_prompt="长" * 201,
            preview_text="试听文本一句。")
    assert client.calls == [], "超长必须在发请求前拦下"


async def test_design_voice_without_demo_audio_reports_pending():
    """status=Training 时没有 demo_audio：报「尚未就绪」，不假装成功。"""
    adapter, _ = _adapter(_Resp({"speaker_id": "S_x", "status": 1}))
    with pytest.raises(AdapterError, match="尚未就绪"):
        await adapter.design_voice(
            target_model="voice-design", voice_prompt="少女音",
            preview_text="试听文本一句。")


# ---------- 音频生成（音效 / 合成） ----------

async def test_generate_sfx_prefers_inline_base64():
    adapter, client = _adapter(_Resp({"audio": B64, "duration": 3.5}))
    out = await adapter.generate_sfx(
        model=DEFAULT_AUDIO_MODEL, text_prompt="玻璃碎裂",
        audio_format="wav", sample_rate=24000)
    _, url, body, _ = client.calls[0]
    assert url.endswith("/api/v3/tts/create")
    assert body["model"] == DEFAULT_AUDIO_MODEL
    assert body["text_prompt"] == "玻璃碎裂"
    assert "speaker" not in body, "音效是纯文本生成，不能带 speaker"
    assert body["audio_config"]["format"] == "wav"
    assert out.audio_bytes == b"RIFF-audio"
    assert out.duration == 3.5


async def test_generate_sfx_falls_back_to_url():
    adapter, _ = _adapter(_Resp({"url": "https://cdn/x.wav", "duration": 1.0}))
    out = await adapter.generate_sfx(model=DEFAULT_AUDIO_MODEL, text_prompt="雨声")
    assert out.audio_url == "https://cdn/x.wav"
    assert out.audio_bytes == b""


async def test_generate_sfx_passes_reference_audio_as_base64():
    adapter, client = _adapter(_Resp({"audio": B64}))
    await adapter.generate_sfx(
        model=DEFAULT_AUDIO_MODEL, text_prompt="跟着参考音频延长",
        references=["data:audio/wav;base64,QUJD"])
    _, _, body, _ = client.calls[0]
    assert body["audio_data"] == "QUJD"
    assert "audio_url" not in body


async def test_synthesize_maps_voice_id_to_speaker():
    adapter, client = _adapter(_Resp({"audio": B64, "duration": 1.2}))
    out = await adapter.synthesize(
        model=DEFAULT_AUDIO_MODEL, text="你好世界",
        voice_id="zh_female_x", speed=1.5, audio_format="mp3")
    _, _, body, _ = client.calls[0]
    assert body["speaker"] == "zh_female_x"
    assert body["text_prompt"] == "你好世界"
    # speed 1.5 → speech_rate 50（火山口径：50 表示 1.5 倍速）
    assert body["audio_config"]["speech_rate"] == 50
    assert out.audio_bytes == b"RIFF-audio"


async def test_synthesize_requires_voice_id():
    adapter, client = _adapter(_Resp())
    with pytest.raises(AdapterError, match="voice_id"):
        await adapter.synthesize(model=DEFAULT_AUDIO_MODEL, text="你好", voice_id=" ")
    assert client.calls == []


async def test_music_channel_is_rejected():
    adapter, _ = _adapter(_Resp())
    with pytest.raises(AdapterError, match="不提供音乐生成接口"):
        await adapter.generate_music(model="seed-audio-1.0", prompt="轻快")


async def test_error_envelope_on_http_200():
    adapter, _ = _adapter(_Resp({"code": 45001001, "message": "请求参数有误"}))
    with pytest.raises(AdapterError, match="请求参数有误"):
        await adapter.synthesize(
            model=DEFAULT_AUDIO_MODEL, text="你好", voice_id="zh_female_x")
