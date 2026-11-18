"""音频生成分发与回写单测（2026-10-28 M1-M3）。

覆盖：
- 通道/模型组合校验（不支持即报错，不静默换模型）；
- 音频落盘与参考音频 data URI 转换；
- 四通道分发（音色设计字节落盘 / 音乐远程 URL 下载落盘）；
- task_manager 回写 audioUrl + voiceId。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.adapters.base import AudioDesignResponse, AudioGenerationResponse
from src.video_agent.adapters.fetch_adapter import FetchResult
from src.video_agent.exceptions import GenerationError
from src.video_agent.web import generation_audio as ga
from src.video_agent.web import task_manager as tm


# ---------- 校验 / 落盘 ----------

def test_check_channel_rejects_mismatched_model():
    cfg = {"audio_models": ["fun-music-v1", "cosyvoice-v3.5-plus"]}
    with pytest.raises(GenerationError, match="不支持"):
        ga._check_channel("p1", cfg, "fun-music-v1", "tts")
    with pytest.raises(GenerationError, match="未知音频通道"):
        ga._check_channel("p1", cfg, "fun-music-v1", "podcast")
    with pytest.raises(GenerationError, match="尚未选择"):
        ga._check_channel("p1", cfg, "", "music")
    ga._check_channel("p1", cfg, "fun-music-v1", "music")  # 合法组合不抛


def test_save_audio_bytes_writes_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "ASSETS_DIR", tmp_path)
    url = ga._save_audio_bytes(b"RIFF", "wav")
    assert url.startswith("/workspace/assets/") and url.endswith(".wav")
    assert (tmp_path / url.rsplit("/", 1)[-1]).read_bytes() == b"RIFF"


def test_save_audio_bytes_empty_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "ASSETS_DIR", tmp_path)
    with pytest.raises(GenerationError, match="没有返回音频"):
        ga._save_audio_bytes(b"", "mp3")


def test_prepare_references_converts_local_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "ASSETS_DIR", tmp_path)
    (tmp_path / "v.wav").write_bytes(b"RIFF")
    refs = ga._prepare_references([
        "/workspace/assets/v.wav",
        "https://cdn/x.wav",
        "/workspace/assets/missing.wav",
        "/workspace/assets/pic.png",
    ])
    assert refs[0].startswith("data:audio/") and ";base64," in refs[0]
    assert refs[1] == "https://cdn/x.wav"
    assert len(refs) == 2, "缺失文件与图片素材都跳过，不阻断主链路"


# ---------- 四通道分发 ----------

class _FakeAdapter:
    last_design: dict = {}
    last_list_model: str = ""

    def __init__(self, base_url, api_key, *, timeout=300.0, **kwargs):
        self.args = (base_url, api_key, timeout)
        self.closed = False

    async def design_voice(self, **kwargs):
        _FakeAdapter.last_design = kwargs
        return AudioDesignResponse(
            voice_id="cosyvoice-v3.5-plus-vd-ann-1",
            preview_audio=b"RIFF-preview", sample_rate=24000,
            response_format="wav", target_model=kwargs.get("target_model", ""),
        )

    async def list_voices(self, *, model: str = ""):
        _FakeAdapter.last_list_model = model
        return [
            {"voice_id": "v-1", "name": "Rachel", "preview_url": "https://x/p.mp3"},
            {"voice_id": "v-1", "name": "重复条目"},
            {"voice_id": " ", "name": "空 id"},
            {"voice_id": "v-2", "name": "Bella", "preview_url": ""},
        ]

    async def generate_music(self, **kwargs):
        return AudioGenerationResponse(
            audio_url="https://oss.example/music.mp3", duration=95.0)

    async def generate_sfx(self, **kwargs):
        return AudioGenerationResponse(audio_bytes=b"ID3-sfx", audio_format="wav")

    async def synthesize(self, **kwargs):
        return AudioGenerationResponse(audio_url="https://oss.example/tts.mp3")

    async def close(self):
        self.closed = True


class _FakeFetch:
    def __init__(self, content=b"ID3-remote"):
        self.content = content
        self.calls = []

    async def download(self, url, **kwargs):
        self.calls.append(url)
        return FetchResult(status_code=200, content=self.content, content_type="audio/mpeg")


@pytest.fixture
def _wire(monkeypatch, tmp_path):
    """端点/适配器/下载器全部打桩，只验分发与落盘。"""
    monkeypatch.setattr(ga, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(ga, "DashScopeAudioAdapter", _FakeAdapter)
    fetch = _FakeFetch()
    monkeypatch.setattr(ga, "get_media_fetch_adapter", lambda: fetch)

    async def fake_endpoint(provider_id):
        return {
            "cfg": {"audio_models": ["cosyvoice-v3.5-plus", "fun-music-v1", "qwen-audio-3.1-tts-next"]},
            "provider_id": "custom-api-8",
            "base_url": "https://llm-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk",
        }
    monkeypatch.setattr(ga, "_resolve_endpoint", fake_endpoint)
    return SimpleNamespace(fetch=fetch, dir=tmp_path)


async def test_voice_design_saves_preview_and_returns_voice_id(_wire):
    out = await ga.generate_audio_via_provider(
        provider_id="阿里百炼", model="cosyvoice-v3.5-plus", channel="voice_design",
        prompt="沉稳的中年男性，音色低沉浑厚", preview_text="各位听众朋友们大家好，欢迎收听本期节目",
        language="zh", audio_format="wav", prefix="ann",
    )
    assert out["voice_id"] == "cosyvoice-v3.5-plus-vd-ann-1"
    assert out["audio_url"].endswith(".wav")
    assert (_wire.dir / out["audio_url"].rsplit("/", 1)[-1]).read_bytes() == b"RIFF-preview"


async def test_music_downloads_remote_url_to_assets(_wire):
    out = await ga.generate_audio_via_provider(
        provider_id="阿里百炼", model="fun-music-v1", channel="music",
        prompt="夏日清新民谣，木吉他与口琴", instrumental=True, audio_format="mp3",
    )
    assert _wire.fetch.calls == ["https://oss.example/music.mp3"]
    assert out["audio_url"].endswith(".mp3")
    assert (_wire.dir / out["audio_url"].rsplit("/", 1)[-1]).read_bytes() == b"ID3-remote"
    assert out["duration"] == 95.0


async def test_sfx_saves_inline_bytes(_wire):
    out = await ga.generate_audio_via_provider(
        provider_id="阿里百炼", model="qwen-audio-3.1-tts-next", channel="sfx",
        prompt="雨声 + 脚步 + 关门", audio_format="wav", sample_rate=48000,
    )
    assert out["audio_url"].endswith(".wav")
    assert (_wire.dir / out["audio_url"].rsplit("/", 1)[-1]).read_bytes() == b"ID3-sfx"


async def test_voice_design_requires_preview_text(_wire):
    """试听文本必填；长度上限己下沉到适配器（各家 200/300/1000 不同）。"""
    with pytest.raises(GenerationError, match="试听文本"):
        await ga.generate_audio_via_provider(
            provider_id="阿里百炼", model="cosyvoice-v3.5-plus", channel="voice_design",
            prompt="沉稳男声", preview_text="  ")


async def test_voice_design_passes_reference_audio_as_clone_source(_wire):
    """上传/引用音频 → 声音复刻：参考音频以 audio_data 下发给适配器。"""
    out = await ga.generate_audio_via_provider(
        provider_id="阿里百炼", model="cosyvoice-v3.5-plus", channel="voice_design",
        prompt="", preview_text="各位听众朋友们大家好，欢迎收听本期节目",
        references=["https://cdn.example/sample.wav"], audio_format="wav",
    )
    assert out["voice_id"]
    assert _FakeAdapter.last_design.get("audio_data") == "https://cdn.example/sample.wav"


async def test_voice_design_requires_prompt_or_reference(_wire):
    """文字描述与参考音频至少一项（复刻时可以不写描述）。"""
    with pytest.raises(GenerationError, match="音色描述或参考音频"):
        await ga.generate_audio_via_provider(
            provider_id="阿里百炼", model="cosyvoice-v3.5-plus", channel="voice_design",
            prompt="  ", preview_text="各位听众朋友们大家好，欢迎收听本期节目")


async def test_clone_voice_from_reference_audio(_wire):
    """语音合成参数栏上传音频：同步复刻返回 voice_id + 试听。"""
    out = await ga.clone_voice_via_provider(
        provider_id="custom-api-8", target_model="cosyvoice-v3.5-plus",
        audio_url="https://cdn.example/sample.wav",
    )
    assert out["voice_id"]
    assert out["preview_url"].endswith(".wav")
    assert _FakeAdapter.last_design.get("audio_data") == "https://cdn.example/sample.wav"
    assert _FakeAdapter.last_design.get("target_model") == "cosyvoice-v3.5-plus"


async def test_list_voices_dedupes_and_keeps_preview(_wire):
    """音色列表：按 voice_id 去重、跳过空 id，保留 preview_url（供试听）。"""
    out = await ga.list_voices_via_provider(
        provider_id="custom-api-8", model="cosyvoice-v3.5-plus")
    assert _FakeAdapter.last_list_model == "cosyvoice-v3.5-plus"
    assert out == [
        {"voice_id": "v-1", "name": "Rachel", "preview_url": "https://x/p.mp3",
         "category": ""},
        {"voice_id": "v-2", "name": "Bella", "preview_url": "", "category": ""},
    ]


async def test_list_voices_rejects_non_tts_model(_wire):
    with pytest.raises(GenerationError, match="不支持"):
        await ga.list_voices_via_provider(
            provider_id="custom-api-8", model="fun-music-v1")


async def test_clone_voice_requires_usable_reference(_wire):
    with pytest.raises(GenerationError, match="参考音频不可用"):
        await ga.clone_voice_via_provider(
            provider_id="custom-api-8", target_model="cosyvoice-v3.5-plus",
            audio_url="/workspace/assets/missing.mp3",
        )


async def test_resolve_endpoint_requires_api_key(monkeypatch):
    async def fake_cfg(pid):
        return {"base_url": "https://x/compatible-mode/v1"}

    async def fake_key(pid):
        return ""

    async def fake_ref(ref):
        return ref

    monkeypatch.setattr(ga, "get_provider_config_async", fake_cfg)
    monkeypatch.setattr(ga, "get_api_key_async", fake_key)
    monkeypatch.setattr(ga, "resolve_provider_ref_async", fake_ref)
    with pytest.raises(GenerationError, match="API Key"):
        await ga._resolve_endpoint("custom-api-8")


async def test_music_requires_prompt_or_lyrics(_wire):
    with pytest.raises(GenerationError, match="音乐描述或歌词"):
        await ga.generate_audio_via_provider(
            provider_id="阿里百炼", model="fun-music-v1", channel="music", prompt="  ")


# ---------- 适配器选择（openai-speech / 未接入平台） ----------

def test_build_adapter_openai_speech_only_for_tts():
    cfg = {"audio_request_mode": "openai-speech", "audio_voice_join_model": True}
    adapter = ga._build_adapter(cfg, "https://api.siliconflow.cn/v1", "sk", "tts")
    assert adapter.__class__.__name__ == "OpenAIAudioAdapter"
    assert adapter._voice_join_model is True
    with pytest.raises(GenerationError, match="只支持语音合成"):
        ga._build_adapter(cfg, "https://api.siliconflow.cn/v1", "sk", "music")


def test_build_adapter_rejects_unintegrated_vendor():
    with pytest.raises(GenerationError, match="尚未接入音频适配器"):
        ga._build_adapter({}, "https://tokenhub.tencentmaas.com/v1", "sk", "tts")


def test_build_adapter_volcengine_speech():
    """火山豆包语音：三通道共用一个适配器（通道支持由适配器自己判）。"""
    cfg = {"protocol": "volcengine-speech"}
    for channel in ("tts", "sfx", "voice_design"):
        adapter = ga._build_adapter(
            cfg, "https://openspeech.bytedance.com", "sk-key", channel)
        assert adapter.__class__.__name__ == "VolcengineSpeechAdapter"


def test_build_adapter_elevenlabs():
    cfg = {"audio_request_mode": "elevenlabs"}
    adapter = ga._build_adapter(cfg, "https://api.elevenlabs.io/v1", "xi-key", "tts")
    assert adapter.__class__.__name__ == "ElevenLabsAudioAdapter"


async def test_tts_requires_voice_id(_wire):
    with pytest.raises(GenerationError, match="voice_id"):
        await ga.generate_audio_via_provider(
            provider_id="阿里百炼", model="cosyvoice-v3.5-plus", channel="tts",
            prompt="台词一句", voice_id="")


async def test_openai_speech_tts_saves_bytes(monkeypatch, tmp_path):
    """OpenAI 兼容 TTS（硅基流动）：二进制音频直接落盘，不经 URL 下载。"""
    monkeypatch.setattr(ga, "ASSETS_DIR", tmp_path)

    async def fake_endpoint(pid):
        return {
            "cfg": {
                "audio_models": ["FunAudioLLM/CosyVoice2-0.5B"],
                "audio_request_mode": "openai-speech",
                "audio_voice_join_model": True,
            },
            "provider_id": "custom-api-10",
            "base_url": "https://api.siliconflow.cn/v1", "api_key": "sk",
        }
    monkeypatch.setattr(ga, "_resolve_endpoint", fake_endpoint)

    class _FakeOpenAI:
        def __init__(self, *args, **kwargs):
            pass

        async def synthesize(self, **kwargs):
            return AudioGenerationResponse(audio_bytes=b"ID3-sf", audio_format="mp3")

        async def close(self):
            pass

    monkeypatch.setattr(ga, "OpenAIAudioAdapter", _FakeOpenAI)
    out = await ga.generate_audio_via_provider(
        provider_id="硅基流动", model="FunAudioLLM/CosyVoice2-0.5B", channel="tts",
        prompt="你好", voice_id="alex", audio_format="mp3",
    )
    assert out["audio_url"].endswith(".mp3")
    assert (tmp_path / out["audio_url"].rsplit("/", 1)[-1]).read_bytes() == b"ID3-sf"


# ---------- 回写 ----------

class _FakeSvc:
    def __init__(self, state):
        self.state_dict = state
        self.saved = 0

    def find_draft(self, draft_id):
        for cat in ("audioItems", "keyElements"):
            for g in self.state_dict.get(cat) or []:
                for d in g.get("drafts") or []:
                    if d.get("id") == draft_id:
                        return (cat, g, d)
        return None

    def save(self):
        self.saved += 1


def test_writeback_audio_sets_url_type_and_voice_id(monkeypatch):
    group = {"id": "audio-1", "drafts": [
        {"id": "a1", "mediaType": "audio", "audioUrl": "", "audioType": "bgm"},
    ]}
    svc = _FakeSvc({"audioItems": [group], "keyElements": []})
    task = {
        "status": "succeeded", "draft_id": "a1",
        "audio_url": "/workspace/assets/audio-1.mp3",
        "result": {"audio": "/workspace/assets/audio-1.mp3", "voice_id": "v-1"},
    }
    monkeypatch.setattr(tm, "StateManager", SimpleNamespace(get_instance=lambda: svc))
    monkeypatch.setattr(
        tm, "get_task_manager", lambda: SimpleNamespace(get_task=lambda tid: task))

    tm.writeback_if_complete("t-audio")

    draft = group["drafts"][0]
    assert draft["audioUrl"] == "/workspace/assets/audio-1.mp3"
    assert draft["mediaType"] == "audio" and draft["genType"] == "audio"
    assert draft["voiceId"] == "v-1"
    assert draft["tag"] == "已生成"
    assert svc.saved == 1
