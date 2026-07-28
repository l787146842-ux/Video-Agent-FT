"""
Provider 可用列表 + 适配器注册。

配置读取统一走 web/provider_config.py；本模块只负责：
- get_available_providers()：给前端下拉框的已启用供应商列表
- register_adapters()：启动时注册适配器（当前仅 mock；真实适配器接入点在此）
"""
from typing import Any, Dict, List

from dotenv import load_dotenv
from loguru import logger

from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.adapters.mock_adapters import MockImageAdapter, MockVideoAdapter
from src.video_agent.utils.paths import PROJECT_ROOT
from src.video_agent.web.provider_config import load_api_providers, load_merged_providers

# 加载根目录 .env（运行环境变量）
load_dotenv(PROJECT_ROOT / ".env")


def get_available_providers() -> List[Dict[str, Any]]:
    """返回所有已启用的 provider 列表（合并本地 + 熊布，供 /api/config 等端点使用）"""
    result = []
    for p in load_merged_providers():
        if p.get("enabled", True):
            result.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "enabled": True,
                "source": p.get("_source", "local"),
                "chat_models": p.get("chat_models", []),
                "image_models": p.get("image_models", []),
                "video_models": p.get("video_models", []),
            })
    # 确保至少 mock 可用
    if not result:
        result.append({
            "id": "mock",
            "name": "Mock (本地测试)",
            "enabled": True,
            "source": "local",
            "chat_models": ["mock-chat"],
            "image_models": ["mock-image"],
            "video_models": ["mock-video"],
        })
    return result


def resolve_adapter_name(provider_id: str, kind: str) -> str:
    """从 provider_id + kind 解析出 AdapterFactory 中注册的适配器名称。
    仅 mock 路径使用（真实供应商走 web/generation.py 的 HTTP 管线）。"""
    if kind == "image":
        return "mock_image"
    elif kind == "video":
        return "mock_video"
    return "mock"


def register_adapters():
    """启动时注册所有可用适配器到 AdapterFactory（Rule5: 声明式选择）"""
    # Mock 适配器（开发/演示用）
    AdapterFactory.register("image_generation", "mock_image", MockImageAdapter(delay_seconds=2))
    AdapterFactory.register("video_generation", "mock_video", MockVideoAdapter(delay_seconds=3))
    logger.info("[Providers] Registered mock adapters (image + video)")

    # 真实适配器：根据 data/api_providers.json 动态注册
    AdapterFactory.register_from_config()
