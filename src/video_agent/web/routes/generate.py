"""
/api/generate — 生成任务端点
图片/视频生成走内核 AdapterFactory → 适配器层。
任务完成后自动回写 StudioStateService（更新 draft 的 imgUrl/videoUrl）。
"""
import json
import os
import time
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from loguru import logger

from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.web.providers import resolve_adapter_name
from src.video_agent.web.state_service import StudioStateService

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

# 任务存储：task_id → {status, adapter_type, adapter_name, draft_id, draft_type, ...}
_tasks: Dict[str, Dict[str, Any]] = {}


def _get_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    """从 data/api_providers.json 读取供应商配置"""
    providers_file = PROJECT_ROOT / "data" / "api_providers.json"
    if not providers_file.exists():
        return None
    try:
        providers = json.loads(providers_file.read_text(encoding="utf-8"))
        for p in providers:
            if p.get("id") == provider_id:
                return p
    except Exception:
        pass
    return None


def _get_api_key(provider_id: str) -> str:
    """从 API/.env 或环境变量读取 API Key"""
    env_mapping = {
        "modelscope": "MODELSCOPE_API_KEY",
        "volcengine": "ARK_API_KEY",
        "gemini-cli": "GEMINI_API_KEY",
    }
    env_name = env_mapping.get(provider_id, f"API_PROVIDER_{provider_id.upper().replace('-', '_')}_KEY")
    val = os.getenv(env_name, "")
    if val:
        return val
    env_file = PROJECT_ROOT / "API" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{env_name}="):
                return line.split("=", 1)[1].strip()
    return ""


import re as _re


def _extract_base64_image(text: str) -> str:
    """从 LLM 回复文本中提取 base64 图片（Gemini 生图模型返回 markdown 格式）"""
    # 匹配 ![image](data:image/xxx;base64,...) 或直接的 data:image/xxx;base64,...
    patterns = [
        r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+',
    ]
    for pat in patterns:
        m = _re.search(pat, text)
        if m:
            return m.group(0)
    return ""


async def _call_image_api(base_url: str, api_key: str, body: "ImageGenRequest") -> str:
    """
    统一图片生成调用：
    1. 先尝试 /images/generations（OpenAI 标准）
    2. 如果失败（502/404/503），回退到 /chat/completions（Gemini 原生图片模型）
    返回图片 URL 或 base64 data URI，失败返回空字符串。
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    size = body.size or "1024x1024"

    # --- 方式 1：/images/generations ---
    try:
        payload = {"model": body.model, "prompt": body.prompt, "n": 1, "size": size}
        logger.info(f"[Generate] 尝试 /images/generations: model={body.model}")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{base_url}/images/generations", json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                images_data = data.get("data", [])
                if images_data:
                    url = images_data[0].get("url", "")
                    if not url and images_data[0].get("b64_json"):
                        url = f"data:image/png;base64,{images_data[0]['b64_json']}"
                    if url:
                        return url
        logger.info("[Generate] /images/generations 未返回有效数据，尝试 chat 生图")
    except Exception as e:
        logger.info(f"[Generate] /images/generations 失败({e})，尝试 chat 生图")

    # --- 方式 2：/chat/completions（Gemini 原生图片生成） ---
    # 构建包含尺寸提示的 prompt
    aspect_hint = ""
    if body.aspect_ratio and body.aspect_ratio != "1:1":
        aspect_hint = f" Aspect ratio: {body.aspect_ratio}."
    image_prompt = f"Generate an image: {body.prompt}.{aspect_hint}"

    payload = {
        "model": body.model,
        "messages": [{"role": "user", "content": image_prompt}],
        "max_tokens": 8192,
    }
    logger.info(f"[Generate] 尝试 /chat/completions 生图: model={body.model}")
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        return ""

    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        # 多模态响应：查找 image_url 类型的 part
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                return part.get("image_url", {}).get("url", "")
        # 拼接文本部分再提取
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))

    # 从文本中提取 base64 图片
    img_data = _extract_base64_image(content)
    if img_data:
        return img_data

    # 如果回复中包含 URL
    url_match = _re.search(r'https?://[^\s\)\"]+\.(?:png|jpg|jpeg|webp|gif)', content)
    if url_match:
        return url_match.group(0)

    return ""


class ImageGenRequest(BaseModel):
    prompt: str
    provider_id: str = ""
    model: str = ""
    size: str = "1280x720"
    aspect_ratio: str = "16:9"
    reference_images: List[Dict[str, str]] = []
    # 可选：关联到哪个 draft（完成后自动回写）
    draft_id: str = ""
    draft_type: str = "keyElement"


class VideoGenRequest(BaseModel):
    prompt: str
    provider_id: str = ""
    model: str = ""
    duration: int = 5
    resolution: str = "1080p"
    aspect_ratio: str = "16:9"
    images: List[Dict[str, str]] = []
    enhance_prompt: bool = False
    multimodal: bool = False
    # 可选：关联到哪个 draft
    draft_id: str = ""
    draft_type: str = "shot"


@router.post("/generate/image")
@router.post("/canvas-image-tasks")
async def generate_image(body: ImageGenRequest):
    """
    提交图片生成任务。
    支持两种模式：
    1. OpenAI 兼容 /images/generations（标准模式）
    2. Chat Completions 生图（Gemini 原生图片模型，如 gemini-3.1-flash-image）
    失败则回退 mock。
    """
    task_id = f"img-{int(time.time())}-{random.randint(100,999)}"

    # 尝试真实 API 调用
    if body.provider_id and body.provider_id != "mock" and body.model and not body.model.startswith("mock"):
        provider_cfg = _get_provider_config(body.provider_id)
        base_url = ""
        api_key = ""
        effective_model = body.model

        if provider_cfg:
            base_url = (provider_cfg.get("base_url") or "").strip().rstrip("/")
            api_key = _get_api_key(body.provider_id)

            # CLI 协议（如 gemini-cli / Antigravity CLI）无 base_url，
            # 自动路由到 Gemini反代（custom-api）走 HTTP，底层是同一套 Gemini 模型
            if not base_url and provider_cfg.get("protocol") in ("gemini-cli", "codex", "jimeng"):
                fallback_cfg = _get_provider_config("custom-api")
                if fallback_cfg and fallback_cfg.get("base_url"):
                    base_url = fallback_cfg["base_url"].rstrip("/")
                    api_key = _get_api_key("custom-api")
                    # "auto" 模型映射到实际可用的生图模型
                    if effective_model in ("auto", ""):
                        effective_model = "gemini-3.1-flash-image"
                    logger.info(f"[Generate] CLI 协议 '{body.provider_id}' 路由到 Gemini反代, model={effective_model}")

        if base_url:
            # 用有效模型覆盖 body.model 供 _call_image_api 使用
            body_copy = body.model_copy(update={"model": effective_model})
            try:
                image_url = await _call_image_api(base_url, api_key, body_copy)
                if image_url:
                    _tasks[task_id] = {
                        "status": "succeeded",
                        "result": {"images": [image_url]},
                        "draft_id": body.draft_id,
                        "draft_type": body.draft_type,
                        "prompt": body.prompt,
                        "model": effective_model,
                    }
                    _writeback_if_complete(task_id)
                    logger.info(f"[Generate] 图片生成成功: {image_url[:80]}...")
                    return {"task_id": task_id}
                else:
                    logger.warning("[Generate] API 返回空图片数据，回退 mock")

            except Exception as e:
                logger.warning(f"[Generate] 真实图片 API 调用失败: {e}，回退 mock")

    # 回退：适配器 / mock
    adapter_name = resolve_adapter_name(body.provider_id, "image")

    try:
        adapter = AdapterFactory.get_adapter("image_generation", adapter_name)
    except ValueError:
        logger.warning(f"[Generate] Adapter '{adapter_name}' not found, using inline mock")
        _tasks[task_id] = {
            "status": "succeeded",
            "result": {"images": [f"https://picsum.photos/seed/{task_id}/1280/720"]},
            "draft_id": body.draft_id,
            "draft_type": body.draft_type,
            "prompt": body.prompt,
            "model": body.model or "mock-image",
        }
        _writeback_if_complete(task_id)
        return {"task_id": task_id}

    # 通过适配器提交任务
    ref_url = body.reference_images[0]["url"] if body.reference_images else None
    result = await adapter.generate_image(prompt=body.prompt, reference_image=ref_url)

    task_id = result.task_id
    _tasks[task_id] = {
        "status": result.status,
        "adapter_type": "image_generation",
        "adapter_name": adapter_name,
        "draft_id": body.draft_id,
        "draft_type": body.draft_type,
        "prompt": body.prompt,
        "model": body.model,
        "result": None,
    }
    logger.info(f"[Generate] Image task submitted: {task_id} via {adapter_name}")
    return {"task_id": task_id}


@router.get("/generate/image/{task_id}")
@router.get("/canvas-image-tasks/{task_id}")
async def poll_image_task(task_id: str):
    """轮询图片生成任务状态"""
    task = _tasks.get(task_id)
    if not task:
        return {"status": "not_found"}

    # 如果已完成，直接返回
    if task["status"] in ("succeeded", "completed", "failed"):
        return task

    # 通过适配器查询最新状态
    adapter_name = task.get("adapter_name", "")
    if adapter_name:
        try:
            adapter = AdapterFactory.get_adapter(task["adapter_type"], adapter_name)
            result = await adapter.fetch_result(task_id)
            if result.status == "completed":
                task["status"] = "succeeded"
                task["result"] = {"images": result.image_urls}
                _writeback_if_complete(task_id)
            elif result.status == "failed":
                task["status"] = "failed"
                task["error"] = result.error_msg
            else:
                task["status"] = "processing"
        except Exception as e:
            logger.warning(f"[Generate] Poll error for {task_id}: {e}")

    return task


@router.post("/generate/video")
@router.post("/canvas-video")
async def generate_video(body: VideoGenRequest):
    """
    提交视频生成任务。
    流程：provider_id → resolve_adapter_name → AdapterFactory → adapter.generate()
    """
    adapter_name = resolve_adapter_name(body.provider_id, "video")

    try:
        adapter = AdapterFactory.get_adapter("video_generation", adapter_name)
    except ValueError:
        logger.warning(f"[Generate] Adapter '{adapter_name}' not found, using inline mock")
        task_id = f"vid-{int(time.time())}-{random.randint(100,999)}"
        video_url = "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"
        _tasks[task_id] = {
            "status": "succeeded",
            "video_url": video_url,
            "draft_id": body.draft_id,
            "draft_type": body.draft_type,
        }
        _writeback_if_complete(task_id)
        return {"task_id": task_id, "video_url": video_url}

    # 通过适配器提交任务
    image_url = body.images[0]["url"] if body.images else ""
    result = await adapter.generate(image_url=image_url, prompt=body.prompt)

    task_id = result.task_id
    _tasks[task_id] = {
        "status": result.status,
        "adapter_type": "video_generation",
        "adapter_name": adapter_name,
        "draft_id": body.draft_id,
        "draft_type": body.draft_type,
        "video_url": None,
    }
    logger.info(f"[Generate] Video task submitted: {task_id} via {adapter_name}")
    return {"task_id": task_id}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """通用任务状态查询"""
    task = _tasks.get(task_id)
    if not task:
        return {"status": "not_found"}

    # 如果还在处理中，尝试通过适配器更新
    if task["status"] not in ("succeeded", "completed", "failed"):
        adapter_name = task.get("adapter_name", "")
        if adapter_name:
            try:
                adapter = AdapterFactory.get_adapter(task["adapter_type"], adapter_name)
                result = await adapter.fetch_result(task_id)
                if result.status == "completed":
                    task["status"] = "succeeded"
                    if hasattr(result, "video_url") and result.video_url:
                        task["video_url"] = result.video_url
                    if hasattr(result, "image_urls") and result.image_urls:
                        task["result"] = {"images": result.image_urls}
                    _writeback_if_complete(task_id)
                elif result.status == "failed":
                    task["status"] = "failed"
                    task["error"] = result.error_msg
            except Exception as e:
                logger.warning(f"[Generate] Poll error for {task_id}: {e}")

    return task


def _writeback_if_complete(task_id: str):
    """任务完成后，将结果回写到 StudioStateService（更新对应 draft）"""
    task = _tasks.get(task_id)
    if not task or task["status"] not in ("succeeded", "completed"):
        return

    draft_id = task.get("draft_id", "")
    if not draft_id:
        return

    svc = StudioStateService.get_instance()
    groups = svc.get_groups()

    # 确定回写字段
    url = ""
    field = "imgUrl"
    if task.get("video_url"):
        url = task["video_url"]
        field = "videoUrl"
    elif task.get("result", {}) and task["result"].get("images"):
        url = task["result"]["images"][0]
        field = "imgUrl"

    if not url:
        return

    # 在 state 中找到对应 draft 并更新
    for category in groups.values():
        for group in category:
            for draft in group.get("drafts", []):
                if draft.get("id") == draft_id:
                    draft[field] = url
                    draft["tag"] = "已生成"
                    svc.save()
                    logger.info(f"[Generate] Writeback: draft {draft_id} → {field}={url[:60]}...")
                    return
