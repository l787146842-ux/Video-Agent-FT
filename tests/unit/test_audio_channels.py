"""音频通道能力推导 + DashScope 音频适配器请求/响应单测（2026-10-28 M1-M3）。"""
import base64

import pytest

from src.video_agent.adapters.dashscope_audio import DashScopeAudioAdapter, dashscope_root
from src.video_agent.core.audio_channels import (
    AUDIO_CHANNEL_MUSIC,
    AUDIO_CHANNEL_SFX,
    AUDIO_CHANNEL_TTS,
    AUDIO_CHANNEL_VOICE_DESIGN,
    audio_adapter_kind,
    audio_models_meta_of,
    audio_params_for,
    first_model_for_channel,
    infer_audio_capabilities,
    model_supports_channel,
    models_for_channel,
)
from src.video_agent.exceptions import AdapterError


# ---------- 能力推导（单一事实源） ----------

@pytest.mark.parametrize("model,expected", [
    ("fun-music-v1", [AUDIO_CHANNEL_MUSIC]),
    ("fun-music-preview", [AUDIO_CHANNEL_MUSIC]),
    ("cosyvoice-v3.5-plus", [AUDIO_CHANNEL_VOICE_DESIGN, AUDIO_CHANNEL_TTS]),
    ("qwen-audio-3.1-tts-flash", [AUDIO_CHANNEL_VOICE_DESIGN, AUDIO_CHANNEL_TTS]),
    ("qwen-audio-3.1-tts-next", [AUDIO_CHANNEL_SFX]),
    # 豆包 seed-audio：纯文本出音效 + 带 speaker 做合成（两种都实测通过）
    ("seed-audio-1.0", [AUDIO_CHANNEL_SFX, AUDIO_CHANNEL_TTS]),
    ("MiniMax/speech-2.8-hd", [AUDIO_CHANNEL_TTS]),
    # 2026-10-28 多厂商批：真实拉取到的模型名
    # voice-design 类只做设计（合成需另一个 speech 模型），故只有 voice_design
    ("minimax-voice-design", [AUDIO_CHANNEL_VOICE_DESIGN]),
    ("minimax-voice-clone", [AUDIO_CHANNEL_TTS]),
    # ElevenLabs 文字设计音色专用模型（text-to-voice）
    ("eleven_multilingual_ttv_v2", [AUDIO_CHANNEL_VOICE_DESIGN]),
    ("minimax-music-v3.0", [AUDIO_CHANNEL_MUSIC]),
    ("mureka-music-v9", [AUDIO_CHANNEL_MUSIC]),
    ("tenlai-tts-v1.0", [AUDIO_CHANNEL_TTS]),
    ("indextts-2", [AUDIO_CHANNEL_TTS]),
    ("FunAudioLLM/CosyVoice2-0.5B", [AUDIO_CHANNEL_TTS]),
    ("fnlp/MOSS-TTSD-v0.5", [AUDIO_CHANNEL_TTS]),
    # 识别类不是生成能力 → 不进任何通道
    ("tenlai-asr-v1.0", []),
    ("Qwen/Qwen3-ASR-1.7B", []),
    ("FunAudioLLM/SenseVoiceSmall", []),
    ("XingChenAGI/XingChenASR-V3.2", []),
    ("some-unknown-audio", [AUDIO_CHANNEL_TTS]),
    ("", []),
])
def test_infer_audio_capabilities(model, expected):
    assert infer_audio_capabilities(model) == expected


def test_explicit_meta_overrides_inference():
    provider = {
        "audio_models": ["fun-music-v1", "cosyvoice-v3.5-plus"],
        "audio_models_meta": [
            # 故意把 fun-music 声明成 tts：显式声明优先于模型名推导
            {"model": "fun-music-v1", "capabilities": ["tts"]},
            # 旧写法 capability 单值兼容
            {"model": "cosyvoice-v3.5-plus", "capability": "tts"},
        ],
    }
    meta = {e["model"]: e["capabilities"] for e in audio_models_meta_of(provider)}
    assert meta["fun-music-v1"] == ["tts"]
    assert meta["cosyvoice-v3.5-plus"] == ["tts"]


def test_models_for_channel_and_support():
    provider = {"audio_models": [
        "cosyvoice-v3.5-plus", "fun-music-v1", "qwen-audio-3.1-tts-next",
    ]}
    assert models_for_channel(provider, AUDIO_CHANNEL_MUSIC) == ["fun-music-v1"]
    assert models_for_channel(provider, AUDIO_CHANNEL_VOICE_DESIGN) == ["cosyvoice-v3.5-plus"]
    assert models_for_channel(provider, AUDIO_CHANNEL_SFX) == ["qwen-audio-3.1-tts-next"]
    assert model_supports_channel("fun-music-v1", AUDIO_CHANNEL_MUSIC, provider) is True
    assert model_supports_channel("fun-music-v1", AUDIO_CHANNEL_TTS, provider) is False


def test_meta_only_model_is_selectable():
    """只在 audio_models_meta 里声明的模型同样进候选（配置两种写法等价）。"""
    provider = {"audio_models_meta": [{"model": "fun-music-v1", "capabilities": ["music"]}]}
    assert models_for_channel(provider, AUDIO_CHANNEL_MUSIC) == ["fun-music-v1"]


def test_first_model_for_channel_skips_disabled():
    providers = [
        {"id": "off", "enabled": False, "audio_models": ["fun-music-v1"]},
        {"id": "on", "enabled": True, "audio_models": ["fun-music-v1"]},
    ]
    assert first_model_for_channel(providers, AUDIO_CHANNEL_MUSIC) == ("on", "fun-music-v1")
    assert first_model_for_channel([], AUDIO_CHANNEL_MUSIC) == ("", "")


# ---------- 参数 schema（模型自己声明，底部栏自适应） ----------

def test_meta_includes_default_params_per_capability():
    provider = {"audio_models": [
        "fun-music-v1", "cosyvoice-v3.5-plus", "qwen-audio-3.1-tts-next",
    ]}
    meta = {entry["model"]: entry for entry in audio_models_meta_of(provider)}

    music_keys = [spec["key"] for spec in meta["fun-music-v1"]["params"]]
    assert music_keys == [
        "prompt", "lyrics", "instrumental", "gender", "format", "watermark",
    ]
    gender = next(s for s in meta["fun-music-v1"]["params"] if s["key"] == "gender")
    assert gender["when"] == "instrumental=false"

    # 跨能力模型：design 与 tts 的默认参数都在，但各自带 channels
    voice = meta["cosyvoice-v3.5-plus"]["params"]
    assert any(s["key"] == "preview_text" and s["channels"] == ["voice_design"] for s in voice)
    assert any(s["key"] == "voice_id" and s["channels"] == ["tts"] for s in voice)

    sfx = meta["qwen-audio-3.1-tts-next"]["params"]
    # 2026-10-31 用户裁决：音效不需要参考音频（refs 只用于声音复刻）
    assert not any(s["key"] == "refs" for s in sfx)


def test_declared_sfx_refs_dropped_and_clone_scoped_to_dashscope():
    """显式声明里残留的音效参考音频被剔除；上传复刻入口只给已接复刻的适配器。"""
    provider = {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "audio_models": [
            "qwen-audio-3.1-tts-next", "cosyvoice-v3.5-plus", "MiniMax/speech-2.8-hd",
        ],
        "audio_models_meta": [
            {"model": "qwen-audio-3.1-tts-next", "capabilities": ["sfx"], "params": [
                {"key": "prompt", "type": "text", "source": "prompt", "required": True,
                 "channels": ["sfx"]},
                {"key": "refs", "type": "refs", "source": "refs", "label": "参考音频",
                 "channels": ["sfx"]},
            ]},
            {"model": "cosyvoice-v3.5-plus", "capabilities": ["tts"], "params": [
                {"key": "voice_id", "type": "text", "required": True, "channels": ["tts"]},
            ]},
            {"model": "MiniMax/speech-2.8-hd", "capabilities": ["tts"], "params": [
                {"key": "voice_id", "type": "text", "required": True, "channels": ["tts"]},
            ]},
        ],
    }
    meta = {e["model"]: e for e in audio_models_meta_of(provider)}
    # 旧配置里的 sfx refs 不能把已裁决去掉的入口带回来
    assert "refs" not in [s["key"] for s in meta["qwen-audio-3.1-tts-next"]["params"]]
    cosy = next(s for s in meta["cosyvoice-v3.5-plus"]["params"] if s["key"] == "voice_id")
    assert cosy.get("clone") is True
    # MiniMax 在百炼 voice-enrollment 下不可复刻：不给上传入口
    minimax = next(s for s in meta["MiniMax/speech-2.8-hd"]["params"] if s["key"] == "voice_id")
    assert "clone" not in minimax

    # 未接复刻的平台（火山）走默认参数集也不显示上传入口
    volc = {
        "base_url": "https://openspeech.bytedance.com",
        "audio_models": ["seed-audio-1.0"],
    }
    volc_meta = {e["model"]: e for e in audio_models_meta_of(volc)}
    volc_voice = next(s for s in volc_meta["seed-audio-1.0"]["params"] if s["key"] == "voice_id")
    assert "clone" not in volc_voice


def test_declared_params_override_defaults_and_support_dict_form():
    provider = {
        "audio_models": ["m"],
        "audio_models_meta": [{
            "model": "m", "capabilities": ["music"],
            "params": {
                "prompt": {"type": "text", "required": True},
                "duration": {"type": "number", "min": 5, "max": 60, "default": "30"},
            },
        }],
    }
    specs = audio_params_for(provider, "m", "music")
    assert [s["key"] for s in specs] == ["prompt", "duration"]
    assert specs[1]["default"] == "30"
    assert specs[1]["max"] == 60


def test_invalid_param_declarations_are_dropped():
    provider = {
        "audio_models": ["m"],
        "audio_models_meta": [{
            "model": "m", "capabilities": ["music"],
            "params": [
                {"key": "bad_enum", "type": "enum"},   # enum 无 values → 丢弃
                {"type": "text"},                        # 无 key → 丢弃
                {"key": "ok", "type": "bool", "default": True},
            ],
        }],
    }
    assert [s["key"] for s in audio_params_for(provider, "m", "music")] == ["ok"]


def test_model_specific_param_drops():
    """模型确实不支持的参数不被展示（preview 无 gender / MiniMax 未映射 language）。"""
    provider = {"audio_models": ["fun-music-preview", "MiniMax/speech-2.8-hd"]}
    meta = {entry["model"]: entry for entry in audio_models_meta_of(provider)}
    preview_keys = [s["key"] for s in meta["fun-music-preview"]["params"]]
    assert preview_keys == ["prompt", "lyrics", "instrumental", "format", "watermark"]
    minimax_keys = [s["key"] for s in meta["MiniMax/speech-2.8-hd"]["params"]]
    assert "language" not in minimax_keys
    assert "voice_id" in minimax_keys


def test_param_provider_scope_and_multiline():
    """长文本参数标多行；音色位 ID 只对火山豆包语音下发（百炼不出现无意义输入框）。"""
    dashscope = {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "audio_models": ["cosyvoice-v3.5-plus", "fun-music-v1"],
    }
    meta = {e["model"]: e for e in audio_models_meta_of(dashscope)}
    design_specs = [
        s for s in meta["cosyvoice-v3.5-plus"]["params"]
        if "voice_design" in (s.get("channels") or [])
    ]
    assert "voice_id" not in [s["key"] for s in design_specs]
    preview = next(s for s in design_specs if s["key"] == "preview_text")
    assert preview.get("multiline") is True
    lyrics = next(s for s in meta["fun-music-v1"]["params"] if s["key"] == "lyrics")
    assert lyrics.get("multiline") is True

    volc = {
        "base_url": "https://openspeech.bytedance.com",
        "audio_models": ["voice-design"],
    }
    volc_meta = {e["model"]: e for e in audio_models_meta_of(volc)}
    volc_keys = [s["key"] for s in volc_meta["voice-design"]["params"]]
    assert "voice_id" in volc_keys


def test_voice_list_injected_only_for_supported_adapter():
    """「拉取音色」入口只给已接列表接口的适配器（当前 ElevenLabs），百炼/火山不出现。"""
    eleven = {
        "base_url": "https://api.elevenlabs.io/v1",
        "audio_models": ["eleven_v3"],
    }
    eleven_meta = {e["model"]: e for e in audio_models_meta_of(eleven)}
    eleven_voice = next(
        s for s in eleven_meta["eleven_v3"]["params"] if s["key"] == "voice_id")
    assert eleven_voice.get("list_voices") is True

    dashscope = {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "audio_models": ["cosyvoice-v3.5-plus"],
    }
    ds_meta = {e["model"]: e for e in audio_models_meta_of(dashscope)}
    ds_voice = next(
        s for s in ds_meta["cosyvoice-v3.5-plus"]["params"]
        if s["key"] == "voice_id" and "tts" in (s.get("channels") or []))
    assert "list_voices" not in ds_voice

    volc = {"base_url": "https://openspeech.bytedance.com", "audio_models": ["seed-audio-1.0"]}
    volc_meta = {e["model"]: e for e in audio_models_meta_of(volc)}
    volc_voice = next(
        s for s in volc_meta["seed-audio-1.0"]["params"] if s["key"] == "voice_id")
    assert "list_voices" not in volc_voice


def test_audio_adapter_kind():
    assert audio_adapter_kind({"audio_request_mode": "openai-speech"}) == "openai-speech"
    assert audio_adapter_kind({"protocol": "volcengine-speech"}) == "volcengine-speech"
    assert audio_adapter_kind({
        "base_url": "https://llm-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    }) == "dashscope"
    assert audio_adapter_kind({"base_url": "https://tokenhub.tencentmaas.com/v1"}) == ""
    assert audio_adapter_kind({}) == ""


def test_save_normalizes_lost_audio_meta():
    """保存自愈：设置页回传的 provider 丢了能力清单/适配器声明，落盘前必须补回。

    这是“未接音频”与模型跨通道串选的根因（表单不展示这两个字段，
    每次保存都丢掉）。修复后不再依赖前端是否记得回传。
    """
    from src.video_agent.web.routes.providers import normalize_provider_audio

    # 前端回传：只有 base_url + audio_models，meta 与 mode 都没了
    saved = normalize_provider_audio({
        "id": "volcengine-speech",
        "protocol": "volcengine-speech",
        "base_url": "https://openspeech.bytedance.com",
        "audio_models": ["voice-design", "seed-audio-1.0"],
    })
    assert saved["audio_request_mode"] == "volcengine-speech"
    meta = {e["model"]: e["capabilities"] for e in saved["audio_models_meta"]}
    assert meta["voice-design"] == ["voice_design"]
    assert meta["seed-audio-1.0"] == ["sfx", "tts"]


    silicon = normalize_provider_audio({
        "id": "custom-api-10", "base_url": "https://api.siliconflow.cn/v1",
        "audio_models": ["FunAudioLLM/CosyVoice2-0.5B"],
    })
    assert silicon["audio_request_mode"] == "openai-speech"


def test_audio_adapter_kind_falls_back_to_host():
    """设置页保存会丢掉未展示字段（audio_request_mode）：
    只剩 base_url 时也要能认出适配器，否则用户改一下地址就变「未接音频」。"""
    assert audio_adapter_kind({"base_url": "https://api.elevenlabs.io/v1"}) == "elevenlabs"
    assert audio_adapter_kind({"base_url": "https://openspeech.bytedance.com"}) == "volcengine-speech"
    assert audio_adapter_kind({"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"}) == "dashscope"
    # 硅基流动实测可用（OpenAI 兼容 /audio/speech），同样不能靠配置字段
    assert audio_adapter_kind({"base_url": "https://api.siliconflow.cn/v1"}) == "openai-speech"


def test_volcengine_adapter_strips_any_endpoint_to_host():
    """豆包语音每个功能一个端点，用户很容易把完整端点粘进 base_url。"""
    from src.video_agent.adapters.volcengine_speech import VolcengineSpeechAdapter

    for base in (
        "https://openspeech.bytedance.com",
        "https://openspeech.bytedance.com/",
        "https://openspeech.bytedance.com/api/v3/tts/voice_design",
        "https://openspeech.bytedance.com/api/v3/tts/create",
        "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
    ):
        assert VolcengineSpeechAdapter(base, "k")._root == "https://openspeech.bytedance.com", base


def test_param_channel_filter():
    provider = {"audio_models_meta": [{
        "model": "m", "capabilities": ["voice_design", "tts"],
        "params": [
            {"key": "a", "channels": ["voice_design"]},
            {"key": "b", "channels": ["tts"]},
        ],
    }]}
    assert [s["key"] for s in audio_params_for(provider, "m", "voice_design")] == ["a"]
    assert [s["key"] for s in audio_params_for(provider, "m", "tts")] == ["b"]


# ---------- base_url 归一化 ----------

@pytest.mark.parametrize("raw,expected", [
    ("https://llm-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
     "https://llm-x.cn-beijing.maas.aliyuncs.com"),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "https://dashscope.aliyuncs.com"),
    ("https://dashscope.aliyuncs.com/api/v1", "https://dashscope.aliyuncs.com"),
    ("https://llm-x.cn-beijing.maas.aliyuncs.com/", "https://llm-x.cn-beijing.maas.aliyuncs.com"),
    ("", ""),
])
def test_dashscope_root(raw, expected):
    assert dashscope_root(raw) == expected


# ---------- 适配器请求体 / 响应解析 ----------

@pytest.fixture
def adapter():
    return DashScopeAudioAdapter(
        "https://llm-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "sk-test")


async def test_design_voice_payload_and_preview_decode(adapter, monkeypatch):
    captured = {}

    async def fake_post(path, payload, *, context):
        captured["path"], captured["payload"], captured["context"] = path, payload, context
        return {"output": {
            "voice_id": "cosyvoice-v3.5-plus-vd-announcer-abc",
            "preview_audio": {
                "data": base64.b64encode(b"RIFF").decode(),
                "sample_rate": 24000, "response_format": "wav",
            },
            "target_model": "cosyvoice-v3.5-plus",
            "status": "DEPLOYING",
        }}

    monkeypatch.setattr(adapter, "_post", fake_post)
    out = await adapter.design_voice(
        target_model="cosyvoice-v3.5-plus",
        voice_prompt="沉稳的中年男性，音色低沉浑厚",
        preview_text="各位听众朋友们大家好，欢迎收听本期节目",
        prefix="announcer-!!", language="zh", sample_rate=24000, response_format="wav",
    )
    assert captured["path"] == "/api/v1/services/audio/tts/customization"
    body = captured["payload"]
    assert body["model"] == "voice-enrollment"
    assert body["input"]["action"] == "create_voice"
    assert body["input"]["target_model"] == "cosyvoice-v3.5-plus"
    assert body["input"]["prefix"] == "announcer"       # 非字母数字被清掉
    assert body["input"]["language_hints"] == ["zh"]
    assert body["parameters"] == {"sample_rate": 24000, "response_format": "wav"}
    assert out.voice_id.endswith("-abc")
    assert out.preview_audio == b"RIFF"
    assert out.status == "DEPLOYING"


async def test_design_voice_uses_reference_audio_for_clone(adapter, monkeypatch):
    """上传参考音频 → 声音复刻：payload 用 audio_data 替代 voice_prompt。"""
    captured = {}

    async def fake_post(path, payload, *, context):
        captured["payload"] = payload
        return {"output": {
            "voice_id": "clone-voice-1",
            "preview_audio": {
                "data": base64.b64encode(b"RIFF").decode(),
                "sample_rate": 24000, "response_format": "wav",
            },
        }}

    monkeypatch.setattr(adapter, "_post", fake_post)
    out = await adapter.design_voice(
        target_model="cosyvoice-v3.5-plus", voice_prompt="",
        preview_text="各位听众朋友们大家好，欢迎收听本期节目",
        audio_data="data:audio/wav;base64,AAAA",
    )
    body_input = captured["payload"]["input"]
    assert body_input["audio_data"] == "data:audio/wav;base64,AAAA"
    assert "voice_prompt" not in body_input
    assert out.voice_id == "clone-voice-1"


async def test_design_voice_requires_prompt_or_audio(adapter):
    with pytest.raises(AdapterError, match="音色描述或参考音频"):
        await adapter.design_voice(
            target_model="cosyvoice-v3.5-plus", voice_prompt="  ",
            preview_text="各位听众朋友们大家好，欢迎收听本期节目",
        )


async def test_generate_music_instrumental_drops_gender_and_keeps_lyrics(adapter, monkeypatch):
    captured = {}

    async def fake_post(path, payload, *, context):
        captured["path"], captured["payload"] = path, payload
        return {"output": {"audio": {"url": "https://oss/x.mp3"}, "extra_info": {"sample_rate": "48000"}},
                "usage": {"duration": 120}}

    monkeypatch.setattr(adapter, "_post", fake_post)
    out = await adapter.generate_music(
        model="fun-music-v1", prompt="夏日清新民谣", lyrics="第一句歌词",
        instrumental=False, gender="female", audio_format="mp3", watermark=True,
    )
    body = captured["payload"]
    assert captured["path"] == "/api/v1/services/audio/music/generation"
    assert body["input"]["is_instrumental"] is False
    assert body["input"]["lyrics"] == "第一句歌词"
    assert body["input"]["gender"] == "female"
    assert body["input"]["enable_aigc_watermark"] is True
    assert out.audio_url == "https://oss/x.mp3"
    assert out.duration == 120.0

    await adapter.generate_music(
        model="fun-music-v1", prompt="纯音乐", instrumental=True, gender="female")
    assert "gender" not in captured["payload"]["input"], "纯音乐模式 gender 无效"


async def test_generate_music_preview_has_no_gender(adapter, monkeypatch):
    captured = {}

    async def fake_post(path, payload, *, context):
        captured["payload"] = payload
        return {"output": {"audio": {"url": "https://oss/y.mp3"}}}

    monkeypatch.setattr(adapter, "_post", fake_post)
    await adapter.generate_music(
        model="fun-music-preview", prompt="p", instrumental=False, gender="male")
    assert "gender" not in captured["payload"]["input"]


async def test_generate_sfx_references_split_url_and_data(adapter, monkeypatch):
    captured = {}

    async def fake_post(path, payload, *, context):
        captured["path"], captured["payload"] = path, payload
        return {"output": {"audio": {"url": "https://oss/sfx.wav"}}}

    monkeypatch.setattr(adapter, "_post", fake_post)
    await adapter.generate_sfx(
        model="qwen-audio-3.1-tts-next", text_prompt="雨声 + 脚步",
        references=["https://x/a.wav", "data:audio/wav;base64,AAA="],
        audio_format="wav", sample_rate=48000, channels=2, volume=60,
    )
    assert captured["path"] == "/api/v1/services/audio/tts/SpeechSynthesizer"
    refs = captured["payload"]["input"]["references"]
    assert refs == [{"audio_url": "https://x/a.wav"}, {"audio_data": "data:audio/wav;base64,AAA="}]
    assert captured["payload"]["input"]["volume"] == 60


async def test_synthesize_minimax_uses_voice_setting_and_url_output(adapter, monkeypatch):
    captured = {}

    async def fake_post(path, payload, *, context):
        captured["path"], captured["payload"] = path, payload
        return {"output": {"audio": {"url": "https://oss/tts.mp3"}}}

    monkeypatch.setattr(adapter, "_post", fake_post)
    out = await adapter.synthesize(
        model="MiniMax/speech-2.8-hd", text="台词", voice_id="male-qn-qingse",
        audio_format="mp3", sample_rate=32000, speed=1.0,
    )
    body = captured["payload"]
    assert captured["path"] == "/api/v1/services/aigc/multimodal-generation/generation"
    assert body["input"]["voice_setting"]["voice_id"] == "male-qn-qingse"
    assert body["input"]["output_format"] == "url"
    assert body["input"]["audio_setting"]["format"] == "mp3"
    assert out.audio_url.endswith("tts.mp3")


async def test_synthesize_qwen_uses_voice_and_language(adapter, monkeypatch):
    captured = {}

    async def fake_post(path, payload, *, context):
        captured["path"], captured["payload"] = path, payload
        return {"output": {"audio": {"url": "https://oss/q.wav"}}}

    monkeypatch.setattr(adapter, "_post", fake_post)
    await adapter.synthesize(
        model="qwen-audio-3.1-tts-plus", text="台词", voice_id="cosyvoice-v3.5-plus-vd-x",
        language="Chinese", audio_format="wav",
    )
    # Qwen-Audio-TTS / CosyVoice 官方合成端点 = SpeechSynthesizer（非 multimodal-generation）
    assert captured["path"] == "/api/v1/services/audio/tts/SpeechSynthesizer"
    assert captured["payload"]["input"]["voice"] == "cosyvoice-v3.5-plus-vd-x"
    assert captured["payload"]["input"]["language_hints"] == ["zh"]
    assert captured["payload"]["input"]["format"] == "wav"


async def test_http_error_carries_status_for_429_retry(monkeypatch, adapter):
    class _Resp:
        status_code = 429
        text = '{"code":"Throttling.RateQuota"}'

    class _Client:
        async def post(self, url, json):
            return _Resp()

    monkeypatch.setattr(adapter, "_get_client", lambda: _Client())

    with pytest.raises(AdapterError) as ei:
        await adapter._post("/x", {}, context="音乐生成")
    assert ei.value.http_status == 429
    assert "429" in str(ei.value)          # BoundedChannel 按 "429" 判定退避
    assert ei.value.retryable is True


async def test_error_envelope_on_http_200(adapter, monkeypatch):
    class _Resp:
        status_code = 200
        text = '{"code":"ModelNotExist","message":"model not exist"}'

        def json(self):
            return {"code": "ModelNotExist", "message": "model not exist"}

    class _Client:
        async def post(self, url, json):
            return _Resp()

    monkeypatch.setattr(adapter, "_get_client", lambda: _Client())
    with pytest.raises(AdapterError) as ei:
        await adapter.generate_music(model="nope", prompt="p")
    assert "ModelNotExist" in str(ei.value)
    assert ei.value.retryable is False


def test_httpx_import_guard():
    """适配器依赖 httpx（Rule 4 外部调用）；导入即失败说明环境缺依赖。"""
    import httpx
    assert httpx.__version__
