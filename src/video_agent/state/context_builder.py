"""
Agent 上下文构建器 — 从 StateManager 抽离。

职责：将 raw state dict 转换为发送给 LLM 的精简 JSON 上下文。
带缓存：状态未变时复用上次结果。
"""
import json
from typing import Any, Dict

from src.video_agent.config import settings

from .models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS


def _dumps(snapshot: Dict[str, Any]) -> str:
    """状态 JSON 序列化：默认紧凑格式（模型读紧凑 JSON 无损，省 20-30% token）；
    CONTEXT_JSON_COMPACT=false 回退 indent=2 便于人工排查日志"""
    if settings.context_json_compact:
        return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(snapshot, ensure_ascii=False, indent=2)


def build_agent_context(
    raw_state: Dict[str, Any],
    asset_mode: str = "bound",
    cache: Dict[str, str] | None = None,
    degraded: bool = False,
) -> str:
    """构建发送给 LLM 的 Studio 状态上下文。

    Args:
        raw_state: StateManager 内部的 raw dict
        asset_mode: "bound" 仅已绑定资产 / "all" 全部
        cache: 可选缓存字典（状态变更时由 StateManager 清空）
        degraded: 降级模式（system 超预算保险丝用）——草稿细节不注入，
                  只留组标题/编号/草稿计数，大幅压缩 system 段体积

    Returns:
        JSON 字符串
    """
    cache_key = f"{asset_mode}:degraded" if degraded else asset_mode
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    if degraded:
        result = _dumps(_build_degraded_snapshot(raw_state))
        if cache is not None:
            cache[cache_key] = result
        return result

    # 媒体 URL 截断：只保留前 200 字符（足够定位，避免 base64/长 URL 撑爆上下文）
    def _u(v: Any) -> str:
        return (str(v) if v else "")[:200]

    # 渐进式披露：草稿 prompt 全文不注入，只给字数；模型需要时调 read_draft 按需读取
    def _pc(d: Dict[str, Any]) -> int:
        return len(d.get("prompt", "") or "")

    assets = raw_state.get("assets", [])
    if asset_mode != "all":
        assets = [a for a in assets if a.get("isBound")]

    snapshot = {
        CAT_KEY_ELEMENTS: [
            {
                "id": g["id"],
                # 编号与前端卡片小标一致：组号 index，卡号 组号-卡序号（如 1-2），
                # action 里的 draft_id 可直接用卡号定位
                "index": gi + 1,
                "title": g.get("title", ""),
                "desc": g.get("desc", ""),
                "drafts": [
                    {
                        "id": d["id"],
                        "index": f"{gi + 1}-{di + 1}",
                        "label": d.get("label", ""),
                        "tag": d.get("tag", ""),
                        "mediaType": d.get("mediaType", ""),
                        "prompt_chars": _pc(d),
                        "model": d.get("model", ""),
                        "imgUrl": _u(d.get("imgUrl", "")),
                        "videoUrl": _u(d.get("videoUrl", "")),
                        "audioUrl": _u(d.get("audioUrl", "")),
                    }
                    for di, d in enumerate(g.get("drafts", []))
                ],
            }
            for gi, g in enumerate(raw_state.get(CAT_KEY_ELEMENTS, []))
        ],
        CAT_SHOTS: [
            {
                "id": g["id"],
                "index": gi + 1,
                "title": g.get("title", ""),
                "duration": g.get("duration", ""),
                "shotType": g.get("shotType", ""),
                "sceneRefs": g.get("sceneRefs", []),
                "roughDesc": g.get("roughDesc", ""),
                "drafts": [
                    {
                        "id": d["id"],
                        "index": f"{gi + 1}-{di + 1}",
                        "label": d.get("label", ""),
                        "tag": d.get("tag", ""),
                        "prompt_chars": _pc(d),
                        "model": d.get("model", ""),
                        "mode": d.get("mode", ""),
                        "imgUrl": _u(d.get("imgUrl", "")),
                        "videoUrl": _u(d.get("videoUrl", "")),
                        "audioUrl": _u(d.get("audioUrl", "")),
                        "refAssets": [_u(u) for u in (d.get("refAssets") or [])],
                    }
                    for di, d in enumerate(g.get("drafts", []))
                ],
            }
            for gi, g in enumerate(raw_state.get(CAT_SHOTS, []))
        ],
        CAT_AUDIO_ITEMS: [
            {
                "id": g["id"],
                "index": gi + 1,
                "title": g.get("title", ""),
                "timeRange": g.get("timeRange", ""),
                "prompt_chars": len(g.get("prompt", "") or ""),
                "drafts": [
                    {
                        "id": d["id"],
                        "index": f"{gi + 1}-{di + 1}",
                        "label": d.get("label", ""),
                        "prompt_chars": _pc(d),
                        "model": d.get("model", ""),
                        "imgUrl": _u(d.get("imgUrl", "")),
                        "videoUrl": _u(d.get("videoUrl", "")),
                        "audioUrl": _u(d.get("audioUrl", "")),
                    }
                    for di, d in enumerate(g.get("drafts", []))
                ],
            }
            for gi, g in enumerate(raw_state.get(CAT_AUDIO_ITEMS, []))
        ],
        "assets": [
            {"id": a["id"], "name": a.get("name", ""), "type": a.get("type", ""),
             "isBound": a.get("isBound", False), "url": _u(a.get("url", ""))}
            for a in assets
        ],
        # 规格文档清单（渐进式披露）：仅名称/时间/字数/前 200 字预览，
        # 全文不注入，模型开工前调 read_project_doc 按需读取
        "documents": [
            {
                "name": d.get("name", ""),
                "updated_at": d.get("updated_at", ""),
                "char_count": len(d.get("content", "") or ""),
                "preview": ((d.get("content", "") or "")[:200]).replace("\n", " "),
            }
            for d in raw_state.get("documents", [])
        ],
        # 上传附件文档清单（故事/剧本）：仅名称/类型/字数，正文不注入，
        # 模型需要全文时调用 read_uploaded_doc 按需检索
        "uploadedDocs": [
            {
                "id": d.get("id", ""),
                "name": d.get("name", ""),
                "kind": d.get("kind", ""),
                "char_count": d.get("char_count", 0),
                "uploaded_at": d.get("uploaded_at", ""),
            }
            for d in raw_state.get("uploadedDocs", [])
        ],
    }
    result = _dumps(snapshot)
    if cache is not None:
        cache[cache_key] = result
    return result


def _build_degraded_snapshot(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    """降级快照：只保留组标题/编号/草稿计数（system 超预算保险丝的第二道防线）。
    模型看到后可调 read_draft / read_project_doc 按需取细节。"""

    def _groups(cat_key: str) -> list:
        return [
            {
                "id": g["id"],
                "index": gi + 1,
                "title": g.get("title", ""),
                "draft_count": len(g.get("drafts", [])),
            }
            for gi, g in enumerate(raw_state.get(cat_key, []))
        ]

    return {
        "degraded": True,
        "note": "状态已降级：草稿细节未注入，请用 read_draft/read_project_doc 按需读取",
        CAT_KEY_ELEMENTS: _groups(CAT_KEY_ELEMENTS),
        CAT_SHOTS: _groups(CAT_SHOTS),
        CAT_AUDIO_ITEMS: _groups(CAT_AUDIO_ITEMS),
        "asset_count": len(raw_state.get("assets", [])),
        "documents": [d.get("name", "") for d in raw_state.get("documents", [])],
        "uploadedDocs": [d.get("name", "") for d in raw_state.get("uploadedDocs", [])],
    }
