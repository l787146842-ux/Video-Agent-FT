"""生成侧降级链。

职责：同模型跨厂商 fallback 候选链 + 失败可重试性判定。
依赖全部在 core/config 层（settings + core/provider_config），无 web 依赖；
web/generation_dispatch 保留薄 re-export 壳（web 消费方零改动）。
"""
from typing import List

from src.video_agent.config import settings
from src.video_agent.core.provider_config import (
    is_mock_provider_async,
    load_merged_providers_async,
)

# 不可重试的失败特征：内容审核/鉴权/配置类错误换厂商也无意义，直接报错
_NON_RETRYABLE_GEN_HINTS = (
    "审核", "敏感", "违规", "moderation", "unauthorized",
    "余额不足", "未配置", "400", "401", "403", "404",
)


def is_retryable_gen_error(e: Exception) -> bool:
    """生成任务失败是否可换厂商重试。

    优先结构化标记（AdapterError.retryable，含 __cause__ 转译链）；
    无标记时除内容审核/鉴权/配置类特征外默认可重试（生成失败多为
    厂商容量/排队问题，同模型换厂商有机会）。
    """
    for obj in (e, getattr(e, "__cause__", None)):
        flag = getattr(obj, "retryable", None)
        if isinstance(flag, bool):
            return flag
    msg = str(e)
    return not any(h in msg for h in _NON_RETRYABLE_GEN_HINTS)


async def gen_fallback_candidates(provider_id: str, model: str, kind: str) -> List[tuple]:
    """生成侧 fallback 候选链：同模型跨厂商，模型永不换。

    主 (provider, model) → 其他启用供应商中明确在 image_models/video_models
    里列出同名模型的供应商（kind=image/video）。模型列表为空的供应商
    无法验证是否提供该模型，不入链（用户审定：空列表不选）。
    mock 供应商不入链；总长度受 settings.model_fallback_max_candidates 限制。
    """
    limit = max(1, settings.model_fallback_max_candidates)
    candidates: List[tuple] = [(provider_id, model)]
    if not str(model or "").strip():
        return candidates[:limit]
    if await is_mock_provider_async(provider_id, model):
        return candidates[:limit]
    try:
        providers = await load_merged_providers_async()
    except Exception:
        return candidates[:limit]
    models_key = "image_models" if kind == "image" else "video_models"
    for p in providers:
        if len(candidates) >= limit:
            break
        pid = p.get("id") or ""
        if not pid or pid == provider_id or not p.get("enabled", True):
            continue
        if await is_mock_provider_async(pid):
            continue
        models = [str(m or "").strip() for m in (p.get(models_key) or [])]
        if model in models and (pid, model) not in candidates:
            candidates.append((pid, model))
    return candidates[:limit]
