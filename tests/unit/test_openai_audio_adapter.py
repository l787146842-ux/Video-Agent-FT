"""OpenAI 兼容音频适配器单测（2026-10-28 多厂商批）。

覆盖：base 归一化、voice=model:voice 拼接、二进制落盘、JSON 错误信封、
429 可重试、非 TTS 通道明确拒绝。
"""
import pytest

from src.video_agent.adapters.openai_audio import OpenAIAudioAdapter, openai_audio_root
from src.video_agent.exceptions import AdapterError


class _Resp:
    def __init__(self, status=200, content=b"ID3-audio", ctype="audio/mpeg", text=""):
        self.status_code = status
        self.content = content
        self.headers = {"content-type": ctype}
        self.text = text


class _Client:
    def __init__(self, resp: _Resp):
        self.resp = resp
        self.calls = []

    async def post(self, url, json):
        self.calls.append((url, json))
        return self.resp


def _adapter(resp: _Resp, *, join=True) -> tuple:
    adapter = OpenAIAudioAdapter(
        "https://api.siliconflow.cn/v1", "sk-test", voice_join_model=join)
    client = _Client(resp)
    adapter._client = client
    return adapter, client


@pytest.mark.parametrize("raw,expected", [
    ("https://api.siliconflow.cn/v1", "https://api.siliconflow.cn/v1"),
    ("https://api.openai.com", "https://api.openai.com/v1"),
    ("https://api.openai.com/", "https://api.openai.com/v1"),
    ("https://ark.cn-beijing.volces.com/api/v3", "https://ark.cn-beijing.volces.com/api/v3"),
    ("", ""),
])
def test_openai_audio_root(raw, expected):
    assert openai_audio_root(raw) == expected


async def test_synthesize_joins_model_and_voice():
    adapter, client = _adapter(_Resp())
    out = await adapter.synthesize(
        model="FunAudioLLM/CosyVoice2-0.5B", text="你好", voice_id="alex",
        audio_format="mp3", sample_rate=32000, speed=1.2,
    )
    url, payload = client.calls[0]
    assert url == "https://api.siliconflow.cn/v1/audio/speech"
    assert payload == {
        "model": "FunAudioLLM/CosyVoice2-0.5B",
        "input": "你好",
        "voice": "FunAudioLLM/CosyVoice2-0.5B:alex",
        "response_format": "mp3",
        "sample_rate": 32000,
        "speed": 1.2,
    }
    assert out.audio_bytes == b"ID3-audio"
    assert out.audio_format == "mp3"


async def test_synthesize_keeps_voice_with_colon():
    adapter, client = _adapter(_Resp())
    await adapter.synthesize(
        model="m", text="t", voice_id="FunAudioLLM/CosyVoice2-0.5B:bella")
    assert client.calls[0][1]["voice"] == "FunAudioLLM/CosyVoice2-0.5B:bella"


async def test_synthesize_requires_voice():
    adapter, _ = _adapter(_Resp())
    with pytest.raises(AdapterError, match="音色"):
        await adapter.synthesize(model="m", text="t", voice_id="  ")


async def test_json_error_envelope_is_adapter_error():
    adapter, _ = _adapter(_Resp(
        status=200, content=b'{"error":{"message":"bad voice"}}',
        ctype="application/json", text='{"error":{"message":"bad voice"}}'))
    with pytest.raises(AdapterError, match="bad voice"):
        await adapter.synthesize(model="m", text="t", voice_id="alex")


async def test_429_is_retryable_and_mentions_status():
    adapter, _ = _adapter(_Resp(status=429, content=b"", ctype="text/plain", text="rate"))
    with pytest.raises(AdapterError) as ei:
        await adapter.synthesize(model="m", text="t", voice_id="alex")
    assert ei.value.http_status == 429
    assert ei.value.retryable is True
    assert "429" in str(ei.value)


async def test_non_tts_channels_rejected():
    adapter, _ = _adapter(_Resp())
    with pytest.raises(AdapterError, match="音色设计"):
        await adapter.design_voice(target_model="m", voice_prompt="p", preview_text="x" * 20)
    with pytest.raises(AdapterError, match="背景音乐"):
        await adapter.generate_music(model="m", prompt="p")
    with pytest.raises(AdapterError, match="音效"):
        await adapter.generate_sfx(model="m", text_prompt="p")
