"""
OpenAI 兼容协议 Adapter — 覆盖 ModelScope / Gemini 反代 / 任何 OpenAI 兼容端点。

同时提供 Chat 和 Image 两种能力：
- OpenAICompatChatAdapter: LLM 对话（支持流式 + function calling）
- OpenAICompatImageAdapter: 图片生成（/images/generations + /chat/completions fallback）
"""
import base64
import binascii
import json
import re
import time
import random
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx
from loguru import logger

from .base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from .base import BaseImageAdapter, ImageGenerationResponse
from src.video_agent.exceptions import AdapterError
from src.video_agent.utils.paths import ASSETS_DIR

_DATA_URI_RE = re.compile(r"data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)")
_HTTP_IMAGE_RE = re.compile(r"https?://[^\s\)\"]+\.(?:png|jpg|jpeg|webp|gif)")


def extract_base64_image(text: str) -> str:
    """从 LLM 回复文本中提取 data URI 图片"""
    m = _DATA_URI_RE.search(text)
    return m.group(0) if m else ""


def persist_data_uri(data_uri: str) -> str:
    """把 base64 data URI 落盘到 workspace/assets/，返回相对 URL"""
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

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"gen-{int(time.time())}-{random.randint(1000, 9999)}.{ext}"
    (ASSETS_DIR / name).write_bytes(raw)
    logger.info(f"[Adapter] base64 图片已落盘: {name} ({len(raw)} bytes)")
    return f"/workspace/assets/{name}"


class OpenAICompatChatAdapter(BaseChatAdapter):
    """OpenAI 兼容 Chat Adapter（支持流式 + function calling）"""

    def __init__(self, base_url: str, api_key: str = "", model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout: int = 120,
    ) -> ChatResponse:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            raise AdapterError(f"LLM 请求超时（{timeout}s），请检查网络或供应商状态")
        except httpx.HTTPStatusError as e:
            raise AdapterError(f"LLM 返回 HTTP {e.response.status_code}: {e.response.text[:200]}")
        except httpx.HTTPError as e:
            raise AdapterError(f"LLM 请求失败: {e}")

        choices = data.get("choices", [])
        if not choices:
            raise AdapterError("LLM 返回了空 choices")
        message = choices[0].get("message", {})
        content = message.get("content", "") or ""
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") != "image_url"
            )
        tool_calls = message.get("tool_calls", []) or []
        return ChatResponse(
            content=content,
            finish_reason=choices[0].get("finish_reason", "") or "",
            tool_calls=tool_calls,
            raw=data,
        )

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout: int = 180,
    ) -> AsyncGenerator[StreamChunk, None]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                ) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", errors="replace")[:200]
                        raise AdapterError(f"LLM 返回 HTTP {resp.status_code}: {body}")

                    ctype = resp.headers.get("content-type", "")
                    if "text/event-stream" not in ctype:
                        # 供应商不支持流式，按普通 JSON 处理
                        data = json.loads((await resp.aread()).decode("utf-8", errors="replace"))
                        choices = data.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "") or ""
                            if content:
                                yield StreamChunk(type="text_delta", text=content)
                        return

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
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}) or {}
                        piece = delta.get("content") or ""
                        if piece:
                            yield StreamChunk(type="text_delta", text=piece)
                        # function calling 增量（简化处理：完整 tool_calls 通常在最后一个 chunk）
                        if delta.get("tool_calls"):
                            for tc in delta["tool_calls"]:
                                raw_args = tc.get("function", {}).get("arguments", {})
                                # OpenAI 协议中 arguments 是 JSON 字符串，需解析为 dict
                                if isinstance(raw_args, str):
                                    try:
                                        raw_args = json.loads(raw_args) if raw_args.strip() else {}
                                    except (json.JSONDecodeError, ValueError):
                                        raw_args = {}
                                yield StreamChunk(
                                    type="tool_call",
                                    tool_name=tc.get("function", {}).get("name", ""),
                                    tool_args=raw_args if isinstance(raw_args, dict) else {},
                                )
        except AdapterError:
            raise
        except httpx.TimeoutException:
            raise AdapterError(f"LLM 流式请求超时（{timeout}s）")
        except httpx.HTTPError as e:
            raise AdapterError(f"LLM 流式请求失败: {e}")


class OpenAICompatImageAdapter(BaseImageAdapter):
    """OpenAI 兼容 Image Adapter（/images/generations + /chat/completions fallback）"""

    def __init__(self, base_url: str, api_key: str = "", model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def generate_image(
        self, prompt: str, reference_image: Optional[str] = None, **kwargs
    ) -> ImageGenerationResponse:
        size = kwargs.get("size", "1024x1024")
        aspect_ratio = kwargs.get("aspect_ratio", "")
        errors: List[str] = []
        connection_failed = False

        # 方式 1: /images/generations
        try:
            payload = {"model": self.model, "prompt": prompt, "n": 1, "size": size or "1024x1024"}
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/images/generations", json=payload, headers=self._headers()
                )
                if resp.status_code == 200:
                    data = resp.json()
                    images_data = data.get("data", [])
                    if images_data:
                        url = images_data[0].get("url", "")
                        if not url and images_data[0].get("b64_json"):
                            url = persist_data_uri(f"data:image/png;base64,{images_data[0]['b64_json']}")
                        if url:
                            return ImageGenerationResponse(
                                task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                            )
                    errors.append("/images/generations 返回 200 但无图片数据")
                else:
                    errors.append(f"/images/generations HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            connection_failed = True
            errors.append(f"/images/generations 连接失败: {e}")
        except httpx.HTTPError as e:
            errors.append(f"/images/generations 请求失败: {e}")

        # 方式 2: /chat/completions（Gemini 原生图片生成）
        if not connection_failed:
            aspect_hint = f" Aspect ratio: {aspect_ratio}." if aspect_ratio and aspect_ratio != "1:1" else ""
            image_prompt = f"Generate an image: {prompt}.{aspect_hint}"
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": image_prompt}],
                "max_tokens": 8192,
            }
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                    )
                    resp.raise_for_status()
                    data = resp.json()

                choices = data.get("choices", [])
                content = choices[0].get("message", {}).get("content", "") if choices else ""
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            if url.startswith("data:image/"):
                                url = persist_data_uri(url)
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
                    return ImageGenerationResponse(
                        task_id=f"img-{int(time.time())}", status="completed", image_urls=[url_match.group(0)]
                    )

                errors.append("供应商没有返回任何图片")
            except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
                connection_failed = True
                errors.append(f"/chat/completions 连接失败: {e}")
            except httpx.TimeoutException:
                raise AdapterError("生图请求超时（180s）。" + "；".join(errors))
            except httpx.HTTPStatusError as e:
                raise AdapterError(
                    f"生图失败：HTTP {e.response.status_code}: {e.response.text[:200]}。" + "；".join(errors)
                )
            except httpx.HTTPError as e:
                errors.append(f"/chat/completions 请求失败: {e}")

        if connection_failed:
            raise AdapterError(
                "图片生成失败：API 服务未启动（连接被拒绝）。请检查服务是否运行，或切换到其他可用的图片 API。"
            )
        raise AdapterError("图片生成失败（模型可能不支持生图，请换用图片模型）。" + "；".join(errors))

    async def fetch_result(self, task_id: str) -> ImageGenerationResponse:
        """OpenAI 兼容接口是同步返回，不需要轮询"""
        return ImageGenerationResponse(task_id=task_id, status="completed", image_urls=[])
