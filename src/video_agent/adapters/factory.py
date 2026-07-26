import asyncio
from typing import Any, Dict, Optional, Type

from loguru import logger
from .base import BaseVideoAdapter, BaseImageAdapter

class AdapterFactory:
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

async def wait_until_complete(adapter: Any, task_id: str, timeout: int = 1200, poll_interval: int = 5) -> Any:
    """
    通用长任务轮询辅助函数
    """
    import time
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            result = await adapter.fetch_result(task_id)
            if result.status == "completed":
                return result
            if result.status == "failed":
                raise Exception(f"Generation task failed: {result.error_msg}")
        except Exception as e:
            logger.error(f"Error fetching result for task {task_id}: {e}")
            # Depending on error type, might want to raise or retry
            
        await asyncio.sleep(poll_interval)
        
    raise TimeoutError(f"Task {task_id} timeout after {timeout} seconds")
