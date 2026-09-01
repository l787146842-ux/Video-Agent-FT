"""
Agent 上下文构建域 — 从 StateManager 抽离。

职责：将 raw state dict 转换为各消费面的状态视图（纯函数组装，不落盘）：
- build_agent_context：发送给 LLM 的精简 JSON 上下文（带缓存：状态未变时复用）
- build_full_snapshot：完整状态深拷贝快照（前端刷新 / SSE done payload）
- build_frontend_view：前端 camelCase JSON 视图（Pydantic 校验后序列化）
"""
import json
from typing import Any, Dict, Optional, Tuple

from src.video_agent.config import settings

from .models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ProjectState

# 第 5 批上下文治理（Q6 裁决 2026-09-01）：分阶段注入策略表（policy-as-data）。
# stage 键 → 该阶段全量注入的类别（焦点）；非焦点类别只注入组级摘要
#（id/编号/标题/草稿计数 + 指针，全文经 read_state_group 按需读回）。
# 空元组 = 三类全摘要（analysis 阶段分组尚未诞生）；
# 不在表内的 stage / 空 stage = 不裁剪（保守全量，探测失败不失约束）。
STAGE_STATE_FOCUS: Dict[str, Tuple[str, ...]] = {
    "analysis": (),
    "structure": (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS),
    "ke_media": (CAT_KEY_ELEMENTS,),
    "shot_media": (CAT_SHOTS,),
    "audio_assets": (CAT_AUDIO_ITEMS,),
    "assembly": (CAT_SHOTS,),
}
_ALL_GROUP_CATS = (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS)


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
    stage: str = "",
    scope: Optional[Dict[str, Any]] = None,
) -> str:
    """构建发送给 LLM 的 Studio 状态上下文。

    Args:
        raw_state: StateManager 内部的 raw dict
        asset_mode: "bound" 仅已绑定资产 / "all" 全部
        cache: 可选缓存字典（状态变更时由 StateManager 清空）
        degraded: 降级模式（预算保险丝用）——草稿细节不注入，
                  只留组标题/编号/草稿计数，大幅压缩状态上下文体积
        stage: 当前创作阶段键（分阶段注入裁剪用；空 = 不裁剪）
        scope: 微调作用域（微调真子对话，policy-as-data 同 STAGE_STATE_FOCUS）：
               仅目标分组/目标卡注入全量草稿细节（含提示词全文），其余分组/
               类别/文档/素材清单一律不注入（对齐 Flova：子对话只看对应元素）；
               空 = 不裁剪（旧行为零变化）

    Returns:
        JSON 字符串
    """
    if degraded:
        cache_key = f"{asset_mode}:degraded"
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        result = _dumps(_build_degraded_snapshot(raw_state))
        if cache is not None:
            cache[cache_key] = result
        return result

    # 缓存键不含 tier：档位对状态确定（状态变更即清缓存），同键读写保命中复用；
    # scope 经确定性序列化进键（同 scope 保命中，不同目标不互串）
    scope_key = _scope_cache_key(scope)
    cache_key = f"{asset_mode}:{stage or '-'}:{scope_key}"
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    snapshot = _build_snapshot_dict(raw_state, asset_mode)
    # 微调作用域裁剪（优先于阶段裁剪：scope 任务不携 Skill，两者不同时生效）
    if scope_key != "-":
        _apply_scope_profile(snapshot, raw_state, scope or {})
    elif stage:
        # 分阶段注入：非焦点类别降为组级摘要（可恢复句柄：id/编号保留）
        _apply_stage_profile(snapshot, raw_state, stage)
    result = _dumps(snapshot)
    # 状态指针化（Q6）：超字符预算自动降 B 档——组级正文截断+指针，
    # 全文经 read_state_group 按需读回；预算 0 = 永远 A 档（回滚开关）
    budget = int(settings.state_context_budget_chars)
    if budget > 0 and len(result) > budget:
        _compact_snapshot(snapshot)
        result = _dumps(snapshot)
    if cache is not None:
        cache[cache_key] = result
    return result

def _build_snapshot_dict(raw_state: Dict[str, Any], asset_mode: str) -> Dict[str, Any]:
    """A 档完整状态快照 dict（序列化/档位裁剪在外层做）。

    媒体 URL 截断：只保留前 200 字符（足够定位，避免 base64/长 URL 撞爆上下文）。
    渐进式披露：草稿 prompt 全文不注入，只给字数；模型需要时调 read_draft 按需读取。
    """
    def _u(v: Any) -> str:
        return (str(v) if v else "")[:200]

    def _pc(d: Dict[str, Any]) -> int:
        return len(d.get("prompt", "") or "")

    assets = raw_state.get("assets", [])
    if asset_mode != "all":
        assets = [a for a in assets if a.get("isBound")]

    return {
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
        # 规格文档清单（渐进式披露）：仅名称/字数/前 200 字预览，
        # 全文不注入，模型开工前调 read_project_doc 按需读取。
        # P2-1 易变字段隔离：updated_at 每次落盘必变，内容未变时也会击穿
        # 提示词前缀字节稳定性（供应商 KV-cache 命中），故移出模型可见面；
        # 前端视图（build_frontend_view）仍随 raw state 携带，行为不变。
        "documents": [
            {
                "name": d.get("name", ""),
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
        # 交互阶段状态：让模型看到先前轮次是否停在「等待确认」暂停点，
        # 避免用户回复确认后模型感知不到进度、从头重复同一套操作
        "interaction": _build_interaction(raw_state),
        # 剧本分析摘要（script_analyze 产出）：一句话总结 + 关键要点，
        # 拆解/提示词阶段主模型必须看到，否则会凭空概括
        "analysis": _build_analysis(raw_state),
    }


def _group_pointers(raw_state: Dict[str, Any], cat_key: str) -> list:
    """组级摘要（可恢复句柄）：id/编号/标题/草稿计数，正文不外流；
    全文经 read_state_group 按需读回。"""
    return [
        {
            "id": g.get("id", ""),
            "index": gi + 1,
            "title": g.get("title", ""),
            "draft_count": len(g.get("drafts", []) or []),
        }
        for gi, g in enumerate(raw_state.get(cat_key, []) or [])
    ]


def _scope_cache_key(scope: Optional[Dict[str, Any]]) -> str:
    """scope 确定性序列化（缓存键用）：无/空/非法形态返回 '-'（不裁剪）。"""
    if not isinstance(scope, dict) or not scope:
        return "-"
    return json.dumps(scope, sort_keys=True, ensure_ascii=False)


def _full_scope_group(raw_group: Dict[str, Any], gi: int) -> Dict[str, Any]:
    """微调目标分组全量注入（渐进披露豁免）：草稿提示词全文在场，
    模型无需再经 read_draft 往返；媒体 URL 仍截断防撞爆上下文。"""
    def _u(v: Any) -> str:
        return (str(v) if v else "")[:200]

    drafts = []
    for di, d in enumerate(raw_group.get("drafts", []) or []):
        if not isinstance(d, dict):
            continue
        entry: Dict[str, Any] = {
            k: d.get(k, "") for k in (
                "label", "tag", "mediaType", "model", "mode", "aspectRatio")
            if d.get(k, "") != ""
        }
        entry.update({
            "id": d.get("id", ""),
            "index": f"{gi + 1}-{di + 1}",
            "prompt": str(d.get("prompt", "") or ""),
            "imgUrl": _u(d.get("imgUrl", "")),
            "videoUrl": _u(d.get("videoUrl", "")),
            "audioUrl": _u(d.get("audioUrl", "")),
        })
        drafts.append(entry)
    group: Dict[str, Any] = {
        k: raw_group.get(k, "") for k in (
            "title", "desc", "duration", "shotType", "roughDesc", "timeRange")
        if raw_group.get(k, "") != ""
    }
    group.update({
        "id": raw_group.get("id", ""),
        "index": gi + 1,
        "sceneRefs": raw_group.get("sceneRefs", []) or [],
        "drafts": drafts,
    })
    return group


def _apply_scope_profile(
    snapshot: Dict[str, Any], raw_state: Dict[str, Any], scope: Dict[str, Any],
) -> bool:
    """微调作用域裁剪（微调真子对话，对齐 Flova：子对话只应看到对应元素）：
    仅目标分组（按 scope.group_id / draft_id 定位）注入全量草稿细节；
    同类别其余分组与其他类别整体不注入（连指针清单也不给，防越界读改）；
    documents（规格/剧本）/uploadedDocs/assets/剧本分析/交互状态同样不注入。
    目标缺失（组已删除）回落该类别空注入，不阻断任务。"""
    cat = str(scope.get("cat") or "")
    group_id = str(scope.get("group_id") or "")
    draft_id = str(scope.get("draft_id") or "")
    trimmed = False
    for c in _ALL_GROUP_CATS:
        groups = raw_state.get(c, []) or []
        if c == cat:
            out = []
            for gi, g in enumerate(groups):
                if not isinstance(g, dict):
                    continue
                is_target = bool(group_id) and g.get("id") == group_id
                if not is_target and draft_id:
                    is_target = any(
                        isinstance(d, dict) and d.get("id") == draft_id
                        for d in (g.get("drafts") or []))
                if is_target:
                    out.append(_full_scope_group(g, gi))
            snapshot[c] = out
            trimmed = True
        else:
            snapshot[c] = []
            trimmed = True
    # 非目标面整体移除（连指针清单也不给）：规格/剧本清单、上传附件、
    # 绑定素材、剧本分析摘要、主对话交互状态均不属于子对话视野；
    # 铁律段不受影响（宪法级，走 system prompt 段，体量小）
    for k in ("documents", "uploadedDocs", "assets", "analysis", "interaction"):
        if k in snapshot:
            snapshot.pop(k)
            trimmed = True
    if trimmed:
        snapshot["scopeNote"] = (
            "微调作用域：仅目标分组/目标卡注入了全量细节（含提示词全文）；"
            "其余分组、剧本、规格文档、上传素材等一律未注入，"
            "不得读取或修改非目标内容"
        )
    return trimmed


def _apply_stage_profile(
    snapshot: Dict[str, Any], raw_state: Dict[str, Any], stage: str,
) -> bool:
    """分阶段注入：非焦点类别降为组级摘要。返回是否发生裁剪。
    不在策略表内的 stage 不裁剪（保守全量）。"""
    focus = STAGE_STATE_FOCUS.get(stage)
    if focus is None:
        return False
    trimmed = False
    for cat in _ALL_GROUP_CATS:
        if cat not in focus:
            snapshot[cat] = _group_pointers(raw_state, cat)
            trimmed = True
    if trimmed:
        snapshot["stageNote"] = (
            f"当前阶段={stage}：非焦点类别仅注入组级摘要，"
            "全文调 read_state_group 按需读回"
        )
    return trimmed


def _compact_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """B 档压缩（原地）：组级正文截断 + 资产 URL 收窄 + 指针 note。
    句柄保留：id/编号/标题/字数不丢，全文经 read_state_group/read_draft 读回。"""
    body_chars = max(0, int(settings.state_group_body_chars))

    def _trunc(v: Any) -> str:
        s = str(v or "")
        return s if len(s) <= body_chars else s[:body_chars] + "…"

    for cat in _ALL_GROUP_CATS:
        for g in snapshot.get(cat) or []:
            if not isinstance(g, dict):
                continue
            if "desc" in g:
                g["desc"] = _trunc(g["desc"])
            if "roughDesc" in g:
                g["roughDesc"] = _trunc(g["roughDesc"])
    for a in snapshot.get("assets") or []:
        if isinstance(a, dict):
            a["url"] = (str(a.get("url") or ""))[:80]
    snapshot["note"] = (
        "状态正文已截断（超注入预算）：分组全文调 read_state_group、"
        "草稿提示词全文调 read_draft 按需读回"
    )
    return snapshot


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
    污染内部状态。
    快照仅在聊天完成路径低频调用，序列化开销可接受。
    """
    snap = json.loads(json.dumps(raw_state, ensure_ascii=False))
    # 乐观锁版本号随快照下发（不写入状态 JSON 本体，避免污染 undo/快照）
    snap["board_version"] = board_version
    # 消息单一来源：快照中对话只留元信息，消息副本不再随快照下发
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
    """降级快照：只保留组标题/编号/草稿计数（预算保险丝的第二道防线）。
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
