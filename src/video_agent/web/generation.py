"""
真实供应商调用管线（图片生成 + Chat Completions）。

供 routes/generate.py、routes/agent.py、routes/workflow.py 共用，
之前散落在各路由里的 HTTP 调用逻辑收敛到这里。

原则：失败就抛 GenerationError（带用户可读的中文信息），
由调用方决定如何呈现——绝不静默降级成 mock 假成功。
"""
import base64
import binascii
import re
import time
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from loguru import logger

from src.video_agent.web.provider_config import (
    CLI_PROTOCOLS,
    get_api_key,
    get_provider_config,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ASSETS_DIR = PROJECT_ROOT / "workspace" / "assets"


class GenerationError(Exception):
    """供应商调用失败——message 面向用户，可直接展示"""


# ---------- 端点解析 ----------

def resolve_openai_endpoint(provider_id: str, model: str) -> Tuple[str, str, str]:
    """
    解析 (base_url, api_key, effective_model)。
    CLI 协议（gemini-cli / codex / jimeng）没有 base_url，
    自动路由到 custom-api 反代（底层同为 Gemini 模型）。
    解析不出可用端点时抛 GenerationError。
    """
    cfg = get_provider_config(provider_id)
    if not cfg:
        raise GenerationError(f"供应商 '{provider_id}' 未配置，请先在 API 设置页添加")

    base_url = (cfg.get("base_url") or "").strip().rstrip("/")
    api_key = get_api_key(provider_id)
    effective_model = model

    if not base_url and cfg.get("protocol") in CLI_PROTOCOLS:
        fallback = get_provider_config("custom-api")
        if fallback and fallback.get("base_url"):
            base_url = fallback["base_url"].rstrip("/")
            api_key = get_api_key("custom-api")
            if effective_model in ("auto", ""):
                effective_model = "gemini-3.1-flash-image"
            logger.info(f"[Generation] CLI 协议 '{provider_id}' 路由到反代, model={effective_model}")

    if not base_url:
        raise GenerationError(
            f"供应商 '{provider_id}' 缺少 Base URL（CLI 协议需要先配置 custom-api 反代）"
        )
    return base_url, api_key, effective_model


# ---------- Chat Completions ----------

async def call_chat_completion(
    provider_id: str,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: int = 8192,
    temperature: float = 0.7,
    timeout: int = 120,
) -> Tuple[str, str]:
    """
    OpenAI 兼容 chat 调用。返回 (content, finish_reason)。
    失败抛 GenerationError。
    """
    base_url, api_key, effective_model = resolve_openai_endpoint(provider_id, model)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": effective_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    logger.info(f"[Generation] chat: provider={provider_id}, model={effective_model}")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise GenerationError(f"LLM 请求超时（{timeout}s），请检查网络或供应商状态")
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:200]
        raise GenerationError(f"LLM 返回 HTTP {e.response.status_code}: {detail}")
    except httpx.HTTPError as e:
        raise GenerationError(f"LLM 请求失败: {e}")

    choices = data.get("choices", [])
    if not choices:
        raise GenerationError("LLM 返回了空 choices")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        content = " ".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") != "image_url"
        )
    if not content:
        raise GenerationError("LLM 返回了空内容")
    finish_reason = choices[0].get("finish_reason", "") or ""
    return content, finish_reason


# ---------- 图片生成 ----------

_DATA_URI_RE = re.compile(r"data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)")
_HTTP_IMAGE_RE = re.compile(r"https?://[^\s\)\"]+\.(?:png|jpg|jpeg|webp|gif)")


def extract_base64_image(text: str) -> str:
    """从 LLM 回复文本中提取 data URI 图片（Gemini 生图模型返回 markdown 格式）"""
    m = _DATA_URI_RE.search(text)
    return m.group(0) if m else ""


def persist_data_uri(data_uri: str) -> str:
    """
    把 base64 data URI 落盘到 workspace/assets/，返回可访问的相对 URL。
    避免几 MB 的 base64 被塞进 state.json。
    解码失败时抛 GenerationError。
    """
    m = _DATA_URI_RE.match(data_uri)
    if not m:
        raise GenerationError("无法解析图片 data URI")
    ext = m.group(1).lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in ("png", "jpg", "webp", "gif"):
        ext = "png"
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as e:
        raise GenerationError(f"图片 base64 解码失败: {e}")

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"gen-{int(time.time())}-{random.randint(1000, 9999)}.{ext}"
    (ASSETS_DIR / name).write_bytes(raw)
    logger.info(f"[Generation] base64 图片已落盘: {name} ({len(raw)} bytes)")
    return f"/workspace/assets/{name}"


async def generate_image_via_provider(
    provider_id: str,
    model: str,
    prompt: str,
    *,
    size: str = "1024x1024",
    aspect_ratio: str = "",
) -> str:
    """
    统一图片生成：
    1. 先尝试 /images/generations（OpenAI 标准）
    2. 回退 /chat/completions（Gemini 原生图片模型）
    返回图片 URL（data URI 会先落盘为文件 URL）。失败抛 GenerationError。
    """
    base_url, api_key, effective_model = resolve_openai_endpoint(provider_id, model)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    errors: List[str] = []

    # --- 方式 1：/images/generations ---
    try:
        payload = {"model": effective_model, "prompt": prompt, "n": 1, "size": size or "1024x1024"}
        logger.info(f"[Generation] /images/generations: model={effective_model}")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{base_url}/images/generations", json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                images_data = data.get("data", [])
                if images_data:
                    url = images_data[0].get("url", "")
                    if not url and images_data[0].get("b64_json"):
                        return persist_data_uri(
                            f"data:image/png;base64,{images_data[0]['b64_json']}"
                        )
                    if url:
                        return url
                errors.append("/images/generations 返回 200 但无图片数据")
            else:
                errors.append(f"/images/generations HTTP {resp.status_code}")
    except httpx.HTTPError as e:
        errors.append(f"/images/generations 请求失败: {e}")

    # --- 方式 2：/chat/completions（Gemini 原生图片生成） ---
    aspect_hint = f" Aspect ratio: {aspect_ratio}." if aspect_ratio and aspect_ratio != "1:1" else ""
    image_prompt = f"Generate an image: {prompt}.{aspect_hint}"
    payload = {
        "model": effective_model,
        "messages": [{"role": "user", "content": image_prompt}],
        "max_tokens": 8192,
    }
    logger.info(f"[Generation] /chat/completions 生图: model={effective_model}")
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise GenerationError("生图请求超时（180s）。" + "；".join(errors))
    except httpx.HTTPStatusError as e:
        raise GenerationError(
            f"生图失败：HTTP {e.response.status_code}: {e.response.text[:200]}。" + "；".join(errors)
        )
    except httpx.HTTPError as e:
        raise GenerationError(f"生图请求失败: {e}。" + "；".join(errors))

    choices = data.get("choices", [])
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if url.startswith("data:image/"):
                    return persist_data_uri(url)
                if url:
                    return url
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))

    img_data = extract_base64_image(content)
    if img_data:
        return persist_data_uri(img_data)

    url_match = _HTTP_IMAGE_RE.search(content)
    if url_match:
        return url_match.group(0)

    raise GenerationError(
        "供应商没有返回任何图片（模型可能不支持生图，请换用图片模型）。" + "；".join(errors)
    )
