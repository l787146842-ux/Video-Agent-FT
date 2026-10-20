import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from .base import BaseVideoAdapter, BaseImageAdapter
from .base_chat import BaseChatAdapter
from src.video_agent.utils.cancel_token import (
    GenerationCancelled,
    current_cancel_token,
    interruptible_sleep,
)
from src.video_agent.utils.provider_config_loader import (
    config_fingerprint,
    get_api_key,
    load_merged_providers,
)
from src.video_agent.core.provider_config import (
    CLI_PROTOCOLS,
    exclude_retired_mock_providers,
)


async def _close_quietly(adapter: Any) -> None:
    """释放旧适配器连接池；失败只记日志（重建路径不得因释放失败而中断）。"""
    try:
        await adapter.close()
    except Exception as e:
        logger.debug("[AdapterFactory] 释放旧适配器连接池失败: {}", e)


# 待释放任务强引用：asyncio 只对任务持弱引用，不持强引用会被 GC 中途回收
_pending_close_tasks: set = set()


def _schedule_close(loop: Any, adapter: Any) -> None:
    """把连接池释放调度到事件循环（持有强引用直至完成）。"""
    task = loop.create_task(_close_quietly(adapter))
    _pending_close_tasks.add(task)
    task.add_done_callback(_pending_close_tasks.discard)


def _dispose(adapters: List[Any]) -> None:
    """丢弃给定适配器并尽力释放其连接池。

    同步取用路径不能 await，故调度到运行中的事件循环；无运行中循环
    （纯同步脚本）时只丢弃引用，实例随 GC 回收、不再被复用。
    """
    if not adapters:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug(
            "[AdapterFactory] 无运行中事件循环，{} 个旧适配器仅丢弃引用", len(adapters))
        return
    for adapter in adapters:
        if callable(getattr(adapter, "close", None)):
            _schedule_close(loop, adapter)


class AdapterFactory:
    """适配器工厂 — 统一管理 chat / image / video 适配器（Rule5: 声明式选择）

    配置新鲜度：取用即按**当前**配置自检——供应商配置或 API Key 一旦变更
    （API 设置页保存、或直接改 data/api_providers.json / API/.env），下次取用
    即按新配置重建，不需要重启进程。判定源 = utils.provider_config_loader
    .config_fingerprint（单一事实源），本类只缓存建表时的指纹用于对比。
    """

    _adapters: Dict[str, Dict[str, Any]] = {}
    # 注册表构建时的配置指纹（None = 尚未建表）；取用时对比，不一致即校准。
    _fingerprint: Optional[Tuple[Any, ...]] = None

    @classmethod
    def register(cls, adapter_type: str, provider: str, adapter_instance: Any):
        if adapter_type not in cls._adapters:
            cls._adapters[adapter_type] = {}
        cls._adapters[adapter_type][provider] = adapter_instance
        logger.debug(f"Registered {adapter_type} adapter: {provider}")

    @classmethod
    def refresh_if_config_changed(cls) -> bool:
        """配置已变更时按当前配置校准注册表；返回是否发生校准。

        每个取用入口的第一步。指纹未变 = 零开销（两次 stat + 计数器比较），
        不触碰任何已有实例，故不影响连接池复用。

        校准按**供应商逐个比对**：只有端点/凭证真正变了的那些实例被替换并
        释放连接池，其余原样保留——避免改一个供应商的 Key 就把别的供应商
        在途任务（如视频轮询）的连接池一起关掉。
        """
        current = config_fingerprint()
        if cls._fingerprint == current:
            return False
        cls._fingerprint = current
        if not cls._adapters:
            # 尚未建表：交给 register_from_config 从零注册
            return False
        logger.info(
            "[AdapterFactory] 检测到供应商配置已变更，按当前配置校准适配器"
            "（API Key / Base URL / 模型列表改动即时生效，无需重启）")
        return cls.register_from_config()

    @staticmethod
    def _provider_of(key: str) -> str:
        """从注册键取供应商 id（键形如 `pid` 或 `pid:model`）。

        按**首个**冒号切分：模型名本身可含冒号（如 `cn:deepseek-v4.1-flash`），
        供应商 id 不含。
        """
        return key.split(":", 1)[0]

    @staticmethod
    def _endpoint_matches(
        adapter: Any, base_url: str, api_key: str, model: Optional[str] = None
    ) -> bool:
        """缓存实例的端点/凭证是否与当前解析值一致（不一致 = 陈旧，须重建）。

        model=None 表示不比模型（用于 `pid:model` 按需键：模型名由请求给定，
        与供应商默认模型本就不同，不构成陈旧判据）。
        """
        # CLI 类适配器不持端点/凭证（无这些属性，走本机子进程）→ 无陈旧可言
        if not hasattr(adapter, "api_key") and not hasattr(adapter, "base_url"):
            return True
        if getattr(adapter, "api_key", None) != api_key:
            return False
        cached_url = (getattr(adapter, "base_url", None) or "").rstrip("/")
        if cached_url != (base_url or "").rstrip("/"):
            return False
        if model:
            cached_model = getattr(adapter, "model", None)
            if cached_model is not None and cached_model != model:
                return False
        return True

    @classmethod
    def _ensure(
        cls, adapter_type: str, key: str, base_url: str, api_key: str,
        model: str, build: Any,
    ) -> Tuple[Any, bool]:
        """确保某槽位存在与当前配置一致的实例；端点变了才替换（其余复用连接池）。

        返回 (adapter, replaced)：replaced 表示本次替换掉了旧实例（供调用方统计）。
        """
        existing = cls._adapters.get(adapter_type, {}).get(key)
        if existing is not None and cls._endpoint_matches(
                existing, base_url, api_key, model):
            return existing, False
        adapter = build()
        cls.register(adapter_type, key, adapter)
        if existing is not None:
            logger.info(
                f"[AdapterFactory] 适配器 '{adapter_type}:{key}' 的端点/凭证已变更，"
                "按当前配置重建（旧实例连接池释放）")
            _dispose([existing])
            return adapter, True
        return adapter, False

    @classmethod
    def get_adapter(cls, adapter_type: str, provider: str = "default") -> Any:
        cls.refresh_if_config_changed()
        adapter = cls._adapters.get(adapter_type, {}).get(provider)
        if not adapter:
            raise ValueError(f"Adapter not found for type '{adapter_type}' and provider '{provider}'")
        return adapter

    @classmethod
    def get_chat_adapter(cls, provider: str) -> Optional[BaseChatAdapter]:
        """获取 chat 适配器，不存在时返回 None"""
        cls.refresh_if_config_changed()
        return cls._adapters.get("chat", {}).get(provider)

    @classmethod
    def get_or_create_chat_adapter(
        cls, provider: str, base_url: str, api_key: str, model: str
    ) -> BaseChatAdapter:
        """按 provider+model 获取或创建 chat 适配器（连接池复用）。

        chat 链路的统一入口（Rule4）：同一 provider+model 复用同一实例及其
        httpx 连接池，避免每次请求新建 AsyncClient 造成连接泄漏；
        实例统一注册在 _adapters["chat"] 中，由 lifespan 关闭时统一 close()。

        本方法按**本次解析出的端点/凭证**校验缓存实例（不只依赖配置指纹）：
        实例若建于 Key 保存之前（持空 Key），此处直接判定为陈旧并按当前值
        重建。否则请求不带 Authorization 直连上游吃 401，而「验证地址」走的
        是一次性探测、仍显示正常，表现为「配置好了却用不了、必须重启」。
        """
        key = f"{provider}:{model}" if model else provider
        cls.refresh_if_config_changed()
        from .openai_compat import OpenAICompatChatAdapter
        adapter, _replaced = cls._ensure(
            "chat", key, base_url, api_key, model,
            lambda: OpenAICompatChatAdapter(
                base_url=base_url, api_key=api_key, model=model, provider_id=provider),
        )
        return adapter

    @classmethod
    def get_image_adapter(cls, provider: str) -> Optional[BaseImageAdapter]:
        """获取 image 适配器，不存在时返回 None"""
        cls.refresh_if_config_changed()
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
        cls._fingerprint = None

    @classmethod
    def reset(cls):
        """清空所有已注册适配器（测试用）"""
        cls._adapters = {}
        cls._fingerprint = None

    @classmethod
    def register_from_config(cls) -> bool:
        """按当前配置注册/校准所有适配器；返回是否替换过任何实例。

        启动时调用（从零建表）；配置变更后由 refresh_if_config_changed 再调用
        做增量校准——端点未变的实例原样保留（连接池复用），变了的按新配置重建
        并释放旧连接池。
        """
        from .openai_compat import OpenAICompatChatAdapter, OpenAICompatImageAdapter
        from .agy_cli import AgyCliImageAdapter
        from .video_compat import OpenAICompatVideoAdapter

        # mock 退役供应商不注册适配器（过滤经唯一收口点，禁止内联判定）
        specs = {}
        for p in exclude_retired_mock_providers(load_merged_providers()):
            if not p.get("enabled", True):
                continue
            specs[p.get("id", "")] = p

        # 先清掉按需键（`pid:model`）中属于已变更/已下架供应商的条目：
        # 它们由 get_or_create_chat_adapter 建，模型名由请求给定，故只比端点/凭证。
        for key in list(cls._adapters.get("chat", {})):
            if ":" not in key:
                continue
            pid = cls._provider_of(key)
            p = specs.get(pid)
            stale = p is None or not cls._endpoint_matches(
                cls._adapters["chat"][key],
                (p.get("base_url") or "").strip().rstrip("/") if p else "",
                get_api_key(pid) if p else "",
            )
            if stale:
                _dispose([cls._adapters["chat"].pop(key)])

        replaced = False

        def _ensure(key_type: str, key: str, base_url: str, api_key: str,
                    model: str, build: Any) -> None:
            """记录是否替换过实例（复用 cls._ensure，单一实现）。"""
            nonlocal replaced
            _adapter, did_replace = cls._ensure(
                key_type, key, base_url, api_key, model, build)
            replaced = replaced or did_replace

        for pid, p in specs.items():
            protocol = p.get("protocol", "")
            base_url = (p.get("base_url") or "").strip().rstrip("/")
            api_key = get_api_key(pid)

            # Chat 适配器
            if base_url and protocol not in CLI_PROTOCOLS:
                chat_models = p.get("chat_models", [])
                default_model = chat_models[0] if chat_models else ""
                _ensure(
                    "chat", pid, base_url, api_key, default_model,
                    lambda pid=pid, base_url=base_url, api_key=api_key,
                    default_model=default_model: OpenAICompatChatAdapter(
                        base_url=base_url, api_key=api_key, model=default_model,
                        provider_id=pid),
                )

            # Image 适配器
            if protocol in CLI_PROTOCOLS:
                _ensure("image_generation", pid, "", "", "",
                        lambda: AgyCliImageAdapter())
            elif base_url:
                image_models = p.get("image_models", [])
                default_model = image_models[0] if image_models else ""
                _ensure(
                    "image_generation", pid, base_url, api_key, default_model,
                    lambda base_url=base_url, api_key=api_key,
                    default_model=default_model: OpenAICompatImageAdapter(
                        base_url=base_url, api_key=api_key, model=default_model),
                )

            # Video 适配器（消费 video_models 字段）
            if base_url and protocol not in CLI_PROTOCOLS:
                video_models = p.get("video_models", [])
                if video_models:
                    default_video_model = video_models[0]
                    _ensure(
                        "video_generation", pid, base_url, api_key, default_video_model,
                        lambda base_url=base_url, api_key=api_key,
                        default_video_model=default_video_model, p=p:
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
            + ("（配置变更：已按新配置重建）" if replaced else "")
        )
        # 记录本次建表所用配置的指纹（取用路径据此判定配置是否已变更）
        cls._fingerprint = config_fingerprint()
        return replaced


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
