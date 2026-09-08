import time
from typing import Any, Dict, Optional, Type

from loguru import logger
from .base import BaseVideoAdapter, BaseImageAdapter
from .base_chat import BaseChatAdapter
from src.video_agent.utils.cancel_token import (
    GenerationCancelled,
    current_cancel_token,
    interruptible_sleep,
)
from src.video_agent.utils.provider_config_loader import (
    get_api_key,
    load_merged_providers,
)
from src.video_agent.core.provider_config import (
    CLI_PROTOCOLS,
    exclude_retired_mock_providers,
)


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
    def get_or_create_chat_adapter(
        cls, provider: str, base_url: str, api_key: str, model: str
    ) -> BaseChatAdapter:
        """按 provider+model 获取或创建 chat 适配器（连接池复用）。

        chat 链路的统一入口（Rule4）：同一 provider+model 复用同一实例及其
        httpx 连接池，避免每次请求新建 AsyncClient 造成连接泄漏；
        实例统一注册在 _adapters["chat"] 中，由 lifespan 关闭时统一 close()。
        """
        key = f"{provider}:{model}" if model else provider
        existing = cls._adapters.get("chat", {}).get(key)
        if existing is not None:
            return existing
        from .openai_compat import OpenAICompatChatAdapter
        adapter = OpenAICompatChatAdapter(
            base_url=base_url, api_key=api_key, model=model, provider_id=provider)
        cls.register("chat", key, adapter)
        return adapter

    @classmethod
    def get_image_adapter(cls, provider: str) -> Optional[BaseImageAdapter]:
        """获取 image 适配器，不存在时返回 None"""
        return cls._adapters.get("image_generation", {}).get(provider)

    @classmethod
    def has_adapter(cls, adapter_type: str, provider: str) -> bool:
        return provider in cls._adapters.get(adapter_type, {})

    @classmethod
    def iter_adapters(cls, adapter_type: str):
        """公开遍历某类型下所有 (provider, adapter)（如 lifespan 关闭时统一 close）"""
        return list(cls._adapters.get(adapter_type, {}).items())

    @classmethod
    def clear_all(cls):
        """清空所有已注册适配器（lifespan 关闭时用）"""
        cls._adapters.clear()

    @classmethod
    def reset(cls):
        """清空所有已注册适配器（测试用）"""
        cls._adapters = {}

    @classmethod
    def register_from_config(cls):
        """根据合并后的 provider 配置动态注册所有适配器（启动时调用）"""
        from .openai_compat import OpenAICompatChatAdapter, OpenAICompatImageAdapter
        from .agy_cli import AgyCliImageAdapter
        from .video_compat import OpenAICompatVideoAdapter

        # mock 退役供应商不注册适配器（过滤经唯一收口点，禁止内联判定）
        for p in exclude_retired_mock_providers(load_merged_providers()):
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
                    OpenAICompatChatAdapter(
                        base_url=base_url, api_key=api_key, model=default_model,
                        provider_id=pid),
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

            # Video 适配器（消费 video_models 字段）
            if base_url and protocol not in CLI_PROTOCOLS:
                video_models = p.get("video_models", [])
                if video_models:
                    default_video_model = video_models[0]
                    AdapterFactory.register(
                        "video_generation", pid,
                        OpenAICompatVideoAdapter(
                            base_url=base_url,
                            api_key=api_key,
                            model=default_video_model,
                            video_request_mode=p.get("video_request_mode") or "classic",
                        ),
                    )

        logger.info(
            f"[AdapterFactory] 已注册 "
            f"{len(cls._adapters.get('chat', {}))} chat + "
            f"{len(cls._adapters.get('image_generation', {}))} image + "
            f"{len(cls._adapters.get('video_generation', {}))} video 适配器"
        )

class GenerationTaskFailed(Exception):
    """生成任务被供应商标记为失败"""


async def wait_until_complete(adapter: Any, task_id: str, timeout: int = 1200) -> Any:
    """
    通用长任务轮询辅助函数（渐进退避）。
    - completed → 返回结果
    - failed → 立即抛 GenerationTaskFailed（不再空转到超时）
    - 取消令牌命中 → 立即抛 GenerationCancelled（协作式中断，不等硬取消）
    - 查询本身出错 → 记录并重试，直到超时

    轮询间隔渐进策略：前 3 次 2s，之后 5s，超过 60s 后 10s。

    取消检查点协议：每圈头部读上下文取消令牌（agent_loop 绑定，
    scope=stop_scope）；等待经 interruptible_sleep 切片睡，取消响应
    延迟有界。供应商侧任务已提交时可能仍在进行，web 层 inflight
    登记兜底告知（第一版不撤销）。
    """
    start_time = time.time()
    poll_count = 0

    while time.time() - start_time < timeout:
        _cancel_tok = current_cancel_token()
        if _cancel_tok is not None and _cancel_tok.cancelled:
            raise GenerationCancelled(
                f"生成任务 {task_id} 已被取消（供应商侧可能仍在进行，"
                "详见在途任务登记）"
            )
        try:
            result = await adapter.fetch_result(task_id)
        except GenerationCancelled:
            raise
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

        # 渐进退避：前 3 次 2s，之后 5s，超过 60s 后 10s；
        # 可中断等待：取消命中提前醒来，圈头检查点抛出
        elapsed = time.time() - start_time
        poll_count += 1
        if poll_count <= 3:
            interval = 2
        elif elapsed < 60:
            interval = 5
        else:
            interval = 10
        await interruptible_sleep(interval, _cancel_tok)

    raise TimeoutError(f"Task {task_id} timeout after {timeout} seconds")
