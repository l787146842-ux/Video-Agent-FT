"""
OpenAI 兼容协议 Adapter — 覆盖 ModelScope / Gemini 反代 / 任何 OpenAI 兼容端点。

同时提供 Chat 和 Image 两种能力：
- OpenAICompatChatAdapter: LLM 对话（支持流式 + function calling）
- OpenAICompatImageAdapter: 图片生成（/images/generations + /chat/completions fallback）
"""
import asyncio
import base64
import binascii
import json
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from loguru import logger

from .base_chat import (
    BaseChatAdapter,
    ChatResponse,
    StreamChunk,
    dispatch_chat_request,
    new_request_id,
)
from .base import BaseImageAdapter, ImageGenerationResponse
from .errors import (
    KIND_NETWORK,
    KIND_REFUSAL,
    KIND_TIMEOUT,
    KIND_UPSTREAM,
    build_exception_error,
    build_status_error,
    is_transient_error,
)
from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError
from src.video_agent.utils.paths import ASSETS_DIR
from src.video_agent.utils import gen_id
from src.video_agent.storage import get_storage

_DATA_URI_RE = re.compile(r"data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)")
_HTTP_IMAGE_RE = re.compile(r"https?://[^\s\)\"]+\.(?:png|jpg|jpeg|webp|gif)")


def extract_base64_image(text: str) -> str:
    """从 LLM 回复文本中提取 data URI 图片"""
    m = _DATA_URI_RE.search(text)
    return m.group(0) if m else ""


def persist_data_uri(data_uri: str) -> str:
    """把 base64 data URI 通过 Storage 接口落盘，返回相对 URL"""
    m = _DATA_URI_RE.match(data_uri)
    if not m:
        raise AdapterError("无法解析图片 data URI")
    ext = m.group(1).lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in ("png", "jpg", "webp", "gif"):
        ext = "png"
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as e:
        raise AdapterError(f"图片 base64 解码失败: {e}")

    name = f"{gen_id('gen', wide=True)}.{ext}"
    storage = get_storage()
    url = storage.save(raw, name, f"image/{ext}")
    return url


_MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}
_MIME_TO_SUFFIX = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def persist_remote_image(url: str, max_bytes: int = 20 * 1024 * 1024) -> str:
    """把供应商返回的远程图片立即落盘到本地存储，返回本地 URL。

    部分图片中转站返回的是有时效的临时托管链接（如 aitohumanize.com），
    几小时后即失效，导致后续视频生成把死链发给下游 API 报 400。
    生成成功时立刻下载内联，之后统一使用本地素材。
    下载失败时保留原 URL（浏览器可能仍可访问），仅记录告警。
    """
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return url
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200 or not resp.content:
            logger.warning(
                f"[ImageAdapter] 远程图片下载失败(HTTP {resp.status_code})，保留原 URL: {url}"
            )
            return url
        raw = resp.content
        if len(raw) > max_bytes:
            logger.warning(
                f"[ImageAdapter] 远程图片 {len(raw) // 1024}KB 超过 {max_bytes // 1024}KB，保留原 URL: {url}"
            )
            return url
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            ext = _MIME_TO_SUFFIX.get(ctype, ".png")
        if ext == ".jpeg":
            ext = ".jpg"
        storage = get_storage()
        name = f"{gen_id('gen', wide=True)}{ext}"
        saved = storage.save(raw, name, ctype or f"image/{ext.lstrip('.')}")
        logger.info(f"[ImageAdapter] 远程图片已落盘: {url} -> {saved} ({len(raw)} bytes)")
        return saved
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ImageAdapter] 远程图片落盘失败，保留原 URL: {url} ({e})")
        return url


async def ref_to_data_uri(url: str) -> str:
    """把参考素材 URL（本地 /assets、http(s)、data:）转为 base64 data URI。

    多模态模型（如 Gemini）无法访问本服务/画布的本地地址，因此将参考图
    内联为 data URI 随请求发送，保证模型能准确接收到 @ 引用的素材。
    失败返回空串（调用方跳过该参考图）。
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("data:"):
        return url
    try:
        if url.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                raw = resp.content
                ctype = resp.headers.get("content-type", "").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    ext = Path(urlparse(url).path).suffix.lower()
                    ctype = _MIME_BY_SUFFIX.get(ext, "image/png")
        else:
            # 本地素材：/workspace/assets/xxx 或 /assets/xxx（防目录穿越）
            path = urlparse(url).path if "://" in url else url
            fname = path.split("/assets/")[-1].strip("/") if "/assets/" in path else path.strip("/")
            full = (ASSETS_DIR / fname).resolve()
            full.relative_to(ASSETS_DIR.resolve())
            if not full.exists():
                return ""
            raw = full.read_bytes()
            ctype = _MIME_BY_SUFFIX.get(full.suffix.lower(), "image/png")
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{ctype};base64,{b64}"
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ImageAdapter] 参考图转 data URI 失败: {e}")
        return ""


# ---------- 中继错误信封识别（用户裁决：选什么用什么，联不通直接报错） ----------
# 中继层（9router 等）会把上游拒收（403/10605 slow 队列等）包进 HTTP 200 流
# 当「模型内容」下发（如 "[qoder error 403: {...}]"）；不识别会被当稿子，
# 垃圾递模型/绿勾/正文渲染裸 JSON。识别命中即抛错（retryable=False，不重试）。
_RELAY_ERROR_PREFIX_RE = re.compile(r"^\s*\[[\w-]+\s+error\s+(\d{3})\s*:", re.IGNORECASE)
_RELAY_QUEUE_CODE_RE = re.compile(r'"code"\s*:\s*"?(\d{3})"?')


def detect_relay_error_envelope(text: str) -> Optional[int]:
    """文本是中继层拒收通知单返回 http_status，否则 None。

    只看短文本（通知单至多几百字），合法长稿零误判：
    ①「[xxx error 403: …」前缀形态；②「{"code":"403",…10605/queueType…}」裸信封形态。
    """
    if not text or len(text) > 4000:
        return None
    m = _RELAY_ERROR_PREFIX_RE.match(text)
    if m:
        return int(m.group(1))
    stripped = text.lstrip()
    if stripped.startswith("{") and "10605" in text and "queueType" in text:
        m2 = _RELAY_QUEUE_CODE_RE.search(text)
        return int(m2.group(1)) if m2 else 403
    return None


class OpenAICompatChatAdapter(BaseChatAdapter):
    """OpenAI 兼容 Chat Adapter（支持流式 + function calling）

    连接池复用：实例持有长生命周期 httpx.AsyncClient，避免每次请求重建 TCP 连接。
    使用完毕后调用 await adapter.close 释放资源。
    """

    def __init__(self, base_url: str, api_key: str = "", model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client: Optional[httpx.AsyncClient] = None
        # 字段兼容探针记忆（同实例只探一次）：
        # 端点 400 拒收 reasoning_effort/response_format 后记入本集合，
        # 后续请求不再下发该字段（与 降级同惯例）。
        self._unsupported_fields: set = set()

    def _get_client(self, timeout: int = 120) -> httpx.AsyncClient:
        """Lazy 创建/复用 httpx 客户端（连接池复用）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(timeout, connect=10.0),
                headers=self._headers(),
            )
        return self._client

    async def close(self) -> None:
        """释放 HTTP 连接池资源"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @property
    def supports_function_calling(self) -> bool:
        return True

    def _apply_thinking_level(self, payload: Dict[str, Any], level: Optional[str] = None) -> None:
        """按配置透传 thinking/reasoning 档位。

        level 参数（本次调用档位）优先于全局配置：执行器机械调用注入
        low/medium/high 覆盖全局；None/空 = 沿用全局 llm_thinking_level；
        非法值不下发。缺省（空配置）不下发任何字段，保持端点默认行为；
        配置 low/medium/high 时按 OpenAI 兼容 reasoning_effort 透传，
        用于缩短推理模型的思考静默期。不支持的端点静默忽略或报 400（此时应置空配置）。
        """
        effective = level if level is not None else settings.llm_thinking_level
        level = str(effective or "").strip().lower()
        if level in ("low", "medium", "high"):
            payload["reasoning_effort"] = level

    def _apply_response_format(self, payload: Dict[str, Any],
                                response_format: Optional[Dict[str, Any]]) -> None:
        """：结构化输出（执行器 JSON 产出点下发 json_object）。
        探针已判定不支持的字段不再下发（兼容探针记忆）。"""
        if response_format and "response_format" not in self._unsupported_fields:
            payload["response_format"] = response_format

    def _strip_unsupported_on_400(self, payload: Dict[str, Any], body: str) -> bool:
        """兼容探针：400 拒收时按报文点名剥离可选字段（reasoning_effort/
        response_format），未点名则两者并剥；剥过即记忆（同实例不再试探）。
        返回是否剥离了任何字段（True 时调用方应重试一次）。"""
        fields = [k for k in ("response_format", "reasoning_effort") if k in payload]
        if not fields:
            return False
        named = [k for k in fields if k in body]
        to_strip = named or fields
        for k in to_strip:
            payload.pop(k, None)
            self._unsupported_fields.add(k)
        try:
            from src.video_agent.core.live_metrics import record_degradation
            for k in to_strip:
                record_degradation(f"adapter.{k}_unsupported")
        except Exception:
            pass
        logger.warning(f"[OpenAICompat] 端点 400 拒收可选字段 {to_strip}，剥离后重试一次")
        return True

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        thinking_level: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ChatResponse:
        if max_tokens is None:
            max_tokens = settings.llm_max_tokens
        if temperature is None:
            temperature = settings.llm_temperature
        if timeout is None:
            timeout = settings.llm_timeout
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 非流式必须显式声明：中介对缺省 stream 按流式路由，
            # 缺省会拿回 SSE 文本导致解析崩溃。
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        self._apply_thinking_level(payload, thinking_level)
        self._apply_response_format(payload, response_format)

        # 同轮请求标识（幂等语义，任务 #26）：一次 chat 调用生成一个 id，
        # 重试全程复用同一 payload + 同一标识（随 X-Request-Id 下发），
        # 供上游按标识去重，避免同轮请求被当多次新请求重复计费。
        request_id = new_request_id()
        _req_headers = {"X-Request-Id": request_id}
        try:
            client = self._get_client(timeout)
            # 分流入口（任务 #26）：transient（429/5xx/超时/连接错误）指数退避
            # 重试（上限/退避走 config）；permanent 4xx 立即上抛结构化错误
            resp = await dispatch_chat_request(
                lambda: client.post(
                    "/chat/completions", json=payload, headers=_req_headers,
                ),
                context="chat",
            )
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                # 200 但回非 JSON（被误当流式路由）按契约转 AdapterError，
                # 不让裸解析错误漏出 adapter 层。
                raise AdapterError(
                    f"LLM 返回非 JSON 响应（可能被误当流式）：{e}；响应头={resp.text[:120]!r}",
                    retryable=False,
                    kind=KIND_UPSTREAM,
                ) from e
        except AdapterError as e:
            # / 优雅降级：严格端点不认 reasoning_effort/
            # response_format 报 400 → 剥离字段重试一次（兼容探针；
            # permanent 400 中唯一允许的一次纠正式重提，非盲目重试）
            if getattr(e, "http_status", None) == 400 and self._strip_unsupported_on_400(
                    payload, str(e)):
                try:
                    resp = await client.post(
                        "/chat/completions", json=payload, headers=_req_headers,
                    )
                    if resp.status_code >= 400:
                        raise build_status_error(
                            resp.status_code, resp.text[:200], context="chat",
                        )
                    data = resp.json()
                except json.JSONDecodeError as e2:
                    raise AdapterError(
                        f"LLM 返回非 JSON 响应（可能被误当流式）：{e2}",
                        retryable=False,
                        kind=KIND_UPSTREAM,
                    ) from e2
                except httpx.HTTPError as e2:
                    raise build_exception_error(e2, context="chat") from e2
            else:
                raise
        except httpx.HTTPError as e:
            # 重试耗尽的超时/连接错误在此转译：分类器给出 kind/retryable
            raise build_exception_error(e, context="chat") from e

        choices = data.get("choices", [])
        if not choices:
            raise AdapterError("LLM 返回了空 choices")
        message = choices[0].get("message", {})
        content = message.get("content", "") or ""
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") != "image_url"
            )
        # 中继拒收通知单识别（200 包错误）——命中即抛错，不当稿子返回；
        # 归类为 permanent/refusal（模型拒答同源处置，任务 #26：不重试不 nudge）
        _env_status = detect_relay_error_envelope(content)
        if _env_status is not None:
            raise AdapterError(
                f"LLM 中继拒收通知单（HTTP {_env_status}）: {content[:200]}",
                retryable=False, http_status=_env_status, kind=KIND_REFUSAL,
            )
        tool_calls = message.get("tool_calls", []) or []
        # 透明度兑现：usage.total_tokens 入响应（轮次账单数据源，缺失保 0）
        _usage = data.get("usage") or {}
        _total_tokens = int(_usage.get("total_tokens") or 0) if isinstance(_usage, dict) else 0
        return ChatResponse(
            content=content,
            finish_reason=choices[0].get("finish_reason", "") or "",
            tool_calls=tool_calls,
            raw=data,
            token_usage=_total_tokens,
        )

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        thinking_level: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        if max_tokens is None:
            max_tokens = settings.llm_max_tokens
        if temperature is None:
            temperature = settings.llm_temperature
        if timeout is None:
            timeout = settings.llm_stream_timeout
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        self._apply_thinking_level(payload, thinking_level)
        self._apply_response_format(payload, response_format)

        # 首块产出前遇瞬时故障（上游 5xx 繁忙 / 连接失败）指数退避重试，
        # 与非流式路径的 with_retry 对齐；已开始产出内容则不重试（避免内容重复）。
        max_connect_retries = 2
        for attempt in range(max_connect_retries + 1):
            yielded = False
            try:
                async for chunk in self._stream_once(payload, timeout):
                    yielded = True
                    yield chunk
                return
            except AdapterError as e:
                # / 优雅降级：严格端点不认 reasoning_effort/
                # response_format 报 400 → 剥离字段重试（兼容探针；
                # AdapterError 报文携原始 body 前 200 字，可供点名判定）
                if (
                    not yielded
                    and (
                        getattr(e, "http_status", None) == 400
                        or str(e).startswith("LLM 返回 HTTP 400")
                    )
                    and self._strip_unsupported_on_400(payload, str(e))
                ):
                    continue
                # 结构化判定（-2）：优先用 retryable 标记，无标记旧异常回落
                # 分类器结构化判定（任务 #26，替代脆弱的文案匹配）
                flag = getattr(e, "retryable", None)
                if flag is None:
                    flag = is_transient_error(e)
                if not flag or yielded or attempt >= max_connect_retries:
                    raise
                delay = 1.0 * (2 ** attempt)
                logger.warning(
                    f"[OpenAICompat] 流式瞬时故障：{str(e)[:120]}，"
                    f"第 {attempt + 1}/{max_connect_retries} 次重试，等待 {delay:.0f}s"
                )
                try:
                    from src.video_agent.utils.stream_notify import notify_stream

                    await notify_stream(
                        f"模型连接瞬时故障，正在重试（第 {attempt + 1}/{max_connect_retries} 次）…"
                    )
                except Exception as _e:
                    logger.debug("[openai_compat] 忽略异常: {}", _e)
                await asyncio.sleep(delay)

    async def _stream_once(
        self,
        payload: Dict[str, Any],
        timeout: int,
    ) -> AsyncGenerator[StreamChunk, None]:
        """单次流式请求（连接 + 逐行解析 SSE），异常转译为 AdapterError。"""
        try:
            client = self._get_client(timeout)
            async with client.stream(
                "POST", "/chat/completions", json=payload
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:200]
                    # 分类器统一判定（任务 #26）：429/5xx = transient 才进重试循环
                    raise build_status_error(resp.status_code, body, context="chat-stream")

                ctype = resp.headers.get("content-type", "")
                if "text/event-stream" not in ctype:
                    # 供应商不支持流式，按普通 JSON 处理；
                    # 畸形体按契约转 AdapterError，不漏裸解析错误（与 chat 同契约）。
                    try:
                        data = json.loads((await resp.aread()).decode("utf-8", errors="replace"))
                    except json.JSONDecodeError as e:
                        raise AdapterError(
                            f"LLM 返回非 JSON 响应（可能被误当流式）：{e}",
                            retryable=False,
                        ) from e
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "") or ""
                        _env_status = detect_relay_error_envelope(content)
                        if _env_status is not None:
                            raise AdapterError(
                                f"LLM 中继拒收通知单（HTTP {_env_status}）: {content[:200]}",
                                retryable=False, http_status=_env_status,
                            )
                        if content:
                            yield StreamChunk(type="text_delta", text=content)
                        fr = choices[0].get("finish_reason", "") or "stop"
                        _ju = data.get("usage") or {}
                        yield StreamChunk(
                            type="done", finish_reason=fr,
                            usage_tokens=int(_ju.get("total_tokens") or 0) if isinstance(_ju, dict) else 0)
                    return

                last_finish = ""
                # 透明度兑现：机会性收集流内 usage（include_usage 端点在末段
                # 下发 choices 为空的 usage chunk；未下发则保 0，不强求不变更请求体）
                _stream_tokens = 0
                # 通知单头部累积器——中继把拒收缝进 200 流时，首段即识别抛错
                _env_head = ""
                _env_done = False
                # 流式 FC 累积器：OpenAI 协议中 tool_calls 的 arguments 是分片字符串，
                # 必须按 index 跨 chunk 拼接，流结束后统一解析（逐 chunk 解析必失败）
                tc_accumulator: Dict[int, Dict[str, str]] = {}
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices", [])
                    # usage chunk 可能 choices 为空：先取 usage 再判空
                    _u = data.get("usage")
                    if isinstance(_u, dict) and _u.get("total_tokens"):
                        _stream_tokens = int(_u.get("total_tokens") or 0)
                    if not choices:
                        continue
                    # 追踪 finish_reason（通常在最后一个 chunk 中携带）
                    fr = choices[0].get("finish_reason")
                    if fr:
                        last_finish = fr
                    delta = choices[0].get("delta", {}) or {}
                    # 推理模型（DeepSeek- / Gemini thinking 等）的 reasoning 增量：
                    # 各家字段名不同（reasoning_content / reasoning），有则透传，无则静默
                    reasoning_piece = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if reasoning_piece:
                        yield StreamChunk(type="reasoning_delta", text=reasoning_piece)
                    piece = delta.get("content") or ""
                    if piece:
                        if not _env_done:
                            _env_head += piece
                            _env_status = detect_relay_error_envelope(_env_head)
                            if _env_status is not None:
                                raise AdapterError(
                                    f"LLM 中继拒收通知单（HTTP {_env_status}）: {_env_head[:200]}",
                                    retryable=False, http_status=_env_status,
                                )
                            if len(_env_head) >= 512:
                                _env_done = True
                        yield StreamChunk(type="text_delta", text=piece)
                    # function calling 分片累积（index 标识第几个工具调用）
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            slot = tc_accumulator.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function", {}) or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                # 流结束：对完整 arguments 统一解析后逐条下发 tool_call chunk
                for idx in sorted(tc_accumulator):
                    slot = tc_accumulator[idx]
                    raw_args = slot["arguments"]
                    try:
                        args = json.loads(raw_args) if raw_args.strip() else {}
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(f"[OpenAICompat] tool_call arguments 解析失败: {raw_args[:100]}")
                        args = {}
                    yield StreamChunk(
                        type="tool_call",
                        tool_name=slot["name"],
                        tool_args=args if isinstance(args, dict) else {},
                    )
                # 流结束后 yield done chunk 携带 finish_reason（+ 机会性 usage）
                yield StreamChunk(type="done", finish_reason=last_finish or "stop",
                                  usage_tokens=_stream_tokens)
        except AdapterError:
            raise
        except httpx.TimeoutException:
            raise AdapterError(
                f"LLM 流式请求超时（{timeout}s）", retryable=True, kind=KIND_TIMEOUT,
            )
        except httpx.HTTPError as e:
            raise AdapterError(
                f"LLM 流式请求失败: {e}", retryable=True, kind=KIND_NETWORK,
            )


class OpenAICompatImageAdapter(BaseImageAdapter):
    """OpenAI 兼容 Image Adapter（/images/generations + /chat/completions fallback）

    连接池复用：同 ChatAdapter，实例持有长生命周期 httpx.AsyncClient。
    """

    def __init__(self, base_url: str, api_key: str = "", model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self, timeout: int = 120) -> httpx.AsyncClient:
        """Lazy 创建/复用 httpx 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(timeout, connect=10.0),
                headers=self._headers(),
            )
        return self._client

    async def close(self) -> None:
        """释放 HTTP 连接池资源"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def generate_image(
        self, prompt: str, reference_image: Optional[str] = None, **kwargs
    ) -> ImageGenerationResponse:
        """AI 图片生成：先尝试 /images/generations，失败后 fallback 到 /chat/completions

        带参考图时（reference_images / reference_image）直接走 /chat/completions 多模态路径，
        因为 /images/generations 无法接收参考图。
        """
        size = kwargs.get("size", "1024x1024")
        aspect_ratio = kwargs.get("aspect_ratio", "")
        # 参考图列表（兼容单个 reference_image）
        reference_images: List[str] = list(kwargs.get("reference_images") or [])
        if reference_image and reference_image not in reference_images:
            reference_images.insert(0, reference_image)
        errors: List[str] = []

        # 带参考图：直接走多模态 chat 路径，保证模型接收到参考素材
        if reference_images:
            result = await self._try_chat_fallback(prompt, aspect_ratio, errors, reference_images)
            if result:
                return result
            raise AdapterError("参考图生成失败（模型可能不支持多模态生图）。" + "；".join(errors))

        # 方式 1: /images/generations
        result = await self._try_images_endpoint(prompt, size, errors)
        if result:
            return result

        # 方式 2: /chat/completions（Gemini 原生图片生成）
        result = await self._try_chat_fallback(prompt, aspect_ratio, errors)
        if result:
            return result

        raise AdapterError("图片生成失败（模型可能不支持生图，请换用图片模型）。" + "；".join(errors))

    async def _try_images_endpoint(self, prompt: str, size: str, errors: List[str]) -> Optional[ImageGenerationResponse]:
        """尝试 /images/generations 端点"""
        try:
            payload = {"model": self.model, "prompt": prompt, "n": 1, "size": size or "1024x1024"}
            client = self._get_client(settings.image_gen_timeout)
            resp = await client.post("/images/generations", json=payload)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    errors.append("/images/generations 返回非 JSON 响应（可能被误当流式）")
                    return None
                images_data = data.get("data", [])
                if images_data:
                    url = images_data[0].get("url", "")
                    if not url and images_data[0].get("b64_json"):
                        url = persist_data_uri(f"data:image/png;base64,{images_data[0]['b64_json']}")
                    elif url.lower().startswith(("http://", "https://")):
                        # 临时托管链立即落盘，避免过期后成为下游死链
                        url = await persist_remote_image(url)
                    if url:
                        return ImageGenerationResponse(
                            task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                        )
                errors.append("/images/generations 返回 200 但无图片数据")
            else:
                errors.append(f"/images/generations HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            raise AdapterError(
                "图片生成失败：API 服务未启动（连接被拒绝）。请检查服务是否运行，或切换到其他可用的图片 API。"
            ) from e
        except httpx.HTTPError as e:
            errors.append(f"/images/generations 请求失败: {e}")
        return None

    async def _try_chat_fallback(
        self, prompt: str, aspect_ratio: str, errors: List[str],
        reference_images: Optional[List[str]] = None,
    ) -> Optional[ImageGenerationResponse]:
        """Fallback: 通过 /chat/completions 生成图片（Gemini 原生图片生成，支持参考图）"""
        aspect_hint = f" Aspect ratio: {aspect_ratio}." if aspect_ratio and aspect_ratio != "1:1" else ""
        ref_hint = " The attached image(s) are provided as visual references; keep the result consistent with them." if reference_images else ""
        image_prompt = f"Generate an image: {prompt}.{aspect_hint}{ref_hint}"

        # 有参考图时构建多模态 content（文本 + 图片 data URI）
        content: Any = image_prompt
        if reference_images:
            parts: List[Dict[str, Any]] = [{"type": "text", "text": image_prompt}]
            for ref in reference_images:
                du = await ref_to_data_uri(ref)
                if du:
                    parts.append({"type": "image_url", "image_url": {"url": du}})
            if len(parts) > 1:
                content = parts

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": settings.llm_max_tokens,
        }
        try:
            client = self._get_client(settings.image_gen_timeout)
            resp = await client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            try:
                data = resp.json()
            except json.JSONDecodeError:
                errors.append("/chat/completions 生图回退返回非 JSON 响应（可能被误当流式）")
                return None

            choices = data.get("choices", [])
            content = choices[0].get("message", {}).get("content", "") if choices else ""
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:image/"):
                            url = persist_data_uri(url)
                        elif url.lower().startswith(("http://", "https://")):
                            url = await persist_remote_image(url)
                        if url:
                            return ImageGenerationResponse(
                                task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                            )
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))

            img_data = extract_base64_image(content)
            if img_data:
                url = persist_data_uri(img_data)
                return ImageGenerationResponse(
                    task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                )

            url_match = _HTTP_IMAGE_RE.search(content)
            if url_match:
                url = await persist_remote_image(url_match.group(0))
                return ImageGenerationResponse(
                    task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                )

            errors.append("供应商没有返回任何图片")
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            raise AdapterError(
                "图片生成失败：API 服务未启动（连接被拒绝）。请检查服务是否运行，或切换到其他可用的图片 API。"
            ) from e
        except httpx.TimeoutException:
            raise AdapterError(f"生图请求超时（{settings.image_gen_timeout}s）。" + "；".join(errors))
        except httpx.HTTPStatusError as e:
            raise AdapterError(
                f"生图失败：HTTP {e.response.status_code}: {e.response.text[:200]}。" + "；".join(errors)
            )
        except httpx.HTTPError as e:
            errors.append(f"/chat/completions 请求失败: {e}")
        return None

    async def fetch_result(self, task_id: str) -> ImageGenerationResponse:
        """OpenAI 兼容接口是同步返回，不需要轮询"""
        return ImageGenerationResponse(task_id=task_id, status="completed", image_urls=[])
