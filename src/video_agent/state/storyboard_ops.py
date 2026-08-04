"""
故事板领域操作层 — 动作语义的唯一实现（Rule2 统一双轨）。

FC Tool（tools/storyboard_tools.py）与文本解析 executor（web/action_executor.py）
双双委托本模块的纯函数操作 state_dict，两轨只保留各自的「解析层」差异：
- FC 轨：pydantic 参数校验（Tool Input Schema）
- 文本轨：action dict 的字段别名归一化（draft_id/target_id/id 等）

职责边界：本模块不加锁（调用方持 svc.lock）、不持久化（调用方 save/save_debounced）、
不做 undo 快照（调用方 push_undo）。所有函数直接就地修改传入的 state_dict 结构。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from src.video_agent.state.models import (
    ALL_CATEGORIES,
    CAT_AUDIO_ITEMS,
    CAT_KEY_ELEMENTS,
    CAT_SHOTS,
    build_draft_dict,
)
from src.video_agent.utils import gen_id

# draft patch 允许写入的字段全集（双轨统一，含 imageResolution / genType）
ALLOWED_DRAFT_FIELDS = (
    "label", "tag", "mediaType", "genType", "imgUrl", "videoUrl", "audioUrl", "prompt", "mode",
    "model", "providerId", "resolution", "duration", "aspectRatio", "imageResolution",
    "size", "timbre", "refAssets",
)

# group patch 允许写入的字段全集
ALLOWED_GROUP_FIELDS = (
    "title", "desc", "roughDesc", "duration", "timeRange", "prompt", "shotType", "sceneRefs",
)

# 卡片小标编号：组号-卡序号（如 "1-2"，与前端卡片下方小标/上下文 index 一致）
INDEX_REF_RE = re.compile(r"^(\d+)\s*[-－.·]\s*(\d+)$")

# selected_type（前端 DraftType）→ 快照类别键
SELECTED_TYPE_TO_CAT = {
    "keyElement": CAT_KEY_ELEMENTS,
    "shot": CAT_SHOTS,
    "audio": CAT_AUDIO_ITEMS,
}


def categories_for_type(draft_type: str, strict: bool = False) -> List[str]:
    """draft_type → 状态类别键。

    strict=True（批量收集路径）：严格单类别，杜绝 all_keyElements
    批量生图时级联兜底把音频草稿也拉去生图；
    strict=False（查找/删除路径）：保留类型缺失时的全类别兜底，
    保证 LLM 未传类型时 find/delete 仍可用。
    """
    t = (draft_type or "").lower().strip()
    if t in ("shot", "shots", "video"):
        return [CAT_SHOTS] if strict else [CAT_SHOTS, CAT_KEY_ELEMENTS, CAT_AUDIO_ITEMS]
    if t in ("audio", "audioitem"):
        return [CAT_AUDIO_ITEMS] if strict else [CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS]
    if t in ("keyelement", "key-element", "element", "image"):
        return [CAT_KEY_ELEMENTS] if strict else [CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS]
    return [] if strict else list(ALL_CATEGORIES)


def category_for_group_type(group_type: str) -> str:
    """新建分组的类型映射（含中文别名，缺省归 keyElements）"""
    t = (group_type or "").lower().strip()
    if t in ("shot", "shots", "video", "分镜"):
        return CAT_SHOTS
    if t in ("audio", "audioitem", "audioitems", "音频"):
        return CAT_AUDIO_ITEMS
    return CAT_KEY_ELEMENTS


def resolve_index_ref(
    state: Dict[str, Any], ref: str, draft_type: str = ""
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """解析卡片编号（如 "1-2" = 第 1 组第 2 张卡）→ (group, draft)；
    编号按类别（关键元素/分镜/音频）各自从 1 开始，与前端小标一致。"""
    m = INDEX_REF_RE.match((ref or "").strip())
    if not m:
        return None
    gi, di = int(m.group(1)) - 1, int(m.group(2)) - 1
    if gi < 0 or di < 0:
        return None
    for cat_key in categories_for_type(draft_type):
        groups = state.get(cat_key, [])
        if gi < len(groups):
            drafts = groups[gi].get("drafts", [])
            if di < len(drafts):
                return groups[gi], drafts[di]
    return None


def find_draft(
    state: Dict[str, Any],
    draft_id: str,
    draft_type: str = "",
    selected_draft_id: str = "",
    selected_type: str = "",
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """在 state 中查找 draft，返回 (group, draft) 或 None。
    draft_id 支持真实 ID、"current" 或卡片编号（如 "1-2"）。"""
    # 卡片编号定位（与前端卡片下方小标一致）
    idx_ref = resolve_index_ref(state, draft_id, draft_type)
    if idx_ref:
        return idx_ref
    categories = categories_for_type(draft_type)
    for cat_key in categories:
        for group in state.get(cat_key, []):
            for draft in group.get("drafts", []):
                if draft.get("id") == draft_id:
                    return group, draft
    if draft_id in ("current", ""):
        # 优先解析为前端当前选中的草稿
        if selected_draft_id:
            found = find_draft(state, selected_draft_id, selected_type or draft_type)
            if found:
                return found
        # 兜底：第一个可用的 draft
        for cat_key in categories:
            for group in state.get(cat_key, []):
                drafts = group.get("drafts", [])
                if drafts:
                    return group, drafts[0]
    return None


def find_group(
    state: Dict[str, Any],
    group_id: str,
    group_type: str = "",
    selected_draft_id: str = "",
    selected_type: str = "",
) -> Optional[Dict[str, Any]]:
    """在 state 中查找 group；"current" 优先解析为包含选中草稿的分组。"""
    categories = categories_for_type(group_type)
    for cat_key in categories:
        for group in state.get(cat_key, []):
            if group.get("id") == group_id:
                return group
    if group_id in ("current", ""):
        if selected_draft_id:
            found = find_draft(state, selected_draft_id, selected_type or group_type)
            if found:
                return found[0]
        for cat_key in categories:
            groups = state.get(cat_key, [])
            if groups:
                return groups[0]
    return None


def patch_draft(draft: Dict[str, Any], patch: Dict[str, Any]) -> bool:
    """按 ALLOWED_DRAFT_FIELDS 白名单就地更新 draft，返回是否有字段被修改。"""
    changed = False
    for field in ALLOWED_DRAFT_FIELDS:
        if field in patch:
            draft[field] = patch[field]
            changed = True
    return changed


def patch_group(group: Dict[str, Any], patch: Dict[str, Any]) -> bool:
    """按 ALLOWED_GROUP_FIELDS 白名单就地更新 group，返回是否有字段被修改。"""
    changed = False
    for field in ALLOWED_GROUP_FIELDS:
        if field in patch:
            group[field] = patch[field]
            changed = True
    return changed


def delete_draft(state: Dict[str, Any], draft_id: str, draft_type: str = "") -> bool:
    """按真实 ID 删除 draft（调用方负责把 "current" 解析为具体 ID）。"""
    if not draft_id:
        return False
    for cat_key in categories_for_type(draft_type):
        for group in state.get(cat_key, []):
            drafts = group.get("drafts", [])
            for i, d in enumerate(drafts):
                if d.get("id") == draft_id:
                    drafts.pop(i)
                    return True
    return False


def delete_group(state: Dict[str, Any], group_id: str, group_type: str = "") -> bool:
    """按真实 ID 删除 group（含其全部草稿）。"""
    if not group_id:
        return False
    for cat_key in categories_for_type(group_type):
        groups = state.get(cat_key, [])
        for i, g in enumerate(groups):
            if g.get("id") == group_id:
                groups.pop(i)
                return True
    return False


def new_group_id(cat_key: str) -> str:
    """按类别生成 group ID（保持既有前缀约定：shot/ke/audio）"""
    prefix = "shot" if cat_key == CAT_SHOTS else "ke" if cat_key == CAT_KEY_ELEMENTS else "audio"
    return gen_id(prefix)


def append_draft(group: Dict[str, Any], draft_data: Dict[str, Any]) -> Dict[str, Any]:
    """向指定 group 添加一个 draft，返回新建的 draft"""
    draft = build_draft_dict(draft_data)
    group.setdefault("drafts", []).append(draft)
    return draft


def clear_draft_media(draft: Dict[str, Any]) -> bool:
    """清空卡片内的媒体内容（图片/视频/音频地址），保留提示词与参数。"""
    changed = False
    for field in ("imgUrl", "videoUrl", "audioUrl"):
        if draft.get(field):
            draft[field] = ""
            changed = True
    return changed


def collect_drafts(
    state: Dict[str, Any], target: str, draft_type: str
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """收集目标 (group, draft) 对。target='all' 时按类型严格遍历（不跨类别）。"""
    categories = categories_for_type(draft_type, strict=True)
    results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    if target == "all":
        for cat_key in categories:
            for group in state.get(cat_key, []):
                for draft in group.get("drafts", []):
                    results.append((group, draft))
        return results

    # 具体 draft_id：先按卡片编号解析，再按类型类别找，找不到再跨全部类别兜底
    # （仅限具体 ID，不影响 all 批量路径的严格类型约束）
    idx_ref = resolve_index_ref(state, target, draft_type)
    if idx_ref:
        return [idx_ref]
    cats = categories or list(ALL_CATEGORIES)
    for cat_key in cats:
        for group in state.get(cat_key, []):
            for draft in group.get("drafts", []):
                if draft.get("id") == target:
                    return [(group, draft)]
    return []


def resolve_scene_refs(state: Dict[str, Any], group: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """解析分镜的 sceneRefs → 对应关键元素的概念图 URL 作为参考图（最多 5 张）"""
    refs: List[Dict[str, str]] = []
    if not group:
        return refs
    scene_refs = group.get("sceneRefs") or []
    if not scene_refs:
        return refs
    for ref_title in scene_refs:
        if not isinstance(ref_title, str):
            continue
        for ke_group in state.get(CAT_KEY_ELEMENTS, []):
            if ke_group.get("title") == ref_title:
                for d in ke_group.get("drafts", []):
                    img = d.get("imgUrl") or ""
                    if img:
                        refs.append({"url": img, "role": "reference"})
                        break
                break
    return refs[:5]


def selected_draft_media_config(
    state: Dict[str, Any], selected_draft_id: str, selected_type: str
) -> Tuple[str, str, str]:
    """解析中间预览面板选中草稿的 (providerId, aspectRatio, imageResolution)，作为生图缺省配置。"""
    cat = SELECTED_TYPE_TO_CAT.get(selected_type, selected_type)
    for group in state.get(cat, []):
        for draft in group.get("drafts", []):
            if draft.get("id") == selected_draft_id:
                return (
                    draft.get("providerId") or "",
                    draft.get("aspectRatio") or "",
                    draft.get("imageResolution") or "",
                )
    return "", "", ""


def find_draft_matches(
    state: Dict[str, Any], wanted: str, draft_type: str = ""
) -> List[Dict[str, Any]]:
    """read_draft 工具的匹配逻辑：支持真实 ID 与「组号-卡序号」编号，
    同编号在多类别重复时全部返回，由模型确认具体目标。"""
    wanted = (wanted or "").strip()
    dtype = (draft_type or "").strip().lower()
    by_type = {
        "keyelement": CAT_KEY_ELEMENTS,
        "shot": CAT_SHOTS,
        "audio": CAT_AUDIO_ITEMS,
    }
    cats = (by_type[dtype],) if dtype in by_type else tuple(ALL_CATEGORIES)

    matches: List[Dict[str, Any]] = []
    for cat_key in cats:
        for gi, group in enumerate(state.get(cat_key, []) or []):
            for di, draft in enumerate(group.get("drafts", []) or []):
                if draft.get("id") == wanted or wanted == f"{gi + 1}-{di + 1}":
                    matches.append({
                        "category": cat_key,
                        "group_title": group.get("title", ""),
                        "group_desc": group.get("desc", "") or group.get("roughDesc", ""),
                        "draft_id": draft.get("id", ""),
                        "index": f"{gi + 1}-{di + 1}",
                        "label": draft.get("label", ""),
                        "tag": draft.get("tag", ""),
                        "model": draft.get("model", ""),
                        "prompt": draft.get("prompt", "") or "",
                    })
    return matches
