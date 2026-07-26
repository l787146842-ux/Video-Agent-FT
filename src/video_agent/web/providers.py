"""
Provider 配置管理
读取 .env 中的 API Key，管理可用 provider 列表，支持动态注册适配器。
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger

from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.adapters.mock_adapters import MockImageAdapter, MockVideoAdapter

# 加载 .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# Provider 定义（id → 配置）
PROVIDER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "mock": {
        "name": "Mock (本地测试)",
        "enabled": True,
        "chat_models": ["mock-chat"],
        "image_models": ["mock-image"],
        "video_models": ["mock-video"],
        "api_key_env": "",
    },
    "gemini-cli": {
        "name": "Gemini CLI",
        "enabled": bool(os.getenv("GEMINI_API_KEY")),
        "chat_models": ["gemini-3.1-flash-image-preview-2k"],
        "image_models": ["gpt-image-2"],
        "video_models": [],
        "api_key_env": "GEMINI_API_KEY",
    },
    "volcengine": {
        "name": "火山引擎",
        "enabled": bool(os.getenv("VOLCENGINE_API_KEY")),
        "chat_models": [],
        "image_models": [],
        "video_models": ["seedance2.0_vip"],
        "api_key_env": "VOLCENGINE_API_KEY",
    },
    "custom-api": {
        "name": "Custom API",
        "enabled": bool(os.getenv("CUSTOM_API_KEY")),
        "chat_models": ["gpt-5.5", "gpt-4o-mini"],
        "image_models": ["nano-banana-pro"],
        "video_models": ["veo3-fast", "sora-2"],
        "api_key_env": "CUSTOM_API_KEY",
    },
}


def get_available_providers() -> List[Dict[str, Any]]:
    """返回所有已启用的 provider 列表（供 /api/providers 端点使用）
    优先从 data/api_providers.json 读取（API配置页面持久化的数据），
    如果文件不存在则回退到静态 PROVIDER_REGISTRY。
    """
    import json
    providers_file = PROJECT_ROOT / "data" / "api_providers.json"

    if providers_file.exists():
        try:
            data = json.loads(providers_file.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                result = []
                for p in data:
                    if p.get("enabled", True):
                        result.append({
                            "id": p.get("id", ""),
                            "name": p.get("name", ""),
                            "enabled": True,
                            "chat_models": p.get("chat_models", []),
                            "image_models": p.get("image_models", []),
                            "video_models": p.get("video_models", []),
                        })
                if result:
                    return result
        except Exception as e:
            logger.warning(f"[Providers] 读取 JSON 配置失败: {e}, 回退到静态注册表")

    # 回退：静态注册表
    result = []
    for pid, cfg in PROVIDER_REGISTRY.items():
        if cfg["enabled"]:
            result.append({
                "id": pid,
                "name": cfg["name"],
                "enabled": True,
                "chat_models": cfg["chat_models"],
                "image_models": cfg["image_models"],
                "video_models": cfg["video_models"],
            })
    # 确保至少 mock 可用
    if not result:
        result.append({
            "id": "mock",
            "name": "Mock (本地测试)",
            "enabled": True,
            "chat_models": ["mock-chat"],
            "image_models": ["mock-image"],
            "video_models": ["mock-video"],
        })
    return result


def resolve_adapter_name(provider_id: str, kind: str) -> str:
    """从 provider_id + kind 解析出 AdapterFactory 中注册的适配器名称"""
    # 当前所有 provider 都映射到 mock 适配器（后续替换为真实适配器）
    if kind == "image":
        return "mock_image"
    elif kind == "video":
        return "mock_video"
    return "mock"


def register_adapters():
    """启动时注册所有可用适配器到 AdapterFactory"""
    # 注册 Mock 适配器（始终可用）
    AdapterFactory.register("image_generation", "mock_image", MockImageAdapter(delay_seconds=2))
    AdapterFactory.register("video_generation", "mock_video", MockVideoAdapter(delay_seconds=3))
    logger.info("[Providers] Registered mock adapters (image + video)")

    # 后续：根据 .env 中的 API Key 注册真实适配器
    # if os.getenv("VOLCENGINE_API_KEY"):
    #     AdapterFactory.register("video_generation", "volcengine", VolcEngineVideoAdapter(...))
    # if os.getenv("GEMINI_API_KEY"):
    #     AdapterFactory.register("image_generation", "gemini", GeminiImageAdapter(...))
