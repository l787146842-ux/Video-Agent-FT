"""DashScope 原生音频适配器（阿里百炼音频三件套）。

覆盖百炼「音频」模型族的原生 HTTP 接口（不走 OpenAI 兼容前缀）：
- 音色设计（声音设计）: ``POST {root}/api/v1/services/audio/tts/customization``
  （``model=voice-enrollment``，返回 voice_id + 预览音频 base64）；
- 音乐生成: ``POST {root}/api/v1/services/audio/music/generation``（Fun-Music）；
- 音效/多人对话: ``POST {root}/api/v1/services/audio/tts/SpeechSynthesizer``
  （qwen-audio-*-tts-next）；
- 语音合成: ``POST {root}/api/v1/services/aigc/multimodal-generation/generation``
  （Qwen-Audio-TTS / MiniMax speech-*）。

``root`` 由供应商 ``base_url`` 归一化而来：百炼控制台的兼容入口形如
``https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1``，
原生音频接口在同一个 host 的 ``/api/v1/...`` 下，故先剥掉兼容前缀。

边界：本适配器只做 HTTP 与响应解析，不落盘、不读本地文件（本地素材 → data URI
的转换在调用方完成）；失败一律抛 ``AdapterError``（含 http_status，429/5xx 可重试）。
"""
import base64
import binascii
import json
import re
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from src.video_agent.adapters.audio_error_hints import friendly_hint

from src.video_agent.adapters.errors import (
    KIND_AUTH,
    KIND_NETWORK,
    KIND_PARAM,
    KIND_QUOTA,
    KIND_TIMEOUT,
    KIND_UPSTREAM,
    classify_status,
)
from src.video_agent.adapters.base import (
    AudioDesignResponse,
    AudioGenerationResponse,
    BaseAudioAdapter,
)
from src.video_agent.exceptions import AdapterError

VOICE_DESIGN_PATH = "/api/v1/services/audio/tts/customization"
MUSIC_PATH = "/api/v1/services/audio/music/generation"
SFX_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"
# MiniMax speech 走多模态生成；Qwen-Audio-TTS / CosyVoice 走 SFX_PATH（官方 HTTP 文档）
TTS_PATH = "/api/v1/services/aigc/multimodal-generation/generation"

# 合成目标语言（前端中文值 → 接口 language_hints 代码）；Auto 不传让模型自判
_LANG_HINTS = {
    "chinese": "zh", "english": "en", "japanese": "ja",
    "zh": "zh", "en": "en", "ja": "ja",
}

# 兼容入口前缀（从长到短剥；``/api/v1`` 本身是原生根，也剥掉再统一拼）
_COMPAT_SUFFIXES = ("/compatible-mode/v1", "/compatible-mode", "/api/v1")
_PREFIX_RE = re.compile(r"[^0-9A-Za-z]")


def dashscope_root(base_url: str) -> str:
    """供应商 base_url → 百炼原生音频根地址（scheme + host）。

    空串返回空串（调用方负责报错）；非百炼地址原样保留（去掉末尾斜杠）。
    """
    root = str(base_url or "").strip().rstrip("/")
    for suffix in _COMPAT_SUFFIXES:
        if root.endswith(suffix):
            root = root[: -len(suffix)].rstrip("/")
            break
    return root


def _safe_prefix(prefix: str) -> str:
    """音色名前缀：只留字母数字，≤10 字符（接口硬约束）。"""
    cleaned = _PREFIX_RE.sub("", str(prefix or ""))
    return (cleaned or "vd")[:10]


def _kind_for_status(status: int) -> str:
    if status in (401, 403):
        return KIND_AUTH
    if status == 429:
        return KIND_QUOTA
    if status in (400, 404, 422):
        return KIND_PARAM
    if status >= 500:
        return KIND_UPSTREAM
    return classify_status(status)[1]


def _http_error(status: int, body: str, *, context: str) -> AdapterError:
    snippet = (body or "").strip()[:300]
    # 已收录的“需用户去控制台操作”的码 → 换成可操作提示
    code = ""
    detail = ""
    try:
        payload = json.loads(body or "{}")
        if isinstance(payload, dict):
            code = str(payload.get("code") or "")
            detail = str(payload.get("message") or "")
    except (ValueError, TypeError):
        pass
    hint = friendly_hint(code, detail)
    message = (f"{context}失败（{code}）：{hint}" if hint
               else f"{context}返回 HTTP {status}: {snippet or '(空响应体)'}")
    return AdapterError(
        message,
        retryable=status == 429 or status >= 500,
        http_status=status,
        kind=_kind_for_status(status),
    )


def _decode_b64(data: str) -> bytes:
    try:
        return base64.b64decode(str(data or ""))
    except (binascii.Error, ValueError):
        return b""


class DashScopeAudioAdapter(BaseAudioAdapter):
    """百炼原生音频适配器（一个供应商实例复用于四条通道）。"""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 300.0) -> None:
        self._root = dashscope_root(base_url)
        if not self._root:
            raise AdapterError("音频供应商缺少 Base URL，请在 API 设置页补全")
        self._api_key = str(api_key or "")
        self._timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------- 通用 POST ----------

    async def _post(self, path: str, payload: Dict[str, Any], *, context: str) -> Dict[str, Any]:
        client = self._get_client()
        url = f"{self._root}{path}"
        try:
            resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise AdapterError(
                f"{context}超时（{self._timeout:g}s），请稍后重试或降低生成规模",
                retryable=True, kind=KIND_TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(
                f"{context}请求失败（{type(exc).__name__}）: {str(exc)[:200]}",
                retryable=True, kind=KIND_NETWORK,
            ) from exc

        if resp.status_code >= 400:
            logger.warning(f"[DashScopeAudio] {context} HTTP {resp.status_code}: {resp.text[:300]}")
            raise _http_error(resp.status_code, resp.text, context=context)
        try:
            data = resp.json()
        except ValueError as exc:
            raise AdapterError(
                f"{context}返回非 JSON 响应: {resp.text[:200]}",
                retryable=False, kind=KIND_UPSTREAM,
            ) from exc
        if isinstance(data, dict) and data.get("code"):
            # 百炼错误信封：HTTP 200 + {code, message}（模型不存在/参数非法/审核未过）
            code = str(data.get("code") or "")
            hint = friendly_hint(code, str(data.get("message") or ""))
            detail = hint or (data.get("message") or "")
            raise AdapterError(
                f"{context}失败（{code}）：{detail}".strip(),
                retryable=False, kind=KIND_PARAM,
            )
        return data if isinstance(data, dict) else {}

    # ---------- 音色设计 ----------

    async def design_voice(
        self, *, target_model: str, voice_prompt: str, preview_text: str,
        prefix: str = "", language: str = "zh",
        sample_rate: int = 24000, response_format: str = "wav",
        speaker_id: str = "", audio_data: str = "",
    ) -> AudioDesignResponse:
        sample = str(audio_data or "").strip()
        prompt = str(voice_prompt or "").strip()
        if not sample and not prompt:
            raise AdapterError(
                "音色设计需要音色描述或参考音频（至少一项）",
                retryable=False, kind=KIND_PARAM)
        payload_input: Dict[str, Any] = {
            "action": "create_voice",
            "target_model": target_model,
            "preview_text": preview_text,
            "prefix": _safe_prefix(prefix),
            "language_hints": [language or "zh"],
        }
        if sample:
            # 声音复刻：上传参考音频直接建音色（与 voice_prompt 二选一）
            payload_input["audio_data"] = sample
        else:
            payload_input["voice_prompt"] = prompt
        payload = {
            "model": "voice-enrollment",
            "input": payload_input,
            "parameters": {
                "sample_rate": int(sample_rate or 24000),
                "response_format": response_format or "wav",
            },
        }
        data = await self._post(VOICE_DESIGN_PATH, payload, context="音色设计")
        output = data.get("output") or {}
        preview = output.get("preview_audio") or {}
        return AudioDesignResponse(
            voice_id=str(output.get("voice_id") or ""),
            preview_audio=_decode_b64(preview.get("data") or ""),
            sample_rate=int(preview.get("sample_rate") or sample_rate or 24000),
            response_format=str(preview.get("response_format") or response_format or "wav"),
            target_model=str(output.get("target_model") or target_model),
            status=str(output.get("status") or ""),
            raw_response=data,
        )

    # ---------- 语音合成 ----------

    async def synthesize(
        self, *, model: str, text: str, voice_id: str,
        language: str = "Auto", audio_format: str = "wav",
        sample_rate: int = 24000, speed: Optional[float] = None,
        volume: Optional[float] = None, pitch: Optional[int] = None,
        emotion: str = "",
    ) -> AudioGenerationResponse:
        lowered = str(model or "").lower()
        is_minimax = "minimax" in lowered or "speech-" in lowered
        if is_minimax:
            voice_setting: Dict[str, Any] = {"voice_id": voice_id}
            if speed is not None:
                voice_setting["speed"] = float(speed)
            if volume is not None and 0 < float(volume) <= 10.0:
                voice_setting["vol"] = float(volume)
            if pitch is not None:
                voice_setting["pitch"] = int(pitch)
            if emotion:
                voice_setting["emotion"] = emotion
            payload = {
                "model": model,
                "input": {
                    "text": text,
                    "voice_setting": voice_setting,
                    "audio_setting": {
                        "sample_rate": int(sample_rate or 32000),
                        "format": audio_format or "mp3",
                    },
                    # 统一以 URL 返回（默认 hex 内联，前端卡片无法直接播放）
                    "output_format": "url",
                },
            }
        else:
            # Qwen-Audio-TTS / CosyVoice：非实时语音合成端点 = SpeechSynthesizer
            # （官方与 Fun 音效同路径；multimodal-generation 会报 url error）
            payload_input: Dict[str, Any] = {
                "text": text,
                "voice": voice_id,
                "format": audio_format or "wav",
                "sample_rate": int(sample_rate or 24000),
            }
            hint = _LANG_HINTS.get(str(language or "").strip().lower(), "")
            if hint:
                payload_input["language_hints"] = [hint]
            if speed is not None:
                payload_input["rate"] = float(speed)
            if volume is not None and 0 <= float(volume) <= 100:
                payload_input["volume"] = int(volume)
            if pitch is not None and 0.5 <= float(pitch) <= 2.0:
                payload_input["pitch"] = float(pitch)
            payload = {"model": model, "input": payload_input}
        data = await self._post(
            TTS_PATH if is_minimax else SFX_PATH,
            payload, context="语音合成",
        )
        return _generation_response(data, audio_format)

    # ---------- 音乐生成 ----------

    async def generate_music(
        self, *, model: str, prompt: str, lyrics: str = "",
        instrumental: bool = True, gender: str = "",
        audio_format: str = "mp3", watermark: bool = False,
    ) -> AudioGenerationResponse:
        payload_input: Dict[str, Any] = {
            "prompt": prompt,
            "is_instrumental": bool(instrumental),
            "format": audio_format or "mp3",
            "enable_aigc_watermark": bool(watermark),
        }
        if lyrics.strip():
            payload_input["lyrics"] = lyrics.strip()
        # gender 仅 fun-music-v1 支持，且纯音乐模式下无效
        if gender and not instrumental and "preview" not in str(model).lower():
            payload_input["gender"] = gender
        data = await self._post(
            MUSIC_PATH, {"model": model, "input": payload_input}, context="音乐生成",
        )
        return _generation_response(data, audio_format)

    # ---------- 音效 / 环境音 ----------

    async def generate_sfx(
        self, *, model: str, text_prompt: str,
        references: Optional[List[str]] = None, audio_format: str = "wav",
        sample_rate: int = 48000, channels: int = 2, volume: int = 50,
        rate: float = 1.0, seed: int = 42, aigc_tag: bool = False,
    ) -> AudioGenerationResponse:
        refs: List[Dict[str, str]] = []
        for raw in references or []:
            ref = str(raw or "").strip()
            if not ref:
                continue
            if ref.startswith("data:"):
                refs.append({"audio_data": ref})
            else:
                refs.append({"audio_url": ref})
        payload_input: Dict[str, Any] = {
            "text_prompt": text_prompt,
            "format": audio_format or "wav",
            "sample_rate": int(sample_rate or 48000),
            "channels": int(channels or 2),
            "volume": int(volume if volume is not None else 50),
            "rate": float(rate or 1.0),
            "seed": int(seed or 42),
            "enable_aigc_tag": bool(aigc_tag),
        }
        if refs:
            payload_input["references"] = refs
        data = await self._post(
            SFX_PATH, {"model": model, "input": payload_input}, context="音效生成",
        )
        return _generation_response(data, audio_format)


def _generation_response(data: Dict[str, Any], audio_format: str) -> AudioGenerationResponse:
    """统一解析 ``output.audio``（URL 优先，其次内联 data）。"""
    output = data.get("output") or {}
    audio = output.get("audio") or {}
    usage = data.get("usage") or {}
    extra = output.get("extra_info") or {}
    return AudioGenerationResponse(
        audio_url=str(audio.get("url") or ""),
        audio_bytes=_decode_b64(audio.get("data") or ""),
        sample_rate=int(extra.get("sample_rate") or audio.get("sample_rate") or 0),
        audio_format=str(audio_format or ""),
        duration=float(usage.get("duration") or audio.get("duration") or 0.0),
        raw_response=data,
    )
