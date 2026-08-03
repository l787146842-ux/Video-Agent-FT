"""
Agent 上下文构建器 — 从 StateManager 抽离。

职责：将 raw state dict 转换为发送给 LLM 的精简 JSON 上下文。
带缓存：状态未变时复用上次结果。
"""
import json
from typing import Any, Dict

from .models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS


def build_agent_context(raw_state: Dict[str, Any], asset_mode: str = "bound", cache: Dict[str, str] | None = None) -> str:
    """构建发送给 LLM 的 Studio 状态上下文。

    Args:
        raw_state: StateManager 内部的 raw dict
        asset_mode: "bound" 仅已绑定资产 / "all" 全部
        cache: 可选缓存字典（状态变更时由 StateManager 清空）

    Returns:
        JSON 字符串
    """
    cache_key = asset_mode
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    # 媒体 URL 截断：只保留前 200 字符（足够定位，避免 base64/长 URL 撑爆上下文）
    def _u(v: Any) -> str:
        return (str(v) if v else "")[:200]

    assets = raw_state.get("assets", [])
    if asset_mode != "all":
        assets = [a for a in assets if a.get("isBound")]

    snapshot = {
        CAT_KEY_ELEMENTS: [
            {
                "id": g["id"],
                "title": g.get("title", ""),
                "desc": g.get("desc", ""),
                "drafts": [
                    {
                        "id": d["id"],
                        "label": d.get("label", ""),
                        "tag": d.get("tag", ""),
                        "mediaType": d.get("mediaType", ""),
                        "prompt": d.get("prompt", ""),
                        "model": d.get("model", ""),
                        "imgUrl": _u(d.get("imgUrl", "")),
                        "videoUrl": _u(d.get("videoUrl", "")),
                        "audioUrl": _u(d.get("audioUrl", "")),
                    }
                    for d in g.get("drafts", [])
                ],
            }
            for g in raw_state.get(CAT_KEY_ELEMENTS, [])
        ],
        CAT_SHOTS: [
            {
                "id": g["id"],
                "title": g.get("title", ""),
                "duration": g.get("duration", ""),
                "shotType": g.get("shotType", ""),
                "sceneRefs": g.get("sceneRefs", []),
                "roughDesc": g.get("roughDesc", ""),
                "drafts": [
                    {
                        "id": d["id"],
                        "label": d.get("label", ""),
                        "tag": d.get("tag", ""),
                        "prompt": d.get("prompt", ""),
                        "model": d.get("model", ""),
                        "mode": d.get("mode", ""),
                        "imgUrl": _u(d.get("imgUrl", "")),
                        "videoUrl": _u(d.get("videoUrl", "")),
                        "audioUrl": _u(d.get("audioUrl", "")),
                        "refAssets": [_u(u) for u in (d.get("refAssets") or [])],
                    }
                    for d in g.get("drafts", [])
                ],
            }
            for g in raw_state.get(CAT_SHOTS, [])
        ],
        CAT_AUDIO_ITEMS: [
            {
                "id": g["id"],
                "title": g.get("title", ""),
                "timeRange": g.get("timeRange", ""),
                "prompt": g.get("prompt", ""),
                "drafts": [
                    {
                        "id": d["id"],
                        "label": d.get("label", ""),
                        "prompt": d.get("prompt", ""),
                        "model": d.get("model", ""),
                        "imgUrl": _u(d.get("imgUrl", "")),
                        "videoUrl": _u(d.get("videoUrl", "")),
                        "audioUrl": _u(d.get("audioUrl", "")),
                    }
                    for d in g.get("drafts", [])
                ],
            }
            for g in raw_state.get(CAT_AUDIO_ITEMS, [])
        ],
        "assets": [
            {"id": a["id"], "name": a.get("name", ""), "type": a.get("type", ""),
             "isBound": a.get("isBound", False), "url": _u(a.get("url", ""))}
            for a in assets
        ],
        "documents": [
            {
                "name": d.get("name", ""),
                "updated_at": d.get("updated_at", ""),
                "content": (d.get("content", "") or "")[:4000],
            }
            for d in raw_state.get("documents", [])
        ],
    }
    result = json.dumps(snapshot, ensure_ascii=False, indent=2)
    if cache is not None:
        cache[cache_key] = result
    return result
