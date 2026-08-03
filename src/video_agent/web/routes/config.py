"""
/api/config — 全局配置端点
返回可用的模型列表（chat / image / video）及画布 URL，供前端渲染。
"""
from fastapi import APIRouter

from src.video_agent.config import settings

router = APIRouter()

# 默认模型列表（后续可从 AdapterFactory / .env 动态读取）
DEFAULT_CHAT_MODELS = ["gpt-5.5", "gpt-4o-mini", "gemini-3.1-flash-image-preview-2k"]
DEFAULT_IMAGE_MODELS = ["nano-banana-pro", "gpt-image-2"]
DEFAULT_VIDEO_MODELS = ["veo3-fast", "sora-2", "seedance2.0_vip"]


@router.get("/config")
async def get_config():
    """前端 loadCanvasApiConfig() 调用"""
    return {
        "chat_models": DEFAULT_CHAT_MODELS,
        "image_models": DEFAULT_IMAGE_MODELS,
        "video_models": DEFAULT_VIDEO_MODELS,
        "canvas_url": settings.canvas_base_url,
    }
