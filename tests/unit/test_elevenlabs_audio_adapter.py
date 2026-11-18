"""ElevenLabs 适配器单测（2026-10-29）。

覆盖：xi-api-key 鉴权、base_url 归一到 /v1、output_format 映射（wav→mp3 降级）、
音色设计（100-1000 字走 text，否则 auto_generate_text；保存音色失败不阻断）、
音效与合成返回二进制、音乐通道拒绝。
"""
import base64

import pytest

from src.video_agent.adapters.elevenlabs_audio import (
    ElevenLabsAudioAdapter,
    actual_format,
    output_format_for,
)
from src.video_agent.exceptions import AdapterError

B64 = base64.b64encode(b"ID3-preview").decode()


class _Resp:
    def __init__(self, payload=None, status=200, content=b"ID3-audio"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)
        self.content = content
        self.headers = {"content-type": "audio/mpeg"}

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses):
        # 按顺序返回（音色设计需要 design + create 两次 POST）
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, url, json=None, params=None):
        self.calls.append((method, url, json, params))
        if not self.responses:
            return _Resp()
        return self.responses.pop(0)

    async def aclose(self):
        pass


def _adapter(*responses, base="https://api.elevenlabs.io/v1"):
    adapter = ElevenLabsAudioAdapter(base, "xi-test-key")
    client = _Client(responses)
    adapter._client = client
    return adapter, client


def test_root_normalizes_base_url():
    for base in (
        "https://api.elevenlabs.io",
        "https://api.elevenlabs.io/",
        "https://api.elevenlabs.io/v1",
        "https://api.elevenlabs.io/v1/models",
    ):
        adapter = ElevenLabsAudioAdapter(base, "k")
        assert adapter._root == "https://api.elevenlabs.io/v1", base


def test_output_format_mapping():
    # 平台没有 wav，wav 请求降级 mp3（并回报真实格式，避免扩展名撒谎）
    assert output_format_for("wav") == "mp3_44100_128"
    assert output_format_for("mp3") == "mp3_44100_128"
    assert output_format_for("pcm", 24000) == "pcm_24000"
    assert output_format_for("pcm", 12345) == "pcm_24000"   # 非法采样率回落
    assert actual_format("wav") == "mp3"
    assert actual_format("pcm") == "pcm"


def test_auth_header_is_xi_api_key():
    # 真实 client（不经假 client）验鉴权头：ElevenLabs 不认 Authorization: Bearer
    adapter = ElevenLabsAudioAdapter("https://api.elevenlabs.io/v1", "xi-test-key")
    assert adapter._get_client().headers["xi-api-key"] == "xi-test-key"


# ---------- 语音合成 ----------

async def test_synthesize_returns_bytes_and_real_format():
    adapter, client = _adapter(_Resp(content=b"ID3-audio"))
    out = await adapter.synthesize(
        model="eleven_multilingual_v2", text="你好", voice_id="voice-1",
        audio_format="wav")
    method, url, body, params = client.calls[0]
    assert method == "POST"
    assert url.endswith("/v1/text-to-speech/voice-1")
    assert body["text"] == "你好"
    assert body["model_id"] == "eleven_multilingual_v2"
    assert params["output_format"] == "mp3_44100_128"
    assert out.audio_bytes == b"ID3-audio"
    assert out.audio_format == "mp3", "请求 wav 实际是 mp3，必须回报真实格式"


async def test_synthesize_requires_voice_id():
    adapter, client = _adapter()
    with pytest.raises(AdapterError, match="voice_id"):
        await adapter.synthesize(model="m", text="你好", voice_id="  ")
    assert client.calls == []


async def test_synthesize_maps_speed_into_voice_settings():
    adapter, client = _adapter(_Resp())
    await adapter.synthesize(model="m", text="t", voice_id="v", speed=1.3)
    _, _, body, _ = client.calls[0]
    assert body["voice_settings"]["speed"] == 1.3

    adapter2, client2 = _adapter(_Resp())
    await adapter2.synthesize(model="m", text="t", voice_id="v", speed=1.0)
    _, _, body2, _ = client2.calls[0]
    assert "voice_settings" not in body2, "原速不传，保持音色默认"


# ---------- 音效 ----------

async def test_generate_sfx_posts_text():
    adapter, client = _adapter(_Resp(content=b"ID3-sfx"))
    out = await adapter.generate_sfx(model="eleven-sound-effects", text_prompt="玻璃碎裂")
    _, url, body, _ = client.calls[0]
    assert url.endswith("/v1/sound-generation")
    assert body["text"] == "玻璃碎裂"
    assert out.audio_bytes == b"ID3-sfx"


async def test_music_channel_is_rejected():
    adapter, _ = _adapter()
    with pytest.raises(AdapterError, match="不提供音乐生成接口"):
        await adapter.generate_music(model="m", prompt="轻快")


# ---------- 音色列表 ----------

async def test_list_voices_returns_ids_and_preview():
    """GET /v1/voices：取 voice_id / name / preview_url，缺 id 的条目跳过。"""
    payload = {"voices": [
        {"voice_id": "v-1", "name": "Rachel", "preview_url": "https://x/p.mp3",
         "category": "premade"},
        {"voice_id": "  ", "name": "空 id 应跳过"},
        {"name": "没有 id"},
    ]}
    adapter, client = _adapter(_Resp(payload))
    out = await adapter.list_voices(model="eleven_v3")
    method, url, _, params = client.calls[0]
    assert method == "GET"
    assert url.endswith("/v1/voices")
    assert params == {"page_size": 100}
    assert out == [{
        "voice_id": "v-1", "name": "Rachel",
        "preview_url": "https://x/p.mp3", "category": "premade",
    }]


async def test_list_voices_bad_shape_is_readable():
    adapter, _ = _adapter(_Resp({"voices": "not-a-list"}))
    with pytest.raises(AdapterError, match="voices 不是数组"):
        await adapter.list_voices()


async def test_base_list_voices_unsupported_is_readable():
    """未接列表接口的平台（百炼/火山）由基类明确报错，不返回空列表。"""
    from src.video_agent.adapters.dashscope_audio import DashScopeAudioAdapter

    adapter = DashScopeAudioAdapter("https://dashscope.aliyuncs.com", "k")
    with pytest.raises(AdapterError, match="不支持拉取音色列表"):
        await adapter.list_voices(model="cosyvoice-v3.5-plus")


# ---------- 音色设计 ----------

async def test_design_voice_long_text_creates_persistent_voice():
    preview = {"previews": [{"generated_voice_id": "gen-abc", "audio_base_64": B64}]}
    created = {"voice_id": "voice-new"}
    adapter, client = _adapter(_Resp(preview), _Resp(created))
    out = await adapter.design_voice(
        target_model="eleven_multilingual_ttv_v2",
        voice_prompt="低沉男声", preview_text="长" * 120, prefix="fd")
    _, design_url, design_body, _ = client.calls[0]
    assert design_url.endswith("/v1/text-to-voice/design")
    assert design_body["text"] == "长" * 120, "100-1000 字正常当试听文本"
    assert "auto_generate_text" not in design_body
    _, create_url, create_body, _ = client.calls[1]
    assert create_url.endswith("/v1/text-to-voice")
    assert create_body["generated_voice_id"] == "gen-abc"
    assert create_body["voice_name"].startswith("fd-")
    assert out.voice_id == "voice-new"
    assert out.preview_audio == b"ID3-preview"
    assert out.status == "success"


async def test_design_voice_short_text_uses_auto_generate():
    preview = {"previews": [{"generated_voice_id": "gen-1", "audio_base_64": B64}]}
    adapter, client = _adapter(_Resp(preview), _Resp({"voice_id": "v"}))
    await adapter.design_voice(
        target_model="eleven_multilingual_ttv_v2",
        voice_prompt="低沉男声", preview_text="太短了")
    _, _, body, _ = client.calls[0]
    assert body["auto_generate_text"] is True
    assert "text" not in body


async def test_design_voice_create_failure_keeps_preview():
    preview = {"previews": [{"generated_voice_id": "gen-1", "audio_base_64": B64}]}
    adapter, _ = _adapter(_Resp(preview), _Resp({"detail": "boom"}, status=403))
    out = await adapter.design_voice(
        target_model="m", voice_prompt="低沉男声", preview_text="长" * 120)
    # 保存失败不阻断：仍返回预览音频，voice_id 回落到生成的临时 id
    assert out.preview_audio == b"ID3-preview"
    assert out.voice_id == "gen-1"
    assert out.status == "preview_only"


async def test_design_voice_403_paid_plan_is_readable():
    """免费套餐调 API 建音色 → 403 feature_not_available，错误要能看懂。"""
    adapter, _ = _adapter(_Resp(
        {"detail": {"code": "feature_not_available",
                    "message": "Creating a voice through the API is only available on a paid plan."}},
        status=403))
    with pytest.raises(AdapterError, match="paid plan"):
        await adapter.design_voice(
            target_model="m", voice_prompt="低沉男声", preview_text="长" * 120)
