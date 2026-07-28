import asyncio
from typing import Any, Dict, Optional, Type

from loguru import logger
from .base import BaseVideoAdapter, BaseImageAdapter
from .base_chat import BaseChatAdapter


class AdapterFactory:
    """适配器工厂 — 统一管理 chat / image / video 适配器（Rule5: 声明式选择）"""

    _adapters: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(cls, adapter_type: str, provider: str, adapter_instance: Any):
        if adapter_type not in cls._adapters:
            cls._adapters[adapter_type] = {}
        cls._adapters[adapter_type][provider] = adapter_instance
        logger.debug(f"Registered {adapter_type} adapter: {provider}")

    @classmethod
    def get_adapter(cls, adapter_type: str, provider: str = "default") -> Any:
        adapter = cls._adapters.get(adapter_type, {}).get(provider)
        if not adapter:
            raise ValueError(f"Adapter not found for type '{adapter_type}' and provider '{provider}'")
        return adapter

    @classmethod
    def get_chat_adapter(cls, provider: str) -> Optional[BaseChatAdapter]:
        """获取 chat 适配器，不存在时返回 None"""
        return cls._adapters.get("chat", {}).get(provider)

    @classmethod
    def get_image_adapter(cls, provider: str) -> Optional[BaseImageAdapter]:
        """获取 image 适配器，不存在时返回 None"""
        return cls._adapters.get("image_generation", {}).get(provider)

    @classmethod
    def has_adapter(cls, adapter_type: str, provider: str) -> bool:
        return provider in cls._adapters.get(adapter_type, {})

    @classmethod
    def reset(cls):
        """清空所有已注册适配器（测试用）"""
        cls._adapters = {}

    @classmethod
    def register_from_config(cls):
        """根据 data/api_providers.json 动态注册所有适配器（启动时调用）"""
        from src.video_agent.web.provider_config import (
            CLI_PROTOCOLS,
            get_api_key,
            load_api_providers,
        )
        from .openai_compat import OpenAICompatChatAdapter, OpenAICompatImageAdapter
        from .agy_cli import AgyCliImageAdapter

        for p in load_api_providers():
            if not p.get("enabled", True):
                continue
            pid = p.get("id", "")
            protocol = p.get("protocol", "")
            base_url = (p.get("base_url") or "").strip().rstrip("/")
            api_key = get_api_key(pid)

            # Chat 适配器
            if base_url and protocol not in CLI_PROTOCOLS:
                chat_models = p.get("chat_models", [])
                default_model = chat_models[0] if chat_models else ""
                AdapterFactory.register(
                    "chat", pid,
                    OpenAICompatChatAdapter(base_url=base_url, api_key=api_key, model=default_model),
                )

            # Image 适配器
            if protocol in CLI_PROTOCOLS:
                AdapterFactory.register("image_generation", pid, AgyCliImageAdapter())
            elif base_url:
                image_models = p.get("image_models", [])
                default_model = image_models[0] if image_models else ""
                AdapterFactory.register(
                    "image_generation", pid,
                    OpenAICompatImageAdapter(base_url=base_url, api_key=api_key, model=default_model),
                )

        logger.info(
            f"[AdapterFactory] 已注册 "
            f"{len(cls._adapters.get('chat', {}))} chat + "
            f"{len(cls._adapters.get('image_generation', {}))} image 适配器"
        )

class GenerationTaskFailed(Exception):
    """生成任务被供应商标记为失败"""


async def wait_until_complete(adapter: Any, task_id: str, timeout: int = 1200, poll_interval: int = 5) -> Any:
    """
    通用长任务轮询辅助函数。
    - completed → 返回结果
    - failed → 立即抛 GenerationTaskFailed（不再空转到超时）
    - 查询本身出错 → 记录并重试，直到超时
    """
    import time
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            result = await adapter.fetch_result(task_id)
        except Exception as e:
            logger.error(f"Error fetching result for task {task_id}: {e}")
            result = None

        if result is not None:
            if result.status == "completed":
                return result
            if result.status == "failed":
                raise GenerationTaskFailed(
                    f"Generation task {task_id} failed: {result.error_msg}"
                )

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Task {task_id} timeout after {timeout} seconds")
