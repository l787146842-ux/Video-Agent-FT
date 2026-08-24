"""
Agent 上下文构建域 — 从 StateManager 抽离（P7-1 追加状态视图组装）。

职责：将 raw state dict 转换为各消费面的状态视图（纯函数组装，不落盘）：
- build_agent_context：发送给 LLM 的精简 JSON 上下文（带缓存：状态未变时复用）
- build_full_snapshot：完整状态深拷贝快照（前端刷新 / SSE done payload）
- build_frontend_view：前端 camelCase JSON 视图（Pydantic 校验后序列化）
"""
import json
from typing import Any, Dict

from src.video_agent.config import settings

from .models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ProjectState


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
        # 交互阶段状态：让模型看到上一轮是否停在「等待确认」暂停点，
        # 避免用户回复确认后模型感知不到进度、从头重复同一套操作
        "interaction": _build_interaction(raw_state),
        # 剧本分析摘要（script_analyze 产出）：一句话总结 + 关键要点，
        # 拆解/提示词阶段主模型必须看到，否则会凭空概括
        "analysis": _build_analysis(raw_state),
    }
    result = _dumps(snapshot)
    if cache is not None:
        cache[cache_key] = result
    return result


def _build_interaction(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    """交互阶段状态快照（暂停说明截断防撑爆上下文）"""
    inter = raw_state.get("interaction") or {}
    return {
        "awaiting_confirmation": bool(inter.get("awaiting_confirmation")),
        "confirmation_message": (str(inter.get("confirmation_message") or ""))[:300],
        # 故事板结构待用户确认窗口：此时严禁写入提示词草案，须先等用户回应
        "storyboard_pending_review": bool(inter.get("storyboard_pending")),
        # 流程事件账本（截断/部分完成等；只带最近 3 条，防膨胀）
        "flowEvents": [
            {"kind": e.get("kind", ""), "detail": str(e.get("detail") or "")[:200]}
            for e in (raw_state.get("flowEvents") or [])[-3:]
        ],
    }


def _build_analysis(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    """剧本分析摘要（script_analyze 产出）紧凑注入。"""
    analysis = raw_state.get("analysis")
    if not isinstance(analysis, dict):
        return {}
    out: Dict[str, Any] = {}
    summary = str(analysis.get("summary") or "").strip()
    if summary:
        out["summary"] = summary[:500]
    kp = [str(k) for k in (analysis.get("key_points") or []) if str(k or "").strip()]
    if kp:
        out["key_points"] = kp[:6]
    return out


def build_full_snapshot(raw_state: Dict[str, Any], board_version: int) -> Dict[str, Any]:
    """完整状态快照（供前端刷新/SSE done payload）。

    返回深拷贝（json round-trip），调用方可任意使用不会回写
    污染内部状态；旧版浅拷贝共享嵌套引用的契约仅靠注释约束，过于脆弱。
    快照仅在聊天完成/mock 路径低频调用，序列化开销可接受。
    """
    snap = json.loads(json.dumps(raw_state, ensure_ascii=False))
    # 乐观锁版本号随快照下发（不写入状态 JSON 本体，避免污染 undo/快照）
    snap["board_version"] = board_version
    # E-2 消息单一来源：快照中对话只留元信息，消息副本不再随快照下发
    #（活跃对话消息仍由顶层 chatMessages 携带；切会话走按会话拉消息接口）
    for conv in snap.get("conversations") or []:
        if isinstance(conv, dict):
            conv.pop("messages", None)
    return snap


def build_frontend_view(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    """前端使用的 camelCase JSON 视图（Pydantic 校验后序列化；
    校验失败降级为 raw dict 直出）。"""
    try:
        ps = ProjectState.model_validate(raw_state)
        return ps.model_dump(by_alias=True, mode="json")
    except Exception:
        return dict(raw_state)


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
        "interaction": _build_interaction(raw_state),
        "analysis": _build_analysis(raw_state),
    }
