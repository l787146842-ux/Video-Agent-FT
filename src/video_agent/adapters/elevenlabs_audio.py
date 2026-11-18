"""ElevenLabs 音频适配器（音色设计 / 语音合成 / 音效）。

官方接口（全部 ``xi-api-key`` 鉴权，不是 OpenAI 兼容协议）：
- 音色设计: ``POST {root}/text-to-voice/design`` → ``previews[0]``（base64 mp3 +
  ``generated_voice_id``），再 ``POST {root}/text-to-voice`` 用该 id 创建永久音色 → ``voice_id``；
- 语音合成: ``POST {root}/text-to-speech/{voice_id}`` → 二进制音频；
- 音效:     ``POST {root}/sound-generation`` → 二进制音频；
- 音色列表: ``GET {root}/voices`` → ``voice_id`` + ``name`` + ``preview_url``（可试听）。

不提供音乐生成，``generate_music`` 直接明确报错（不猜端点）。

两处平台限制值得记在代码里：
1. 输出格式只有 mp3/pcm 族，没有 wav；请求 wav 时降级 mp3 并回报真实格式，
   否则落盘会写出扩展名与内容不符的文件；
2. 音色设计的 ``text`` 必须 100-1000 字，短文本走 ``auto_generate_text``，
   由平台按描述自拟试听文本（比截断/补齐更诚实，用户仍能听到音色）。

边界：只做 HTTP 与响应解析，不落盘；失败一律抛 ``AdapterError``（含 http_status）。
"""
import base64
import binascii
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from src.video_agent.adapters.base import (
    AudioDesignResponse,
    AudioGenerationResponse,
    BaseAudioAdapter,
)
from src.video_agent.adapters.errors import (
    KIND_AUTH,
    KIND_NETWORK,
    KIND_PARAM,
    KIND_QUOTA,
    KIND_TIMEOUT,
    KIND_UPSTREAM,
    classify_status,
)
from src.video_agent.exceptions import AdapterError

DESIGN_PATH = "/text-to-voice/design"
CREATE_VOICE_PATH = "/text-to-voice"
TTS_PATH = "/text-to-speech"
SFX_PATH = "/sound-generation"
VOICES_PATH = "/voices"

# 音色列表分页上限（平台单页上限 100；面板只做“可选项”，不翻页拉全量）
VOICES_PAGE_SIZE = 100

DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_DESIGN_MODEL = "eleven_multilingual_ttv_v2"

# 音色设计的试听文本区间（平台硬限制，超出会 422）
PREVIEW_TEXT_MIN = 100
PREVIEW_TEXT_MAX = 1000


def _kind_for_status(status: int) -> str:
    return classify_status(status)[1]


def _http_error(status: int, body: str, *, context: str) -> AdapterError:
    snippet = (body or "").strip()[:300]
    return AdapterError(
        f"{context}返回 HTTP {status}: {snippet or '(空响应体)'}",
        retryable=status == 429 or status >= 500,
        http_status=status,
        kind=_kind_for_status(status),
    )


def _decode_b64(data: str) -> bytes:
    try:
        return base64.b64decode(str(data or ""))
    except (binascii.Error, ValueError):
        return b""


def output_format_for(audio_format: str, sample_rate: int = 0) -> str:
    """界面格式 → ElevenLabs ``output_format`` 值。

    平台没有 wav（只有 mp3/pcm/ulaw/alaw/opus），故非 mp3/pcm 一律按 mp3 请求；
    码率固定 128k（192k 需 Creator 档，免费档会 422）。
    """
    fmt = str(audio_format or "").strip().lower()
    if fmt == "pcm":
        rate = int(sample_rate or 24000)
        if rate not in (8000, 16000, 22050, 24000, 32000, 44100, 48000):
            rate = 24000
        return f"pcm_{rate}"
    return "mp3_44100_128"


def actual_format(audio_format: str) -> str:
    """实际产出格式（用于落盘扩展名）：只有 pcm 与 mp3。"""
    return "pcm" if str(audio_format or "").strip().lower() == "pcm" else "mp3"


class ElevenLabsAudioAdapter(BaseAudioAdapter):
    """ElevenLabs 原生音频适配器（一个供应商实例复用于三条通道）。"""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 300.0) -> None:
        root = str(base_url or "").strip().rstrip("/")
        if not root:
            raise AdapterError("音频供应商缺少 Base URL，请在 API 设置页补全")
        # 允许用户误填成 .../v1/models 之类，统一取到版本段为止
        marker = root.find("/v1")
        self._root = root[: marker + 3] if marker >= 0 else f"{root}/v1"
        self._api_key = str(api_key or "")
        self._timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"xi-api-key": self._api_key},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------- HTTP ----------

    async def _send(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        context: str,
    ) -> httpx.Response:
        client = self._get_client()
        url = f"{self._root}{path}"
        try:
            resp = await client.request(method, url, json=payload, params=params)
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
            logger.warning(f"[ElevenLabsAudio] {context} HTTP {resp.status_code}: {resp.text[:300]}")
            if resp.status_code == 401:
                raise AdapterError(
                    f"{context}失败：API Key 无效或缺少权限（{resp.text[:160]}）",
                    retryable=False, http_status=401, kind=KIND_AUTH,
                )
            if resp.status_code == 429:
                raise AdapterError(
                    f"{context}失败：额度或频率超限（{resp.text[:160]}）",
                    retryable=True, http_status=429, kind=KIND_QUOTA,
                )
            raise _http_error(resp.status_code, resp.text, context=context)
        return resp

    async def _post_json(
        self, path: str, payload: Dict[str, Any], *, context: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resp = await self._send("POST", path, payload=payload, params=params, context=context)
        try:
            data = resp.json()
        except ValueError as exc:
            raise AdapterError(
                f"{context}返回非 JSON 响应: {resp.text[:200]}",
                retryable=False, kind=KIND_UPSTREAM,
            ) from exc
        return data if isinstance(data, dict) else {}

    async def _post_bytes(
        self, path: str, payload: Dict[str, Any], *, context: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        resp = await self._send("POST", path, payload=payload, params=params, context=context)
        content = resp.content or b""
        if not content:
            raise AdapterError(f"{context}返回空音频（{resp.headers.get('content-type', '')}）",
                               retryable=False, kind=KIND_UPSTREAM)
        return content

    async def _get_json(
        self, path: str, *, context: str, params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resp = await self._send("GET", path, params=params, context=context)
        try:
            data = resp.json()
        except ValueError as exc:
            raise AdapterError(
                f"{context}返回非 JSON 响应: {resp.text[:200]}",
                retryable=False, kind=KIND_UPSTREAM,
            ) from exc
        return data if isinstance(data, dict) else {}

    # ---------- 音色列表 ----------

    async def list_voices(self, *, model: str = "") -> List[Dict[str, str]]:
        """账号音色清单（``GET /v1/voices``）：name + preview_url 供选择与试听。

        ``model`` 不参与筛选：ElevenLabs 音色是账号级资源，模型兼容性由合成时报错，
        这里不做本地猜测。平台不返回 preview_url 的条目照常返回，前端只禁用试听。
        """
        data = await self._get_json(
            VOICES_PATH, context="拉取音色列表", params={"page_size": VOICES_PAGE_SIZE})
        raw = data.get("voices") or []
        if not isinstance(raw, list):
            raise AdapterError("音色列表响应格式异常（voices 不是数组）",
                               retryable=False, kind=KIND_UPSTREAM)
        out: List[Dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            voice_id = str(item.get("voice_id") or "").strip()
            if not voice_id:
                continue
            out.append({
                "voice_id": voice_id,
                "name": str(item.get("name") or "").strip(),
                "preview_url": str(item.get("preview_url") or "").strip(),
                "category": str(item.get("category") or "").strip(),
            })
        return out

    # ---------- 音色设计 ----------

    async def design_voice(
        self, *, target_model: str, voice_prompt: str, preview_text: str,
        prefix: str = "", language: str = "zh",
        sample_rate: int = 24000, response_format: str = "wav",
        speaker_id: str = "", audio_data: str = "",
    ) -> AudioDesignResponse:
        if str(audio_data or "").strip():
            # 不猜测 voices/add 的 multipart 契约：未实测前明确拒绝，不静默降级
            raise AdapterError(
                "ElevenLabs 上传音频复刻音色暂未接入（当前只支持文字描述设计）",
                retryable=False, kind=KIND_PARAM)
        if not voice_prompt.strip():
            raise AdapterError("音色设计需要音色描述（提示词不能为空）",
                               retryable=False, kind=KIND_PARAM)
        body: Dict[str, Any] = {"voice_description": voice_prompt.strip()[:1000]}
        if target_model:
            body["model_id"] = target_model
        text = preview_text.strip()
        if PREVIEW_TEXT_MIN <= len(text) <= PREVIEW_TEXT_MAX:
            body["text"] = text
        else:
            # 平台要求 100-1000 字：短文本让平台按描述自拟，长文本截断
            body["auto_generate_text"] = True
            logger.info(
                f"[ElevenLabsAudio] 试听文本 {len(text)} 字不在 "
                f"{PREVIEW_TEXT_MIN}-{PREVIEW_TEXT_MAX}，改用平台自动生成试听文本")

        data = await self._post_json(DESIGN_PATH, body, context="音色设计")
        previews = data.get("previews") or []
        if not previews or not isinstance(previews[0], dict):
            raise AdapterError("音色设计未返回任何音色预览（请换一个描述重试）",
                               retryable=True, kind=KIND_UPSTREAM)
        first = previews[0]
        generated_id = str(first.get("generated_voice_id") or "")
        preview_audio = _decode_b64(str(first.get("audio_base_64") or ""))
        if not preview_audio:
            raise AdapterError("音色设计返回的预览音频为空", retryable=True, kind=KIND_UPSTREAM)

        voice_id = await self._create_voice(
            generated_id=generated_id, voice_prompt=voice_prompt, prefix=prefix)
        return AudioDesignResponse(
            voice_id=voice_id or generated_id,
            preview_audio=preview_audio,
            sample_rate=44100,
            response_format=actual_format(response_format),
            target_model=target_model or DEFAULT_DESIGN_MODEL,
            status="success" if voice_id else "preview_only",
            raw_response={"generated_voice_id": generated_id},
        )

    async def _create_voice(self, *, generated_id: str, voice_prompt: str, prefix: str) -> str:
        """用预览 id 创建永久音色；失败不阻断（预览音频已拿到，返回生成的 id）。"""
        if not generated_id:
            return ""
        name = f"{prefix or 'fd'}-{generated_id[:8]}"
        try:
            created = await self._post_json(
                CREATE_VOICE_PATH,
                {
                    "voice_name": name[:60],
                    "voice_description": voice_prompt.strip()[:500],
                    "generated_voice_id": generated_id,
                },
                context="保存音色",
            )
        except AdapterError as exc:
            logger.warning(f"[ElevenLabsAudio] 保存音色失败（保留预览 id）: {exc}")
            return ""
        return str(created.get("voice_id") or "")

    # ---------- 语音合成 ----------

    async def synthesize(
        self, *, model: str, text: str, voice_id: str,
        language: str = "Auto", audio_format: str = "wav",
        sample_rate: int = 24000, speed: Optional[float] = None,
        volume: Optional[float] = None, pitch: Optional[int] = None,
        emotion: str = "",
    ) -> AudioGenerationResponse:
        if not voice_id.strip():
            raise AdapterError(
                "语音合成需要 voice_id：请先做音色设计，或填 ElevenLabs 已有的音色 ID",
                retryable=False, kind=KIND_PARAM)
        audio = await self._post_bytes(
            f"{TTS_PATH}/{voice_id.strip()}",
            {
                "text": text,
                "model_id": model or DEFAULT_MODEL,
                # speed 在 voice_settings 里（1.0 = 原速；未给则不传保持音色默认）
                **({"voice_settings": {"speed": float(speed)}}
                   if speed is not None and abs(float(speed) - 1.0) > 1e-6 else {}),
            },
            params={"output_format": output_format_for(audio_format, sample_rate)},
            context="语音合成",
        )
        return AudioGenerationResponse(
            audio_bytes=audio,
            sample_rate=int(sample_rate or 44100),
            audio_format=actual_format(audio_format),
        )

    # ---------- 音乐（平台不支持） ----------

    async def generate_music(
        self, *, model: str, prompt: str, lyrics: str = "",
        instrumental: bool = True, gender: str = "",
        audio_format: str = "mp3", watermark: bool = False,
    ) -> AudioGenerationResponse:
        raise AdapterError(
            "ElevenLabs 不提供音乐生成接口（只有语音/音色设计/音效）；"
            "背景音乐请换用百炼 Fun-Music 或其它音乐模型",
            retryable=False, kind=KIND_PARAM)

    # ---------- 音效 ----------

    async def generate_sfx(
        self, *, model: str, text_prompt: str,
        references: Optional[List[str]] = None, audio_format: str = "wav",
        sample_rate: int = 48000, channels: int = 2, volume: int = 50,
        rate: float = 1.0, seed: int = 42, aigc_tag: bool = False,
    ) -> AudioGenerationResponse:
        if not text_prompt.strip():
            raise AdapterError("音效生成需要音效描述（提示词不能为空）",
                               retryable=False, kind=KIND_PARAM)
        audio = await self._post_bytes(
            SFX_PATH, {"text": text_prompt.strip()[:450]},
            params={"output_format": output_format_for(audio_format, sample_rate)},
            context="音效生成",
        )
        return AudioGenerationResponse(
            audio_bytes=audio,
            sample_rate=int(sample_rate or 44100),
            audio_format=actual_format(audio_format),
        )


__all__ = [
    "ElevenLabsAudioAdapter",
    "actual_format",
    "output_format_for",
]
