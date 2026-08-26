"""
Provider 可用列表 + 适配器注册。

配置读取统一走 core/provider_config.py；本模块只负责：
- get_available_providers()：给前端下拉框的已启用供应商列表
- register_adapters()：启动时按 data/api_providers.json 动态注册真实适配器
"""
from typing import Any, Dict, List

from dotenv import load_dotenv

from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.utils.paths import PROJECT_ROOT
from src.video_agent.core.provider_config import (
    exclude_retired_mock_providers,
    load_merged_providers,
)

# 加载根目录 .env（运行环境变量）
load_dotenv(PROJECT_ROOT / ".env")


def get_available_providers() -> List[Dict[str, Any]]:
    """返回所有已启用的 provider 列表（合并本地 + 画布，供 /api/config 等端点使用）"""
    result = []
    # mock 演示通道退役过滤统一经 provider_config 收口点（批次F）
    for p in exclude_retired_mock_providers(load_merged_providers()):
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
    return result


def register_adapters():
    """启动时注册所有可用适配器到 AdapterFactory（Rule5: 声明式选择）"""
    # 真实适配器：根据 data/api_providers.json 动态注册
    AdapterFactory.register_from_config()
