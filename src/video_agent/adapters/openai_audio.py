"""OpenAI 兼容音频适配器（POST {base}/audio/speech）。

覆盖硅基流动 / OpenAI / Groq / 本地 OpenAI 兼容音频服务等：
- ``synthesize``：输入文本 + voice → 二进制音频（直接落盘）；
- 其余通道（音色设计/音乐/音效）不属于该协议，明确拒绝（不猜接口）。

voice 约定：部分平台（硅基流动）把音色编码为 ``model:voice``（如
``FunAudioLLM/CosyVoice2-0.5B:alex``），由供应商标记
``audio_voice_join_model=true`` 时自动拼接；已含 ``:`` 的 voice 原样透传。
"""
import re
from typing import Any, Dict, Optional

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
)
from src.video_agent.adapters.errors import classify_status
from src.video_agent.exceptions import AdapterError

_VERSION_SUFFIX_RE = re.compile(r"/(?:api/)?v\d+$", re.IGNORECASE)


def openai_audio_root(base_url: str) -> str:
    """base_url → OpenAI 音频根（保证带版本段，如 /v1）。"""
    root = str(base_url or "").strip().rstrip("/")
    if not root:
        return ""
    if not _VERSION_SUFFIX_RE.search(root):
        root += "/v1"
    return root


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


class OpenAIAudioAdapter(BaseAudioAdapter):
    """OpenAI 兼容 ``/audio/speech`` 适配器（仅语音合成通道）。"""

    def __init__(
        self, base_url: str, api_key: str, *, timeout: float = 300.0,
        voice_join_model: bool = False,
    ) -> None:
        self._root = openai_audio_root(base_url)
        if not self._root:
            raise AdapterError("音频供应商缺少 Base URL，请在 API 设置页补全")
        self._api_key = str(api_key or "")
        self._timeout = float(timeout)
        self._voice_join_model = bool(voice_join_model)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _speak(self, payload: Dict[str, Any]) -> AudioGenerationResponse:
        client = self._get_client()
        try:
            resp = await client.post(f"{self._root}/audio/speech", json=payload)
        except httpx.TimeoutException as exc:
            raise AdapterError(
                f"语音合成超时（{self._timeout:g}s），请稍后重试",
                retryable=True, kind=KIND_TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(
                f"语音合成请求失败（{type(exc).__name__}）: {str(exc)[:200]}",
                retryable=True, kind=KIND_NETWORK,
            ) from exc
        ctype = str(resp.headers.get("content-type") or "")
        if resp.status_code >= 400 or "json" in ctype:
            snippet = resp.text[:300]
            if resp.status_code >= 400:
                logger.warning(f"[OpenAIAudio] HTTP {resp.status_code}: {snippet}")
                raise AdapterError(
                    f"语音合成返回 HTTP {resp.status_code}: {snippet or '(空响应体)'}",
                    retryable=resp.status_code == 429 or resp.status_code >= 500,
                    http_status=resp.status_code,
                    kind=_kind_for_status(resp.status_code),
                )
            # HTTP 200 但返回 JSON = 错误信封（不同平台字段不同）
            raise AdapterError(
                f"语音合成失败: {snippet or '(空响应体)'}",
                retryable=False, kind=KIND_PARAM,
            )
        if not resp.content:
            raise AdapterError("语音合成返回空音频", retryable=False, kind=KIND_UPSTREAM)
        fmt = str(payload.get("response_format") or "mp3")
        return AudioGenerationResponse(
            audio_bytes=resp.content, audio_format=fmt,
            sample_rate=int(payload.get("sample_rate") or 0),
        )

    async def synthesize(
        self, *, model: str, text: str, voice_id: str,
        language: str = "Auto", audio_format: str = "wav",
        sample_rate: int = 24000, speed: Optional[float] = None,
        volume: Optional[float] = None, pitch: Optional[int] = None,
        emotion: str = "",
    ) -> AudioGenerationResponse:
        voice = str(voice_id or "").strip()
        if not voice:
            raise AdapterError(
                "该供应商需要填写音色（如 FunAudioLLM/CosyVoice2-0.5B:alex）",
                retryable=False, kind=KIND_PARAM,
            )
        if self._voice_join_model and ":" not in voice:
            voice = f"{model}:{voice}"
        payload: Dict[str, Any] = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": audio_format or "mp3",
        }
        if sample_rate:
            payload["sample_rate"] = int(sample_rate)
        if speed is not None:
            payload["speed"] = float(speed)
        return await self._speak(payload)

    @staticmethod
    def _unsupported(channel: str) -> None:
        raise AdapterError(
            f"该供应商（OpenAI 兼容 /audio/speech）不支持{channel}，请换音频通道或供应商",
            retryable=False, kind=KIND_PARAM,
        )

    async def design_voice(self, **kwargs) -> AudioDesignResponse:
        self._unsupported("音色设计")

    async def generate_music(self, **kwargs) -> AudioGenerationResponse:
        self._unsupported("背景音乐")

    async def generate_sfx(self, **kwargs) -> AudioGenerationResponse:
        self._unsupported("音效")
