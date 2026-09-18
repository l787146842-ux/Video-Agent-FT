"""
故事板领域操作层 — 动作语义的唯一实现（Rule2 统一双轨）。

FC Tool（tools/storyboard_tools.py）与动作执行器（core/action_executor.py）
双双委托本模块的纯函数操作 state_dict，两轨只保留各自的「解析层」差异：
- FC 轨：pydantic 参数校验（Tool Input Schema）
- 文本轨：action dict 的字段别名归一化（draft_id/target_id/id 等）

职责边界：本模块不加锁（调用方持 svc.lock）、不持久化（调用方 save/save_debounced）、
不做 undo 快照（调用方 push_undo）。所有函数直接就地修改传入的 state_dict 结构。
"""
import json
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

# draft patch 允许写入的字段全集（双轨统一，含 imageResolution / genType / desc）
ALLOWED_DRAFT_FIELDS = (
    "label", "tag", "mediaType", "genType", "imgUrl", "videoUrl", "audioUrl", "prompt", "mode",
    "model", "providerId", "resolution", "duration", "aspectRatio", "imageResolution",
    "size", "timbre", "refAssets", "desc",
)

# 新建草稿（storyboard_add_draft / storyboard_create_group 附带）允许的字段：
# = patch 白名单 + id（新建时可显式指定 ID；patch 通道改 id 无意义仍拒收）
ALLOWED_NEW_DRAFT_FIELDS = ALLOWED_DRAFT_FIELDS + ("id",)

# group patch 允许写入的字段全集（shotType 已摘除：分镜镜头语言唯一载体 = desc；
# roughDesc 同批退役写口 2026-09-15：双通道歧义致分镜正文落盲区，
# 存量数据只读保留；badgeLabel 同批退役写口 2026-09-17：用户裁决类别标识
# 全链删除，存量数据只读透传）
ALLOWED_GROUP_FIELDS = (
    "title", "desc", "duration", "timeRange", "prompt", "sceneRefs", "summary",
)


def dedup_scene_refs(refs: Any) -> List[str]:
    """flova 对齐批（2026-09-17）：sceneRefs canonical 去重——同一元素的裸名与
    Element_ 前缀形态算同一引用（去重键 = strip_type_prefix），去重保序留首；
    杜绝 K4 三源合并产同元素双份（场景 chips 行重复 chip）。纯函数，不改状态。"""
    out: List[str] = []
    seen: set = set()
    for ref in refs or []:
        if not isinstance(ref, str):
            continue
        k = strip_type_prefix(ref)
        if k in seen:
            continue
        seen.add(k)
        out.append(ref)
    return out

# ---------- 分组标题容器 ID 约定（2026-09-17 裁决：对齐 flova，纯结构性） ----------
# 组标题 = 类型前缀 + 名字：前缀由平台按组类型幂等补全（flova 容器 ID 约定），
# 名字部分 = 模型原文照搬——平台不剥不清洗不翻译任何旧前缀（无词表映射）；
# 显示层只剥三个结构性类型前缀、其余原样（前端 desc-ref-utils 同契约镜像）。

# 容器 ID 约定类型前缀（前端 GROUP_TITLE_PREFIX 同契约镜像）
_GROUP_TITLE_PREFIX = {
    CAT_KEY_ELEMENTS: "Element_",
    CAT_SHOTS: "Shot_",
    CAT_AUDIO_ITEMS: "Audio_",
}


def strip_type_prefix(title: str) -> str:
    """剥容器类型前缀取名字（显示/引用匹配共用；只认三个结构性前缀）。"""
    t = str(title or "").strip()
    for prefix in _GROUP_TITLE_PREFIX.values():
        if t.startswith(prefix):
            return t[len(prefix):]
    return t


def normalize_group_title(title: str, cat_key: str = "") -> str:
    """分组标题确定性归一（写口）：幂等补容器类型前缀，名字原样保留。"""
    t = str(title or "").strip()
    prefix = _GROUP_TITLE_PREFIX.get(cat_key, "")
    if not prefix or not t or t.startswith(prefix):
        return t
    return prefix + t


# ---------- 关键元素角标（2026-09-17 用户裁决全链退役） ----------
# badgeLabel 推导（_BADGE_ANCHORS 锚点表 + normalize_badge_label）随类别标识
# 删除裁决退役：建组/patch 写口关闭，前端不显示不编辑；存量数据只读透传。

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
    if t in ("shot", CAT_SHOTS, "video"):
        return [CAT_SHOTS] if strict else [CAT_SHOTS, CAT_KEY_ELEMENTS, CAT_AUDIO_ITEMS]
    if t in ("audio", "audioitem"):
        return [CAT_AUDIO_ITEMS] if strict else [CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS]
    if t in ("keyelement", "key-element", "element", "image"):
        return [CAT_KEY_ELEMENTS] if strict else [CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS]
    return [] if strict else list(ALL_CATEGORIES)


def category_for_group_type(group_type: str) -> str:
    """新建分组的类型映射（含中文别名，缺省归 keyElements）"""
    t = (group_type or "").lower().strip()
    if t in ("shot", CAT_SHOTS, "video", "分镜"):
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


def dropped_patch_fields(patch: Dict[str, Any], allowed: Tuple[str, ...]) -> List[str]:
    """白名单差集：返回 patch 中不在允许集内的字段名（排序，确定性输出）。
    名单唯一事实源 = ALLOWED_DRAFT_FIELDS/ALLOWED_GROUP_FIELDS，只引用不复制（P1）。"""
    return sorted(set(patch or {}) - set(allowed))


def patch_draft(draft: Dict[str, Any], patch: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """按 ALLOWED_DRAFT_FIELDS 白名单就地更新 draft，返回 (是否有字段被修改, 被丢弃字段名列表)。
    被丢弃字段透出给调用方（T2 第一步「错误可见」），由调用方决定拒收/告警口径。

    确认状态闭环：提示词被重写（值变化且非空）时，「已确认」标记作废
    （tag 重置为 Agent）——用户提修改 → 模型重写 → 需重新经用户确认，
    避免旧确认被静默继承到新版本提示词。
    """
    dropped = dropped_patch_fields(patch, ALLOWED_DRAFT_FIELDS)
    new_prompt = patch.get("prompt")
    prompt_changed = (
        "prompt" in patch
        and str(new_prompt or "").strip()
        and str(new_prompt or "") != str(draft.get("prompt") or "")
    )
    changed = False
    for field in ALLOWED_DRAFT_FIELDS:
        if field in patch:
            draft[field] = patch[field]
            changed = True
    if prompt_changed and "tag" not in patch and draft.get("tag") == "已确认":
        draft["tag"] = "Agent"
    return changed, dropped


def patch_group(group: Dict[str, Any], patch: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """按 ALLOWED_GROUP_FIELDS 白名单就地更新 group，返回 (是否有字段被修改, 被丢弃字段名列表)。"""
    dropped = dropped_patch_fields(patch, ALLOWED_GROUP_FIELDS)
    changed = False
    for field in ALLOWED_GROUP_FIELDS:
        if field in patch:
            # sceneRefs 写口同口径 canonical 去重（与 create_group 三源合并一致）
            group[field] = dedup_scene_refs(patch[field]) if field == "sceneRefs" else patch[field]
            changed = True
    return changed, dropped


def sync_shot_duration(group: Dict[str, Any], draft: Dict[str, Any], patch: Optional[Dict[str, Any]] = None) -> bool:
    """时长参数同步（分镜专用）：草稿的生视频时长参数必须与分镜结构时长一致。

    客观兜底（不依赖模型自觉）：本次 patch 未带 duration 且草稿时长仍为
    空/默认 5s 时，用分组 duration 补印，确保生成参数里的时长就是分镜时长；
    用户手动设过的非默认值不覆盖。返回是否发生补印。
    """
    if (patch or {}).get("duration"):
        return False
    gd = str((group or {}).get("duration") or "").strip()
    if not gd:
        return False
    dd = str((draft or {}).get("duration") or "").strip()
    if dd and dd != "5s":
        return False
    draft["duration"] = gd
    return True


def delete_draft(state: Dict[str, Any], draft_id: str, draft_type: str = "") -> List[str]:
    """按真实 ID 删除 draft（调用方负责把 "current" 解析为具体 ID）。
    返回被删草稿 id 列表（空 = 未命中），供调用方做 scope 线程删除级联。"""
    if not draft_id:
        return []
    for cat_key in categories_for_type(draft_type):
        for group in state.get(cat_key, []):
            drafts = group.get("drafts", [])
            for i, d in enumerate(drafts):
                if d.get("id") == draft_id:
                    drafts.pop(i)
                    return [draft_id]
    return []


def delete_group(
    state: Dict[str, Any], group_id: str, group_type: str = "",
) -> Tuple[List[str], bool]:
    """按真实 ID 删除 group（含其全部草稿）。先展开该分组全部草稿 id 再删，
    返回（被删草稿 id 列表，是否命中），供调用方做 scope 线程删除级联。
    命中位与草稿列表分离（评审修补批）：空分组命中时草稿列表为空，
    调用方凭命中位落盘报成功，不得误报 not found。"""
    if not group_id:
        return [], False
    for cat_key in categories_for_type(group_type):
        groups = state.get(cat_key, [])
        for i, g in enumerate(groups):
            if g.get("id") == group_id:
                removed = [
                    str(d.get("id")) for d in (g.get("drafts") or [])
                    if isinstance(d, dict) and str(d.get("id") or "")
                ]
                groups.pop(i)
                return removed, True
    return [], False


def new_group_id(cat_key: str) -> str:
    """按类别生成 group ID（保持既有前缀约定：shot/ke/audio）"""
    prefix = "shot" if cat_key == CAT_SHOTS else "ke" if cat_key == CAT_KEY_ELEMENTS else "audio"
    return gen_id(prefix)


def append_draft(group: Dict[str, Any], draft_data: Dict[str, Any]) -> Dict[str, Any]:
    """向指定 group 添加一个 draft，返回新建的 draft"""
    draft = build_draft_dict(draft_data)
    group.setdefault("drafts", []).append(draft)
    return draft


def draft_id_exists(
    state: Dict[str, Any], draft_id: str,
    categories: Optional[Tuple[str, ...]] = None,
) -> bool:
    """批 3 · B6：显式 draft id 是否已存在（写入前查重，防重复卡假成功）。

    categories 缺省查全部故事板类别——「镜头 ID 重复」即拒（外部实测转录
    标尺：失败时现有故事板零改动）。只读，不写任何状态。"""
    wanted = str(draft_id or "").strip()
    if not wanted:
        return False
    for cat_key in (categories or ALL_CATEGORIES):
        for group in state.get(cat_key, []) or []:
            for d in (group.get("drafts") or []):
                if isinstance(d, dict) and str(d.get("id") or "") == wanted:
                    return True
    return False


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


def resolve_scene_refs(
    state: Dict[str, Any], group: Optional[Dict[str, Any]], limit: int = 5,
) -> List[Dict[str, str]]:
    """解析分镜的 sceneRefs → 对应关键元素的概念图 URL 作为参考图（默认最多 5 张）"""
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
            # sceneRefs 兼容关键元素 ID（ke-xxx）与标题两种写法
            if str(ke_group.get("id") or "") != ref_title and str(ke_group.get("title") or "") != ref_title:
                continue
            for d in ke_group.get("drafts", []):
                img = d.get("imgUrl") or ""
                if img:
                    refs.append({"url": img, "role": "reference"})
                    break
            break
    return refs[:limit]


def resolve_scene_audio_refs(
    state: Dict[str, Any], group: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """批 6 · A3：按分镜组 sceneRefs 收集关键元素卡的 audioUrl（音色锚点）。

    与 resolve_scene_refs 同构（imgUrl→reference 的姊妹轴）：分镜引用了
    带音色参考的元素时，视频生成自动把该音色挂为 reference_audio，
    对齐外部标杆「按引用自动挂声音锚点」。只读，不改状态。"""
    refs: List[Dict[str, str]] = []
    if not group:
        return refs
    for ref_title in group.get("sceneRefs") or []:
        if not isinstance(ref_title, str):
            continue
        for ke_group in state.get(CAT_KEY_ELEMENTS, []):
            if str(ke_group.get("id") or "") != ref_title and str(ke_group.get("title") or "") != ref_title:
                continue
            for d in ke_group.get("drafts", []):
                audio = str(d.get("audioUrl") or "")
                if audio:
                    refs.append({"url": audio, "role": "reference_audio"})
                    break
            break
    return refs


def parse_element_tokens(text: str) -> List[str]:
    """批 6 · A3：提取文本中的 [元素名] 令牌（外部标杆 形态），去重保序。

    令牌是写在分镜描述里的人可读引用层；匹配不到元素的令牌由调用方
    丢弃（不拒收，不锁死）。"""
    tokens: List[str] = []
    for raw in re.findall(r"\[([^\[\]]{1,60})\]", str(text or "")):
        token = raw.strip()
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def scan_bare_name_mentions(
    desc: str, key_elements: List[Dict[str, Any]],
) -> List[str]:
    """K4 批（2026-09-16 对齐 flova）：裸名提及自动绑定——分镜正文里
    提到元素名（原全称/归一裸名）即自动挂引用（提及即绑定）。

    镜像前端 desc-ref-utils.ts descChipNames 语义：候选源 = keyElements
    全集（原全称 + 归一裸名两形态，Set 去重、≥2 字符守卫、最长优先防重叠）；
    命中规则 = 候选名在 desc 子串出现；返回 = 命中的关键元素组标题
    （sceneRefs 存储口径，去重保序）。纯函数，不改状态。"""
    text = str(desc or "")
    if not text:
        return []
    candidates: List[Tuple[str, str]] = []
    seen: set = set()
    for ke in key_elements or []:
        if not isinstance(ke, dict):
            continue
        title = str(ke.get("title") or "").strip()
        if not title:
            continue
        bare = strip_type_prefix(title)
        for cand in (title, bare):
            if len(cand) >= 2 and cand not in seen:
                seen.add(cand)
                candidates.append((cand, title))
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
    hits: List[str] = []
    for cand, title in candidates:
        if cand in text and title not in hits:
            hits.append(title)
    return hits


def match_element_titles_report(
    state: Dict[str, Any], tokens: List[str],
) -> Tuple[List[str], List[str]]:
    """把 [元素名] 令牌匹配到既有关键元素组标题，返回 (匹配标题, 未匹配令牌)。

    匹配规则：精确 → 双向包含。未匹配令牌由调用方决定处置（建组通道
    丢弃不拒收——令牌是引导不是闸；但必须回喂告知模型，防「以为挂上了」）。"""
    titles = [
        str(g.get("title") or "").strip()
        for g in (state.get(CAT_KEY_ELEMENTS, []) or []) if isinstance(g, dict)
    ]
    titles = [t for t in titles if t]
    matched: List[str] = []
    unmatched: List[str] = []
    for token in tokens or []:
        token = str(token or "").strip()
        if not token:
            continue
        hit = next((t for t in titles if t == token), None)
        if hit is None:
            hit = next((t for t in titles if token in t or t in token), None)
        if hit:
            if hit not in matched:
                matched.append(hit)
        else:
            unmatched.append(token)
    return matched, unmatched


def match_element_titles(state: Dict[str, Any], tokens: List[str]) -> List[str]:
    """把 [元素名] 令牌匹配到既有关键元素组标题（精确→双向包含）。

    匹配不到的令牌静默丢弃（不拒收不锁死——令牌是引导不是闸）。"""
    matched, _unmatched = match_element_titles_report(state, tokens)
    return matched


def coerce_draft_payload(data: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """批 6 · A3：draft 入参宽容解析。

    8888 实证模型高频把 draft 传成 JSON 字符串（该交对象交了字符串），
    pydantic 直接拒收导致连败放弃。收到 str 时 json.loads 宽容拆包一次；
    拆不了返回 (None, 三要素报错) 由调用方原子拒收。"""
    if isinstance(data, dict):
        return data, ""
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return None, ""
        try:
            parsed = json.loads(text)
        except Exception:
            return None, (
                "Validation Error: draft 传入了字符串，且内容不是合法 JSON。"
                "本次调用已拒收、未写入任何字段，现有故事板与全部草稿保持原样。"
                "请把 draft 作为 JSON 对象（而非字符串）重新提交。")
        if isinstance(parsed, dict):
            return parsed, ""
        return None, (
            "Validation Error: draft 反序列化后不是 JSON 对象。"
            "本次调用已拒收、未写入任何字段，现有故事板与全部草稿保持原样。"
            "请把 draft 作为 JSON 对象（而非字符串或数组）重新提交。")
    if data is None:
        return None, ""
    return None, (
        "Validation Error: draft 必须是 JSON 对象。"
        "本次调用已拒收、未写入任何字段，现有故事板与全部草稿保持原样。"
        "请把 draft 作为 JSON 对象重新提交。")


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
