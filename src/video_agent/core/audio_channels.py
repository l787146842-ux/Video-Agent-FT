"""音频通道 / 模型能力词表（单一事实源）。

音频只保留四条通道（用户裁决 2026-10-28「只用能设计音色的模型和能出背景
音乐的模型」）：
- ``voice_design`` 音色设计：自然语言描述 → 自定义音色（CosyVoice / Qwen-Audio-TTS）；
- ``tts``          语音合成：已设计/已复刻音色 → 音频样音（旁白、台词）；
- ``music``        背景音乐：Fun-Music 纯音乐（BGM）；
- ``sfx``          音效/环境音：百炼音频生成（qwen-audio-*-tts-next）。

本模块是「模型能干什么」的唯一推导入口：后端路由校验、供应商列表下发
（``/api/providers`` 的 ``audio_models_meta``）、前端下拉过滤全部消费这里，
禁止各处再按模型名前缀各写一遍（P1 单一事实源）。

配置优先：``data/api_providers.json`` 的 ``audio_models_meta`` 若显式声明
``capabilities``（或旧写法 ``capability``），以声明为准；未声明才按模型名推导。
"""
from typing import Any, Dict, Iterable, List

# 通道取值（前后端与卡字段 audioChannel 共用同一词表）
AUDIO_CHANNEL_VOICE_DESIGN = "voice_design"
AUDIO_CHANNEL_TTS = "tts"
AUDIO_CHANNEL_MUSIC = "music"
AUDIO_CHANNEL_SFX = "sfx"

AUDIO_CHANNELS = (
    AUDIO_CHANNEL_VOICE_DESIGN,
    AUDIO_CHANNEL_TTS,
    AUDIO_CHANNEL_MUSIC,
    AUDIO_CHANNEL_SFX,
)

AUDIO_CHANNEL_LABELS = {
    AUDIO_CHANNEL_VOICE_DESIGN: "音色设计",
    AUDIO_CHANNEL_TTS: "语音合成",
    AUDIO_CHANNEL_MUSIC: "背景音乐",
    AUDIO_CHANNEL_SFX: "音效",
}

# 模型名 → 能力推导关键词（顺序敏感：先剔除非生成类，再判音乐/音效/音色设计）
_ASR_KEYWORDS = (
    "asr", "sensevoice", "whisper", "paraformer", "speech-recognition",
    "transcribe", "diarize",
)
_MUSIC_KEYWORDS = (
    "fun-music", "suno", "mureka", "ace-step", "stable-audio", "musicgen",
    "diffrhythm", "seedmusic", "seed-music", "music",
)
# qwen-audio-3.1-tts-next（音频生成：音效/环境音/多人对话）
_SFX_KEYWORDS = ("tts-next", "sound-effect", "sound_effect", "sfx", "seed-audio", "audio-gen")
# 显式声音设计命名（百炼 voice-enrollment / MiniMax voice-design / ElevenLabs ttv）
_VOICE_DESIGN_KEYWORDS = (
    "voice-enrollment", "voice-enroll", "voice-design", "voice_design", "voicedesign",
    "_ttv_", "text-to-voice",
)
_QWEN_TTS_KEYWORDS = ("qwen-audio", "qwen3-tts", "qwen-tts")
_CLONE_KEYWORDS = ("voice-clone", "voice_clone", "voicecopy", "voice-copy")
_SPEECH_KEYWORDS = ("speech", "tts", "voice")


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def infer_audio_capabilities(model: str) -> List[str]:
    """按模型名推导能力（配置未显式声明 ``capabilities`` 时的兜底）。

    返回列表而非单值：同一模型可同时承担多通道（CosyVoice 既能设计音色
    也能合成语音；qwen-audio-*-tts-next 既能出音效也能当 TTS 用）。
    """
    m = _lower(model)
    if not m:
        return []
    # 识别/转写类不是生成能力：不进任何音频生成通道（ASR/SenseVoice/Whisper…）
    if any(k in m for k in _ASR_KEYWORDS):
        return []
    if any(k in m for k in _MUSIC_KEYWORDS):
        return [AUDIO_CHANNEL_MUSIC]
    if any(k in m for k in _SFX_KEYWORDS):
        # 音频生成模型：能纯文本出音效，也能带 speaker 做语音合成（seed-audio 实测两者都通），
        # 故声报 tts+sfx；而 qwen-audio-*-tts-next 合成走 text_prompt（不接受 voice），
        # 挂到 tts 会被上游 400，只给 sfx。
        if "seed-audio" in m:
            return [AUDIO_CHANNEL_SFX, AUDIO_CHANNEL_TTS]
        return [AUDIO_CHANNEL_SFX]
    if any(k in m for k in _VOICE_DESIGN_KEYWORDS):
        # 名字里直接写 voice-design 的只做设计（合成需另一个 speech 模型）；
        # CosyVoice / Qwen 这类合成模型走下面的分支同时给两通道。
        return [AUDIO_CHANNEL_VOICE_DESIGN]
    if "cosyvoice" in m:
        # CosyVoice v3+ 支持声音设计；CosyVoice2 只能合成（硅基流动同名模型属后者）
        if "cosyvoice2" in m or "cosyvoice-2" in m:
            return [AUDIO_CHANNEL_TTS]
        return [AUDIO_CHANNEL_VOICE_DESIGN, AUDIO_CHANNEL_TTS]
    if any(k in m for k in _QWEN_TTS_KEYWORDS) and "tts" in m:
        return [AUDIO_CHANNEL_VOICE_DESIGN, AUDIO_CHANNEL_TTS]
    if any(k in m for k in _CLONE_KEYWORDS):
        # 复刻是输入方式，产物仍是合成语音；暂归 tts（未单开克隆通道）
        return [AUDIO_CHANNEL_TTS]
    if any(k in m for k in _SPEECH_KEYWORDS):
        return [AUDIO_CHANNEL_TTS]
    return [AUDIO_CHANNEL_TTS]


def declared_capabilities(entry: Dict[str, Any]) -> List[str]:
    """读取 meta 条目里显式声明的能力（兼容 ``capability`` 单值旧写法）。"""
    if not isinstance(entry, dict):
        return []
    raw = entry.get("capabilities")
    if raw is None:
        raw = entry.get("capability")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Iterable):
        return []
    out: List[str] = []
    for cap in raw:
        cap = str(cap or "").strip()
        if cap in AUDIO_CHANNELS and cap not in out:
            out.append(cap)
    return out


# ---------- 参数 schema（模型自己声明，底部参数栏据此渲染） ----------
# 统一参数名是“平台语义”，不是任何一家的字段名：adapter 负责把
# preview_text/format/sample_rate/... 映射到厂商实际字段。
# source：prompt = 复用主提示词框（不渲染控件，只参与校验）；refs = 只读展示参考栏数量。

AUDIO_PARAM_TYPES = ("text", "bool", "enum", "number", "refs")

# 未声明 params 时的默认集（顺序 = 界面顺序）
DEFAULT_AUDIO_PARAMS: Dict[str, List[Dict[str, Any]]] = {
    AUDIO_CHANNEL_VOICE_DESIGN: [
        # 上限取各家最大值（百炼 500 / 火山 200 / ElevenLabs 1000），
        # 前端不误拦；精确长度由各适配器按自家规则报可读错误。
        # required=False：上传参考音频复刻时可以不写文字描述（二选一，后端校验）
        {"key": "prompt", "type": "text", "source": "prompt", "required": False,
         "max_len": 1000, "label": "音色描述"},
        {"key": "preview_text", "type": "text", "required": True, "multiline": True,
         "min_len": 15, "max_len": 1000, "label": "试听文本", "placeholder": "15-300 字"},
        # 参考音频不在此通道展示（用户裁决 2026-10-31）：用自己音色的入口统一在语音合成的音色 ID 旁
        # （参考栏音频仍可作为复刻源：generate_audio 会把 references 转 audio_data）
        # 音色位：火山豆包语音控制台购买后分配（决定剩余设计次数）；其余平台不展示
        # （参数级 providers 限定，避免百炼等平台多出一个无意义的输入框）
        {"key": "voice_id", "type": "text", "label": "音色位 ID（火山专用）",
         "placeholder": "火山豆包语音需填音色位", "providers": ["volcengine-speech"]},
        {"key": "language", "type": "enum", "values": ["zh", "en"],
         "default": "zh", "label": "语言"},
        {"key": "sample_rate", "type": "enum", "values": ["16000", "24000", "48000"],
         "default": "24000", "label": "采样率"},
        {"key": "format", "type": "enum", "values": ["wav", "mp3"],
         "default": "wav", "label": "输出格式"},
    ],
    AUDIO_CHANNEL_TTS: [
        {"key": "prompt", "type": "text", "source": "prompt", "required": True,
         "label": "台词文本"},
        # clone（上传音频复刻建音色）不写在这里：由适配器能力注入
        # （见 _CLONE_ADAPTERS），避免未接复刻的平台也显示上传入口
        {"key": "voice_id", "type": "text", "required": True, "label": "音色 ID",
         "placeholder": "音色设计产出的 ID，或平台系统音色名",
         "note": "百炼：音色设计返回的 voice_id（推荐），或对应版本的平台音色（如 longanhuan_v3.1）；"
                 "硅基流动：model:voice；ElevenLabs：平台 Voice ID"},
        {"key": "language", "type": "enum",
         "values": ["Auto", "Chinese", "English", "Japanese"],
         "default": "Auto", "label": "语言"},
        {"key": "sample_rate", "type": "enum", "values": ["16000", "24000", "48000"],
         "default": "24000", "label": "采样率"},
        {"key": "format", "type": "enum", "values": ["wav", "mp3"],
         "default": "wav", "label": "输出格式"},
    ],
    AUDIO_CHANNEL_MUSIC: [
        # 与 lyrics 二选一：required=False，互斥校验归路由（require_one_of 语义）
        {"key": "prompt", "type": "text", "source": "prompt", "required": False,
         "max_len": 2000, "label": "音乐描述", "note": "与歌词二选一"},
        {"key": "lyrics", "type": "text", "multiline": True, "label": "歌词", "max_len": 350,
         "placeholder": "可选；与描述二选一"},
        {"key": "instrumental", "type": "bool", "default": True, "label": "纯音乐"},
        {"key": "gender", "type": "enum", "values": ["female", "male"],
         "default": "female", "label": "演唱性别", "when": "instrumental=false"},
        {"key": "format", "type": "enum", "values": ["mp3", "wav"],
         "default": "mp3", "label": "输出格式"},
        {"key": "watermark", "type": "bool", "default": False, "label": "AIGC 标识"},
    ],
    AUDIO_CHANNEL_SFX: [
        {"key": "prompt", "type": "text", "source": "prompt", "required": True,
         "max_len": 3000, "label": "音效描述"},
        # 音效不需要参考音频（用户裁决 2026-10-31）：参考音频只用于语音合成的声音复刻
        {"key": "channels", "type": "enum", "values": ["1", "2"],
         "default": "2", "label": "声道"},
        {"key": "volume", "type": "number", "min": 0, "max": 100, "step": 1,
         "default": "50", "label": "音量"},
        {"key": "rate", "type": "number", "min": 0.5, "max": 2, "step": 0.1,
         "default": "1", "label": "语速"},
        {"key": "sample_rate", "type": "enum", "values": ["16000", "24000", "48000"],
         "default": "48000", "label": "采样率"},
        {"key": "format", "type": "enum", "values": ["wav", "mp3"],
         "default": "wav", "label": "输出格式"},
        {"key": "watermark", "type": "bool", "default": False, "label": "AIGC 标识"},
    ],
}


def _norm_param_spec(raw: Any) -> Dict[str, Any] | None:
    """单条参数声明 → 规范 spec（非法/缺 key/enum 无 values 则丢弃）。"""
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or raw.get("name") or "").strip()
    if not key:
        return None
    ptype = str(raw.get("type") or "text").strip().lower()
    if ptype not in AUDIO_PARAM_TYPES:
        ptype = "text"
    spec: Dict[str, Any] = {"key": key, "type": ptype, "required": bool(raw.get("required"))}
    label = str(raw.get("label") or "").strip()
    if label:
        spec["label"] = label
    channels = raw.get("channels")
    if isinstance(channels, list):
        valid = [str(c).strip() for c in channels if str(c).strip() in AUDIO_CHANNELS]
        if valid:
            spec["channels"] = valid
    for name in ("default", "placeholder", "note", "when"):
        if raw.get(name) not in (None, ""):
            spec[name] = raw[name]
    # 界面形态：multiline = 多行宽输入框（试听文本/歌词这类长文本）
    if raw.get("multiline"):
        spec["multiline"] = True
    # 音色输入旁提供「上传音频创建音色」入口（语音合成）
    if raw.get("clone"):
        spec["clone"] = True
    # 音色输入旁提供「拉取平台音色」入口（仅实测接通列表接口的适配器）
    if raw.get("list_voices"):
        spec["list_voices"] = True
    # 参数级供应商限定：只在指定适配器的供应商下展示（如火山音色位 ID）
    only_providers = raw.get("providers")
    if isinstance(only_providers, list):
        valid_providers = [str(p).strip() for p in only_providers if str(p).strip()]
        if valid_providers:
            spec["providers"] = valid_providers
    if raw.get("source") in ("prompt", "draft", "refs"):
        spec["source"] = raw["source"]
    for name in ("min", "max", "step", "min_len", "max_len"):
        if isinstance(raw.get(name), (int, float)):
            spec[name] = raw[name]
    values = raw.get("values")
    if isinstance(values, list):
        spec["values"] = [str(v) for v in values if str(v).strip()]
    if ptype == "enum" and not spec.get("values"):
        return None
    return spec


def declared_params(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """读取 meta 条目的参数声明（支持 list 或 ``{key: spec}`` 两种写法）。"""
    raw = entry.get("params") if isinstance(entry, dict) else None
    if isinstance(raw, dict):
        raw = [{"key": key, **(val if isinstance(val, dict) else {})} for key, val in raw.items()]
    if not isinstance(raw, list):
        return []
    return [spec for spec in (_norm_param_spec(item) for item in raw) if spec]


# 已知模型级参数剔除（模型确实不接受该参数时，界面不展示，避免“填了也没用”）
_MODEL_PARAM_DROPS: Dict[str, tuple] = {
    "fun-music-preview": ("gender",),          # preview 不支持演唱性别
    "minimax/speech-2.8-hd": ("language",),     # 适配器未映射 language_boost
    "minimax/speech-2.8-turbo": ("language",),
}

# 通道级参数剔除（用户裁决 2026-10-31：音效不需要参考音频）。
# 配置里显式声明残留的 refs 也一并剔除——旧配置不能把已裁决去掉的入口带回来。
_CHANNEL_PARAM_DROPS: Dict[str, tuple] = {AUDIO_CHANNEL_SFX: ("refs",)}

# 支持「上传音频 → 复刻建音色」的适配器（create_voice 已接 audio_data）：
# dashscope 百炼 voice-enrollment；火山 / ElevenLabs 的复刻接口未接入，
# 不下发展示上传入口，避免用户点了才看到“暂未接入”。
_CLONE_ADAPTERS = ("dashscope",)
# 百炼托管的第三方语音（MiniMax）不支持 voice-enrollment 复刻：不展示上传入口
_CLONE_MODEL_DROPS = ("minimax",)

# 支持「拉取平台音色列表」的适配器（list_voices 已接，且列表自带试听）：
# ElevenLabs GET /voices 实测有 preview_url；百炼 list 动作待实测、火山无列表接口
#（实测 /v1/models 等全 404，只能看控制台音色库），不下发「拉取音色」入口。
_VOICE_LIST_ADAPTERS = ("elevenlabs",)


def audio_params_for_entry(
    entry: Dict[str, Any], capabilities: List[str], model: str = "", adapter_kind: str = "",
) -> List[Dict[str, Any]]:
    """某模型的参数清单：显式 params 优先，否则按能力合并默认集。

    ``adapter_kind`` 非空时，带 ``providers`` 限定的参数只在对应适配器下下发
    （未知适配器不过滤，避免旧配置被误删）。
    """
    caps = [c for c in (capabilities or []) if c in AUDIO_CHANNELS]
    drops = set(_MODEL_PARAM_DROPS.get(str(model or "").strip().lower(), ()))

    def keep(spec: Dict[str, Any]) -> bool:
        only = spec.get("providers")
        if only and adapter_kind and adapter_kind not in only:
            return False
        for ch in spec.get("channels") or ():
            if spec["key"] in _CHANNEL_PARAM_DROPS.get(ch, ()):
                return False
        return True

    def mark_clone(spec: Dict[str, Any]) -> None:
        """音色输入旁的「上传音频复刻」入口，只给已接复刻的适配器（tts 通道）。"""
        if spec.get("key") != "voice_id" or not adapter_kind:
            return
        if "tts" not in (spec.get("channels") or caps):
            return
        if adapter_kind in _CLONE_ADAPTERS and not any(
                hint in str(model or "").lower() for hint in _CLONE_MODEL_DROPS):
            spec["clone"] = True
        else:
            spec.pop("clone", None)

    def mark_voice_list(spec: Dict[str, Any]) -> None:
        """音色输入旁的「拉取平台音色」入口，只给已接列表接口的适配器（tts 通道）。"""
        if spec.get("key") != "voice_id" or not adapter_kind:
            return
        if "tts" not in (spec.get("channels") or caps):
            return
        if adapter_kind in _VOICE_LIST_ADAPTERS:
            spec["list_voices"] = True
        else:
            spec.pop("list_voices", None)

    declared = declared_params(entry)
    if declared:
        kept: List[Dict[str, Any]] = []
        for spec in declared:
            spec.setdefault("channels", list(caps))
            if spec["key"] in drops or not keep(spec):
                continue
            mark_clone(spec)
            mark_voice_list(spec)
            kept.append(spec)
        return kept
    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for cap in caps:
        for spec in DEFAULT_AUDIO_PARAMS.get(cap, []):
            marker = (cap, spec["key"])
            if marker in seen or spec["key"] in drops:
                continue
            item = dict(spec)
            item["channels"] = [cap]
            if not keep(item):
                continue
            seen.add(marker)
            mark_clone(item)
            mark_voice_list(item)
            merged.append(item)
    return merged


def audio_params_for(
    provider: Dict[str, Any], model: str, channel: str,
) -> List[Dict[str, Any]]:
    """查某供应商某模型在某通道下的参数清单（服务端校验/测试用）。"""
    for entry in audio_models_meta_of(provider):
        if entry["model"] != str(model or "").strip():
            continue
        return [
            spec for spec in entry.get("params") or []
            if not spec.get("channels") or channel in spec["channels"]
        ]
    return []


def audio_models_meta_of(provider: Dict[str, Any]) -> List[Dict[str, Any]]:
    """供应商配置 → 音频模型能力清单 ``[{model, capabilities, params}]``。

    模型集合 = ``audio_models`` ∪ ``audio_models_meta[].model``（只声明 meta
    的配置同样生效）；能力 = 显式声明 > 模型名推导；参数 = 显式 params > 通道默认。
    返回值不回写配置。
    """
    if not isinstance(provider, dict):
        return []
    entries: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for entry in provider.get("audio_models_meta") or []:
        if not isinstance(entry, dict):
            continue
        model = str(entry.get("model") or "").strip()
        if not model:
            continue
        if model not in order:
            order.append(model)
        entries[model] = entry
    for model in provider.get("audio_models") or []:
        model = str(model or "").strip()
        if model and model not in order:
            order.append(model)
    out: List[Dict[str, Any]] = []
    adapter_kind = audio_adapter_kind(provider)
    for model in order:
        entry = entries.get(model) or {}
        caps = declared_capabilities(entry) or infer_audio_capabilities(model)
        out.append({
            "model": model,
            "capabilities": caps,
            "params": audio_params_for_entry(entry, caps, model, adapter_kind),
        })
    return out


def models_for_channel(provider: Dict[str, Any], channel: str) -> List[str]:
    """某供应商在指定通道下可选的模型列表（顺序 = 配置顺序）。"""
    channel = str(channel or "").strip()
    if channel not in AUDIO_CHANNELS:
        return []
    return [
        str(entry["model"]) for entry in audio_models_meta_of(provider)
        if channel in (entry.get("capabilities") or [])
    ]


def model_supports_channel(model: str, channel: str, provider: Dict[str, Any] | None = None) -> bool:
    """模型是否支持该通道（显式 meta 优先，未声明按模型名推导）。"""
    channel = str(channel or "").strip()
    if channel not in AUDIO_CHANNELS:
        return False
    model = str(model or "").strip()
    if not model:
        return False
    if provider:
        for entry in audio_models_meta_of(provider):
            if entry["model"] == model:
                return channel in (entry.get("capabilities") or [])
    return channel in infer_audio_capabilities(model)


def first_model_for_channel(providers: Iterable[Dict[str, Any]], channel: str) -> tuple:
    """首个可用的 (provider_id, model)；无则 ("", "")（不臆造）。"""
    for provider in providers or []:
        if not isinstance(provider, dict) or not provider.get("enabled", True):
            continue
        models = models_for_channel(provider, channel)
        if models:
            return str(provider.get("id") or ""), models[0]
    return "", ""


# 按域名兜底认适配器：设置页保存会把未在表单里展示的字段整条覆盖丢掉，
# 适配器选择不能因此失效（用户仅改 base_url 也会丢 audio_request_mode）。
_ADAPTER_BY_HOST = (
    ("elevenlabs.io", "elevenlabs"),
    ("openspeech.bytedance.com", "volcengine-speech"),
    ("siliconflow.cn", "openai-speech"),
    ("maas.aliyuncs.com", "dashscope"),
    ("dashscope.aliyuncs.com", "dashscope"),
)


def audio_adapter_kind(cfg: Dict[str, Any]) -> str:
    """供应商可用的音频适配器（空 = 尚未接入，前端用于标“未接音频”）。

    与 web/generation_audio._build_adapter 同口径：
    - openai-speech：OpenAI 兼容 /audio/speech（硅基流动/OpenAI/Groq…）
    - elevenlabs：ElevenLabs 原生（xi-api-key；音色设计/TTS/音效）
    - volcengine-speech：火山豆包语音 V3（音色设计/合成/音效）
    - dashscope：百炼原生音频（DashScope/MaaS 专属域名）
    """
    if not isinstance(cfg, dict):
        return ""
    mode = str(cfg.get("audio_request_mode") or "").strip().lower()
    if mode == "openai-speech":
        return "openai-speech"
    if mode == "elevenlabs":
        return "elevenlabs"
    if mode == "volcengine-speech" or str(cfg.get("protocol") or "").lower() == "volcengine-speech":
        return "volcengine-speech"
    base = str(cfg.get("base_url") or "").lower()
    for host, kind in _ADAPTER_BY_HOST:
        if host in base:
            return kind
    return ""
