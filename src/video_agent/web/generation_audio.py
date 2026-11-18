"""音频生成分发（音色设计 / 语音合成 / 背景音乐 / 音效）。

职责：
1. 解析供应商端点（``base_url`` + API Key）并校验「模型是否支持该通道」；
2. 经 ``audio_channel`` 有界并发通道调用 ``DashScopeAudioAdapter``（429 退避 + 熔断）；
3. 把结果本地化到 ``workspace/assets/``（远程 URL 24 小时过期、音色预览是
   base64，两者都不能直接落卡）。

不做：任务登记/SSE/日志（归 routes/generate_audio）、草稿回写（归 task_manager）。
"""
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.adapters.dashscope_audio import DashScopeAudioAdapter
from src.video_agent.adapters.elevenlabs_audio import ElevenLabsAudioAdapter
from src.video_agent.adapters.fetch_adapter import get_media_fetch_adapter
from src.video_agent.adapters.openai_audio import OpenAIAudioAdapter
from src.video_agent.adapters.volcengine_speech import VolcengineSpeechAdapter
from src.video_agent.config import settings
from src.video_agent.core.audio_channels import (
    AUDIO_CHANNEL_MUSIC,
    AUDIO_CHANNEL_SFX,
    AUDIO_CHANNEL_TTS,
    AUDIO_CHANNEL_VOICE_DESIGN,
    AUDIO_CHANNELS,
    model_supports_channel,
)
from src.video_agent.core.provider_config import (
    get_api_key_async,
    get_provider_config_async,
    resolve_provider_ref_async,
)
from src.video_agent.exceptions import AdapterError, GenerationError
from src.video_agent.utils import gen_id
from src.video_agent.utils.paths import ASSETS_DIR
from src.video_agent.web.generation_channel import audio_channel

_ASSETS_PREFIX = "/workspace/assets/"
# 百炼原生音频（DashScope/MaaS 专属域名）
_DASHSCOPE_HOST_MARKERS = ("maas.aliyuncs.com", "dashscope.aliyuncs.com")
_FORMAT_EXTS = {"wav": "wav", "mp3": "mp3", "pcm": "pcm", "flac": "flac", "ogg": "ogg"}
# 参考音频扩展名（与 web/generation_submit.is_audio_url 同口径）：参考栏可能混入
# 图片/视频素材，非音频条目必须剔除（否则会把图片字节当 audio_data 发上游）
_AUDIO_REF_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".pcm")


def _is_audio_ref(url: str) -> bool:
    u = str(url or "").strip().lower().split("?")[0].split("#")[0]
    return u.endswith(_AUDIO_REF_EXTS)


def _asset_ext(fmt: str, fallback: str = "mp3") -> str:
    ext = _FORMAT_EXTS.get(str(fmt or "").strip().lower(), "")
    return ext or fallback


def _save_audio_bytes(data: bytes, fmt: str) -> str:
    """音频字节 → 本地素材 URL（写失败抛 GenerationError，不返回假地址）。"""
    if not data:
        raise GenerationError("供应商没有返回音频数据")
    name = f"{gen_id('audio')}.{_asset_ext(fmt)}"
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSETS_DIR / name
    try:
        path.write_bytes(data)
    except OSError as exc:
        raise GenerationError(f"音频落盘失败：{exc}") from exc
    return f"{_ASSETS_PREFIX}{name}"


async def _localize_remote(url: str, fmt: str) -> str:
    """远程音频 URL → 本地素材 URL（下载失败明确报错，不留过期外链）。"""
    result = await get_media_fetch_adapter().download(
        url, timeout=120, trust_env=False, follow_redirects=True,
        raise_on_http_error=True, max_retries=2, context="audio-generate",
    )
    return _save_audio_bytes(result.content, fmt)


def _local_ref_to_data_uri(url: str) -> str:
    """本地素材 → data URI（百炼参考音频只接受公网 URL 或 data URI）。

    ``/workspace/assets/x.wav`` 走磁盘读；其他地址原样返回（由上游按 URL 处理）。
    读失败返回空串（调用方跳过该条参考，不阻断主链路）。
    """
    raw = str(url or "").strip()
    if not raw.startswith(_ASSETS_PREFIX):
        return ""
    name = Path(raw).name
    path = ASSETS_DIR / name
    if not path.is_file():
        return ""
    try:
        content = path.read_bytes()
    except OSError:
        return ""
    mime = mimetypes.guess_type(name)[0] or "audio/wav"
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def _prepare_references(refs: Optional[List[str]]) -> List[str]:
    """参考音频：本地素材转 data URI，公网 URL 原样透传；非音频条目剔除。"""
    out: List[str] = []
    for ref in refs or []:
        raw = str(ref or "").strip()
        if not raw:
            continue
        if raw.startswith(("http://", "https://")):
            out.append(raw)
            continue
        if not _is_audio_ref(raw):
            continue  # 参考栏混入的图片/视频不参与音效参考
        uri = _local_ref_to_data_uri(raw)
        if uri:
            out.append(uri)
        else:
            logger.warning(f"[Audio] 参考音频不可用（跳过）：{raw[:120]}")
    return out


async def _resolve_endpoint(provider_id: str) -> Dict[str, Any]:
    """供应商 id/显示名 → {cfg, provider_id, base_url, api_key}。"""
    pid = await resolve_provider_ref_async(provider_id)
    if not pid:
        raise GenerationError("尚未选择音频供应商，请在参数栏或 API 设置页配置")
    cfg = await get_provider_config_async(pid)
    if not cfg:
        raise GenerationError(f"供应商 '{pid}' 未配置，请先在 API 设置页添加")
    base_url = str(cfg.get("base_url") or "").strip()
    if not base_url:
        raise GenerationError(f"供应商 '{pid}' 缺少 Base URL，无法调用音频接口")
    api_key = await get_api_key_async(pid)
    if not api_key:
        raise GenerationError(
            f"供应商 '{pid}' 未配置 API Key，请在「设置 → API 配置」填写后重试")
    return {"cfg": cfg, "provider_id": pid, "base_url": base_url, "api_key": api_key}


def _is_dashscope(base_url: str) -> bool:
    base = str(base_url or "").lower()
    return any(marker in base for marker in _DASHSCOPE_HOST_MARKERS)


async def clone_voice_via_provider(
    *, provider_id: str, target_model: str, audio_url: str,
    preview_text: str = "", language: str = "zh",
) -> Dict[str, Any]:
    """用一段参考音频创建音色（声音复刻），供语音合成填入 voice_id。

    与 `generate_audio_via_provider` 的 voice_design 分支同口径，但只做「建音色」：
    同步返回 voice_id + 预览音频 URL，不走生成任务队列（参数栏上传后立即回填）。
    平台不支持复刻时由适配器抛可读错误（不静默降级成文字设计）。
    """
    endpoint = await _resolve_endpoint(provider_id)
    cfg = endpoint["cfg"]
    pid = endpoint["provider_id"]
    # 目标模型 = 后续语音合成要用的模型，必须支持 tts 通道
    _check_channel(pid, cfg, target_model, AUDIO_CHANNEL_TTS)
    refs = _prepare_references([audio_url])
    if not refs:
        raise GenerationError("参考音频不可用：请上传 mp3/wav/m4a 等音频文件后重试")
    adapter = _build_adapter(
        cfg, endpoint["base_url"], endpoint["api_key"], AUDIO_CHANNEL_VOICE_DESIGN)
    # 百炼试听文本要求 15-200 字；参数栏不暴露这一项，用固定示例文本
    text = preview_text.strip() or "你好，我是这段声音的主人，很高兴为你讲述接下来的故事。"
    try:
        designed = await audio_channel.run(
            pid, adapter.design_voice,
            target_model=target_model, voice_prompt="", preview_text=text,
            prefix="", language=language or "zh",
            sample_rate=24000, response_format="wav",
            speaker_id="", audio_data=refs[0],
        )
    finally:
        await adapter.close()
    if not designed.voice_id:
        raise GenerationError(
            "供应商没有返回音色 ID：请确认参考音频可用（建议 10-60 秒、单人、干净人声）")
    preview_url = ""
    if designed.preview_audio:
        preview_url = _save_audio_bytes(
            designed.preview_audio, designed.response_format or "wav")
    return {
        "voice_id": designed.voice_id,
        "preview_url": preview_url,
        "target_model": designed.target_model or target_model,
        "provider_id": pid,
    }


async def list_voices_via_provider(*, provider_id: str, model: str) -> List[Dict[str, str]]:
    """拉取平台账号下的音色清单（供参数栏选择与试听）。

    只给已实测接通列表接口的适配器（当前 ElevenLabs ``GET /v1/voices``，列表自带
    ``preview_url``）；百炼列表动作待实测、火山无列表接口，由基类抛可读错误
    （不猜端点、不返回空列表假装成功）。
    """
    endpoint = await _resolve_endpoint(provider_id)
    cfg = endpoint["cfg"]
    pid = endpoint["provider_id"]
    _check_channel(pid, cfg, model, AUDIO_CHANNEL_TTS)
    adapter = _build_adapter(
        cfg, endpoint["base_url"], endpoint["api_key"], AUDIO_CHANNEL_TTS)
    try:
        voices = await audio_channel.run(pid, adapter.list_voices, model=model)
    except AdapterError as exc:
        raise GenerationError(str(exc)) from exc
    finally:
        await adapter.close()
    out: List[Dict[str, str]] = []
    seen: set = set()
    for item in voices or []:
        voice_id = str((item or {}).get("voice_id") or "").strip()
        if not voice_id or voice_id in seen:
            continue
        seen.add(voice_id)
        out.append({
            "voice_id": voice_id,
            "name": str(item.get("name") or "").strip(),
            "preview_url": str(item.get("preview_url") or "").strip(),
            "category": str(item.get("category") or "").strip(),
        })
    if not out:
        raise GenerationError("平台返回的音色列表为空：请先在平台控制台创建音色后重试")
    return out


def _build_adapter(cfg: Dict[str, Any], base_url: str, api_key: str, channel: str):
    """按供应商声明选音频适配器；未接入的平台明确报错（不盲调）。

    通道支持与否不在这一层拦（各平台差异大），由适配器自己报「不支持该通道」，
    这样新增平台只写适配器，不用回来改分发。
    """
    mode = str(cfg.get("audio_request_mode") or "").strip().lower()
    protocol = str(cfg.get("protocol") or "").strip().lower()
    base_lower = str(base_url or "").lower()
    timeout = float(settings.audio_gen_timeout)
    if mode == "openai-speech" or "siliconflow.cn" in base_lower:
        if channel != AUDIO_CHANNEL_TTS:
            raise GenerationError("该供应商只支持语音合成通道（OpenAI 兼容 /audio/speech）")
        # 硅基流动把音色编码为 model:voice，这个平台特性同样不能依赖配置字段
        # （设置页保存会把 audio_voice_join_model 一并清掉）
        voice_join = bool(cfg.get("audio_voice_join_model")) or "siliconflow.cn" in base_lower
        return OpenAIAudioAdapter(
            base_url, api_key, timeout=timeout, voice_join_model=voice_join,
        )
    # 域名兜底：设置页保存会丢掉表单未展示的字段（如 audio_request_mode），
    # 适配器选择不能因此失效，否则用户只改个 base_url 就变成“未接音频”。
    if mode == "elevenlabs" or "elevenlabs.io" in base_lower:
        return ElevenLabsAudioAdapter(base_url, api_key, timeout=timeout)
    if (mode == "volcengine-speech" or protocol == "volcengine-speech"
            or "openspeech.bytedance.com" in base_lower):
        return VolcengineSpeechAdapter(
            base_url, api_key, timeout=timeout,
            appid=str(cfg.get("volc_appid") or ""),
            cluster=str(cfg.get("volc_cluster") or ""),
        )
    if _is_dashscope(base_url):
        return DashScopeAudioAdapter(base_url, api_key, timeout=timeout)
    raise GenerationError(
        "该供应商尚未接入音频适配器（当前支持：阿里百炼原生音频 / "
        "OpenAI 兼容 /audio/speech / 火山豆包语音 V3 / ElevenLabs）；"
        "请在供应商配置声明 audio_request_mode")


def _check_channel(provider_id: str, cfg: Dict[str, Any], model: str, channel: str) -> None:
    """模型能力校验：不支持的组合明确报错（绝不静默换模型）。"""
    if channel not in AUDIO_CHANNELS:
        raise GenerationError(
            f"未知音频通道 '{channel}'（合法值：{'/'.join(AUDIO_CHANNELS)}）")
    if not str(model or "").strip():
        raise GenerationError("尚未选择音频模型，请在参数栏选择")
    if not model_supports_channel(model, channel, cfg):
        raise GenerationError(
            f"模型 '{model}' 不支持「{channel}」通道，请更换模型或通道（供应商 {provider_id}）")


async def generate_audio_via_provider(
    *,
    provider_id: str,
    model: str,
    channel: str,
    prompt: str = "",
    preview_text: str = "",
    language: str = "zh",
    sample_rate: int = 24000,
    audio_format: str = "",
    prefix: str = "",
    voice_id: str = "",
    lyrics: str = "",
    instrumental: bool = True,
    gender: str = "",
    watermark: bool = False,
    references: Optional[List[str]] = None,
    channels: int = 2,
    volume: int = 50,
    rate: float = 1.0,
    speed: Optional[float] = None,
    pitch: Optional[int] = None,
    emotion: str = "",
) -> Dict[str, Any]:
    """按通道调用音频供应商并返回本地化结果。

    返回：``{audio_url, voice_id, duration, sample_rate, target_model}``。
    """
    endpoint = await _resolve_endpoint(provider_id)
    cfg = endpoint["cfg"]
    pid = endpoint["provider_id"]
    _check_channel(pid, cfg, model, channel)

    adapter = _build_adapter(cfg, endpoint["base_url"], endpoint["api_key"], channel)
    try:
        if channel == AUDIO_CHANNEL_VOICE_DESIGN:
            # 描述/试听文本的精确长度限制各家不同（百炼 15-200、火山描述 200/试听 300、
            # ElevenLabs 100-1000），交由适配器按自家规则校验并报可读原因。
            # 参考音频（参考栏/参数栏上传）→ 声音复刻；与文字描述二选一。
            sample_refs = _prepare_references(references)[:1]
            if not prompt.strip() and not sample_refs:
                raise GenerationError("音色设计需要音色描述或参考音频（至少一项）")
            if not preview_text.strip():
                raise GenerationError("音色设计需要试听文本（用来试听音色的示例文本）")
            designed = await audio_channel.run(
                pid, adapter.design_voice,
                target_model=model, voice_prompt=prompt.strip(),
                preview_text=preview_text.strip(), prefix=prefix or "",
                language=language or "zh", sample_rate=int(sample_rate or 24000),
                response_format=audio_format or "wav",
                # 音色位：火山控制台购买后分配（决定剩余设计次数）；其余平台忽略
                speaker_id=voice_id.strip(),
                audio_data=sample_refs[0] if sample_refs else "",
            )
            # 落盘用适配器回报的实际格式（百炼返回 wav、火山预览可能是 mp3）
            url = _save_audio_bytes(
                designed.preview_audio, designed.response_format or audio_format or "wav")
            return {
                "audio_url": url, "voice_id": designed.voice_id,
                "duration": 0.0, "sample_rate": designed.sample_rate,
                "target_model": designed.target_model or model,
            }

        if channel == AUDIO_CHANNEL_MUSIC:
            if not prompt.strip() and not lyrics.strip():
                raise GenerationError("背景音乐需要音乐描述或歌词（至少一项）")
            fmt = audio_format or "mp3"
            result = await audio_channel.run(
                pid, adapter.generate_music,
                model=model, prompt=prompt.strip(), lyrics=lyrics,
                instrumental=bool(instrumental), gender=gender or "",
                audio_format=fmt, watermark=bool(watermark),
            )
        elif channel == AUDIO_CHANNEL_SFX:
            if not prompt.strip():
                raise GenerationError("音效生成需要音效描述（提示词不能为空）")
            fmt = audio_format or "wav"
            result = await audio_channel.run(
                pid, adapter.generate_sfx,
                model=model, text_prompt=prompt.strip(),
                references=_prepare_references(references),
                audio_format=fmt, sample_rate=int(sample_rate or 48000),
                channels=int(channels or 2), volume=int(volume),
                rate=float(rate or 1.0), aigc_tag=bool(watermark),
            )
        else:  # tts：已设计/已复刻音色 → 样音
            if not prompt.strip():
                raise GenerationError("语音合成需要台词文本（提示词不能为空）")
            if not voice_id.strip():
                raise GenerationError(
                    "语音合成需要 voice_id：请先在本卡完成音色设计，或绑定用户上传的音色参考")
            fmt = audio_format or "wav"
            # 界面上的「语速」参数（rate）对 TTS 即 speed；两者都没给则不传
            tts_speed = speed if speed is not None else (
                float(rate) if rate and abs(float(rate) - 1.0) > 1e-6 else None)
            result = await audio_channel.run(
                pid, adapter.synthesize,
                model=model, text=prompt.strip(), voice_id=voice_id.strip(),
                language=language or "Auto", audio_format=fmt,
                sample_rate=int(sample_rate or 24000), speed=tts_speed,
                volume=None if volume is None else float(volume),
                pitch=pitch, emotion=emotion or "",
            )

        if result.audio_url:
            local_url = await _localize_remote(result.audio_url, fmt)
        else:
            # 按适配器回报的**实际**格式落盘：部分平台（ElevenLabs）没有 wav，
            # 请求 wav 时会降级 mp3，照用户选择落盘会写出扩展名与内容不符的文件。
            local_url = _save_audio_bytes(result.audio_bytes, result.audio_format or fmt)
        return {
            "audio_url": local_url, "voice_id": "",
            "duration": result.duration, "sample_rate": result.sample_rate,
            "target_model": model,
        }
    except AdapterError as exc:
        raise GenerationError(str(exc)) from exc
    finally:
        await adapter.close()


__all__ = [
    "AUDIO_CHANNEL_MUSIC",
    "AUDIO_CHANNEL_SFX",
    "AUDIO_CHANNEL_TTS",
    "AUDIO_CHANNEL_VOICE_DESIGN",
    "clone_voice_via_provider",
    "generate_audio_via_provider",
    "list_voices_via_provider",
]
