"""火山引擎「豆包语音」V3 适配器（音色设计 / 语音合成 / 音效）。

官方接口（新版控制台，``X-Api-Key`` 单头鉴权）：
- 音色设计: ``POST {root}/api/v3/tts/voice_design`` → ``speaker_id`` + ``demo_audio``（URL，1h 有效）
- 音频生成: ``POST {root}/api/v3/tts/create``
    * 音效：只传 ``text_prompt``（纯文本生成，最长 120 秒）
    * 语音合成：额外传 ``speaker``（音色 ID）；``speaker`` / ``audio_data`` / ``audio_url`` 三者互斥

鉴权两种写法（同一个适配器都支持）：
1. 新版（推荐）：API Key 填控制台「API Key 管理」拿到的那串 → ``X-Api-Key``；
2. 旧版：Key 填 ``appid|access_token`` → ``X-Api-App-Key`` + ``X-Api-Access-Key`` 双头。
两者都必须带 ``X-Api-Request-Id``（uuid）。

音乐生成（seed-music 等）不在本适配器范围，``generate_music`` 明确报错。

边界：只做 HTTP 与响应解析，不落盘；失败一律抛 ``AdapterError``（含 http_status）。
"""
import base64
import binascii
import uuid
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from src.video_agent.adapters.base import (
    AudioDesignResponse,
    AudioGenerationResponse,
    BaseAudioAdapter,
)
from src.video_agent.adapters.errors import (
    KIND_NETWORK,
    KIND_PARAM,
    KIND_TIMEOUT,
    KIND_UPSTREAM,
    classify_status,
)
from src.video_agent.exceptions import AdapterError

DESIGN_PATH = "/api/v3/tts/voice_design"
GENERATE_PATH = "/api/v3/tts/create"
DEFAULT_AUDIO_MODEL = "seed-audio-1.0"

# 平台硬限制（超出接口直接 4xx，提前拦下给出可读原因）
VOICE_PROMPT_MAX = 200      # prompt.text_prompt
PREVIEW_TEXT_MAX = 300      # text（试听文本）
SFX_PROMPT_MAX = 2000       # text_prompt

_FORMATS = {"wav", "mp3", "pcm", "ogg_opus"}


def parse_credentials(api_key: str, appid: str = "") -> tuple:
    """凭据归一化 → ``(token, appid)``。

    ``appid|access_token[|cluster]`` 视为旧版双头凭据（token 取第二段）；
    其余情况当作新版 API Key，appid 为空。
    """
    raw = str(api_key or "").strip()
    if "|" in raw:
        parts = [p.strip() for p in raw.split("|")]
        head = parts[0] if parts else ""
        token = parts[1] if len(parts) > 1 else ""
        return (token or head, appid or head)
    return (raw, str(appid or "").strip())


def _http_error(status: int, body: str, *, context: str) -> AdapterError:
    snippet = (body or "").strip()[:300]
    return AdapterError(
        f"{context}返回 HTTP {status}: {snippet or '(空响应体)'}",
        retryable=status == 429 or status >= 500,
        http_status=status,
        kind=classify_status(status)[1],
    )


def _decode_b64(data: str) -> bytes:
    try:
        return base64.b64decode(str(data or ""))
    except (binascii.Error, ValueError):
        return b""


class VolcengineSpeechAdapter(BaseAudioAdapter):
    """豆包语音 V3 适配器（一个供应商实例复用于三条通道）。"""

    def __init__(
        self, base_url: str, api_key: str, *, timeout: float = 300.0,
        appid: str = "", cluster: str = "",
    ) -> None:
        root = str(base_url or "").strip().rstrip("/") or "https://openspeech.bytedance.com"
        # 官方文档每个功能一个端点（voice_design / create / unidirectional …），用户很容易
        # 把完整端点粘进 base_url。统一剥到主机：这层容错比要求用户“填对”更可靠。
        marker = root.find("/api/")
        if marker > 0:
            root = root[:marker]
        self._root = root.rstrip("/")
        self._token, self._appid = parse_credentials(api_key, appid)
        self._cluster = str(cluster or "")
        self._timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Request-Id": str(uuid.uuid4()),
        }
        if self._appid:
            headers["X-Api-App-Key"] = self._appid
            headers["X-Api-Access-Key"] = self._token
        else:
            headers["X-Api-Key"] = self._token
        return headers

    async def _post_json(
        self, path: str, payload: Dict[str, Any], *, context: str,
    ) -> Dict[str, Any]:
        client = self._get_client()
        url = f"{self._root}{path}"
        try:
            resp = await client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise AdapterError(
                f"{context}超时（{self._timeout:g}s），请稍后重试或缩短文本",
                retryable=True, kind=KIND_TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(
                f"{context}请求失败（{type(exc).__name__}）: {str(exc)[:200]}",
                retryable=True, kind=KIND_NETWORK,
            ) from exc
        if resp.status_code >= 400:
            logger.warning(f"[VolcSpeech] {context} HTTP {resp.status_code}: {resp.text[:300]}")
            raise _http_error(resp.status_code, resp.text, context=context)
        try:
            data = resp.json()
        except ValueError as exc:
            raise AdapterError(
                f"{context}返回非 JSON 响应: {resp.text[:200]}",
                retryable=False, kind=KIND_UPSTREAM,
            ) from exc
        if not isinstance(data, dict):
            raise AdapterError(f"{context}返回格式异常", retryable=False, kind=KIND_UPSTREAM)
        # 火山错误信封：HTTP 200 + {code, message}
        code = data.get("code")
        if code not in (None, 0, "0"):
            raise AdapterError(
                f"{context}失败（{code}）：{data.get('message') or ''}".strip(),
                retryable=False, kind=KIND_PARAM,
            )
        return data

    async def _download(self, url: str, *, context: str) -> bytes:
        """把平台返回的临时 URL（音色预览）取成字节。"""
        client = self._get_client()
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise AdapterError(
                f"{context}预览音频下载失败（{type(exc).__name__}）",
                retryable=True, kind=KIND_NETWORK,
            ) from exc
        if resp.status_code >= 400 or not resp.content:
            raise AdapterError(
                f"{context}预览音频下载失败（HTTP {resp.status_code}）",
                retryable=True, kind=KIND_UPSTREAM,
            )
        return resp.content

    # ---------- 音色设计 ----------

    async def design_voice(
        self, *, target_model: str, voice_prompt: str, preview_text: str,
        prefix: str = "", language: str = "zh",
        sample_rate: int = 24000, response_format: str = "wav",
        speaker_id: str = "", audio_data: str = "",
    ) -> AudioDesignResponse:
        if str(audio_data or "").strip():
            # 火山声音复刻走独立签名接口（未接入）：不拿设计接口硬套
            raise AdapterError(
                "火山豆包语音的上传音频复刻暂未接入（当前只支持文字描述设计）",
                retryable=False, kind=KIND_PARAM)
        prompt = voice_prompt.strip()
        if not prompt:
            raise AdapterError("音色设计需要音色描述（提示词不能为空）",
                               retryable=False, kind=KIND_PARAM)
        if len(prompt) > VOICE_PROMPT_MAX:
            raise AdapterError(
                f"音色描述最长 {VOICE_PROMPT_MAX} 字（接口限制），当前 {len(prompt)} 字",
                retryable=False, kind=KIND_PARAM)
        text = preview_text.strip()
        if not text:
            raise AdapterError("音色设计需要试听文本（15-300 字）",
                               retryable=False, kind=KIND_PARAM)
        if len(text) > PREVIEW_TEXT_MAX:
            raise AdapterError(
                f"试听文本最长 {PREVIEW_TEXT_MAX} 字（接口限制），当前 {len(text)} 字",
                retryable=False, kind=KIND_PARAM)

        body: Dict[str, Any] = {"prompt": {"text_prompt": prompt}, "text": text}
        # speaker_id：控制台购买的音色位（决定「剩余设计次数」）；未购买可不传
        if speaker_id.strip():
            body["speaker_id"] = speaker_id.strip()
        body["language"] = 1 if str(language or "").lower() in ("en", "english") else 0

        data = await self._post_json(DESIGN_PATH, body, context="音色设计")
        new_speaker = str(data.get("speaker_id") or "").strip()
        status = data.get("status")
        if not new_speaker:
            raise AdapterError(
                f"音色设计未返回音色 ID（status={status}），请稍后重试或检查音色位是否还有设计次数",
                retryable=True, kind=KIND_UPSTREAM)
        demo_url = str(data.get("demo_audio") or "").strip()
        preview = await self._download(demo_url, context="音色设计") if demo_url else b""
        if not preview:
            # 音频还没生成完（status=1 Training）：明确告知，避免误以为成功
            raise AdapterError(
                f"音色 '{new_speaker}' 已创建但预览音频尚未就绪（status={status}），"
                "请稍后重试或到控制台试听",
                retryable=True, kind=KIND_UPSTREAM)
        # 预览 URL 带签名查询串（?x-expires=...），判断格式前先剥掉 query
        clean = demo_url.lower().split("?", 1)[0].split("#", 1)[0]
        return AudioDesignResponse(
            voice_id=new_speaker,
            preview_audio=preview,
            sample_rate=24000,
            response_format="mp3" if clean.endswith(".mp3") else "wav",
            target_model=target_model or "voice_design",
            status=str(status or ""),
            raw_response={"speaker_id": new_speaker, "status": status},
        )

    # ---------- 音频生成（音效 / 语音合成共用） ----------

    def _audio_config(
        self, *, audio_format: str, sample_rate: int, speed: Optional[float],
    ) -> Dict[str, Any]:
        fmt = str(audio_format or "wav").strip().lower()
        if fmt not in _FORMATS:
            fmt = "wav"
        config: Dict[str, Any] = {"format": fmt, "sample_rate": int(sample_rate or 24000)}
        if speed is not None and abs(float(speed) - 1.0) > 1e-6:
            # 火山 speech_rate：[-50,100]，50 表示 1.5 倍速、100 表示 2.0 倍速
            config["speech_rate"] = max(-50, min(100, int(round((float(speed) - 1.0) * 100))))
        return config

    async def _generate(
        self, *, payload: Dict[str, Any], audio_format: str,
        sample_rate: int, context: str,
    ) -> AudioGenerationResponse:
        data = await self._post_json(GENERATE_PATH, payload, context=context)
        audio = _decode_b64(str(data.get("audio") or ""))
        duration = float(data.get("duration") or 0.0)
        if audio:
            return AudioGenerationResponse(
                audio_bytes=audio, sample_rate=int(sample_rate or 24000),
                audio_format=str(audio_format or "wav"), duration=duration,
            )
        url = str(data.get("url") or "").strip()
        if url:
            return AudioGenerationResponse(
                audio_url=url, sample_rate=int(sample_rate or 24000),
                audio_format=str(audio_format or "wav"), duration=duration,
            )
        raise AdapterError(f"{context}未返回音频数据", retryable=True, kind=KIND_UPSTREAM)

    async def generate_sfx(
        self, *, model: str, text_prompt: str,
        references: Optional[List[str]] = None, audio_format: str = "wav",
        sample_rate: int = 48000, channels: int = 2, volume: int = 50,
        rate: float = 1.0, seed: int = 42, aigc_tag: bool = False,
    ) -> AudioGenerationResponse:
        text = text_prompt.strip()
        if not text:
            raise AdapterError("音效生成需要音效描述（提示词不能为空）",
                               retryable=False, kind=KIND_PARAM)
        if len(text) > SFX_PROMPT_MAX:
            raise AdapterError(
                f"音效描述最长 {SFX_PROMPT_MAX} 字（接口限制），当前 {len(text)} 字",
                retryable=False, kind=KIND_PARAM)
        payload: Dict[str, Any] = {
            "model": model or DEFAULT_AUDIO_MODEL,
            "text_prompt": text,
            "audio_config": self._audio_config(
                audio_format=audio_format, sample_rate=sample_rate,
                speed=rate if rate and abs(rate - 1.0) > 1e-6 else None),
        }
        ref = (references or [None])[0]
        if ref:
            # 参考音频：本地素材在上游已转 data URI，这里拆成纯 base64 给 audio_data
            if str(ref).startswith("data:") and ";base64," in str(ref):
                payload["audio_data"] = str(ref).split(";base64,", 1)[1]
            else:
                payload["audio_url"] = str(ref)
        return await self._generate(
            payload=payload, audio_format=audio_format,
            sample_rate=sample_rate, context="音效生成")

    async def synthesize(
        self, *, model: str, text: str, voice_id: str,
        language: str = "Auto", audio_format: str = "wav",
        sample_rate: int = 24000, speed: Optional[float] = None,
        volume: Optional[float] = None, pitch: Optional[int] = None,
        emotion: str = "",
    ) -> AudioGenerationResponse:
        speaker = voice_id.strip()
        if not speaker:
            raise AdapterError(
                "语音合成需要 voice_id：请先做音色设计，或填控制台里的音色 ID（如 zh_female_...）",
                retryable=False, kind=KIND_PARAM)
        payload: Dict[str, Any] = {
            "model": model or DEFAULT_AUDIO_MODEL,
            "text_prompt": text,
            "speaker": speaker,
            "audio_config": self._audio_config(
                audio_format=audio_format, sample_rate=sample_rate, speed=speed),
        }
        return await self._generate(
            payload=payload, audio_format=audio_format,
            sample_rate=sample_rate, context="语音合成")

    # ---------- 音乐（平台不支持） ----------

    async def generate_music(
        self, *, model: str, prompt: str, lyrics: str = "",
        instrumental: bool = True, gender: str = "",
        audio_format: str = "mp3", watermark: bool = False,
    ) -> AudioGenerationResponse:
        raise AdapterError(
            "豆包语音不提供音乐生成接口（只有语音/音色设计/音效）；"
            "背景音乐请换用百炼 Fun-Music 或其它音乐模型",
            retryable=False, kind=KIND_PARAM)


__all__ = ["VolcengineSpeechAdapter", "parse_credentials"]
