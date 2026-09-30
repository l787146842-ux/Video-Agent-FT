"""
故事板领域操作层 — 动作语义的唯一实现（Rule2 统一双轨）。

FC Tool（tools/storyboard_tools.py）与动作执行器（core/action_executor.py）
双双委托本模块的纯函数操作 state_dict，两轨只保留各自的「解析层」差异：
- FC 轨：pydantic 参数校验（Tool Input Schema）
- 文本轨：action dict 的字段别名归一化（draft_id/target_id/id 等）

职责边界：本模块不加锁（调用方持 svc.lock）、不持久化（调用方 save/save_debounced）、
不做 undo 快照（调用方 push_undo）。所有函数直接就地修改传入的 state_dict 结构。
"""
import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.state.models import (
    ALL_CATEGORIES,
    CAT_AUDIO_ITEMS,
    CAT_KEY_ELEMENTS,
    CAT_SHOTS,
    build_draft_dict,
    infer_media_type,
)
from src.video_agent.utils import gen_id

# ---------- 归属语义字段词表（2026-09-23 批5，用户 D-1/D-2/D-3 裁决） ----------
# 用户原话：「不能做模型识别到这个字段，自己就知道放在哪里么」——
# 病灶：平台**注释里写对了**归属（audio ← key_elements 的角色音色卡），
# 但可执行代码 0 命中、草稿白名单**没有** elementType/audioType，
# 模型**没有可用字段**表达「这是音色卡」；于是模型自发用 tag='BGM'/desc 表达，
# 而平台对 tag/timbre 的消费也是 0 命中。
# ⇒ 修法（D-2=schema 层 / D-3=给字段+正面契约，均不加硬判）：
#   把归属语义落成**模型可见的字段**，取值词表在此登记为单一事实源。
#
# elementType：关键元素组的元素种类（Skill：element character / element scene /
#   prop element）。属**分组**字段（元素种类是组的属性）。
ELEMENT_TYPES = ("character", "scene", "prop")

# audioType：音频卡的音频种类。`voice` = Skill 明文的 key_element_audio
#   （「角色的声音特征（音色/语气/情绪基调）单独登记为 key_element_audio，
#   与角色元素绑定」）；其余对齐 AudioCategory 并补叙事类。
#   属**草稿**字段（音频种类是卡的属性）。
AUDIO_TYPES = ("voice", "bgm", "narration", "sfx", "dialogue", "foley")

# ---------- 类目 × 能力矩阵（2026-09-23 批4，用户 D-2 裁决：落 schema 层） ----------
# 用户要求（逐字）：
#   「只有关键元素里面能出图、出视频、出音频，能放图、放视频、放音频；
#     分镜里面只能放视频、只能出视频；音频里面只能放音频、只能出音频。」
#
# 取证结论（报告 03 §Q7）：平台**不存在**这张矩阵——真实出处是前端
# `ParamControls.tsx` 散落的 if/Switch（隐式矩阵）+ 后端按**阶段**的单点黑名单；
# 两者维度不同（类目 vs 阶段）**不可互推**，且类目约束缺失已造成实跑混装
# （2222 keyElement 组内 3 张 audio 卡；3333 shot 组内 15 张 image 卡）。
#
# D-2 裁决 = **落 schema 层**；D-3 裁决 = **给字段+正面契约，不加硬判**。
# ⇒ 本表是矩阵的**单一事实源（数据）**，供字段描述/前端可见性消费；
#   **不新增拒收闸**（与 2026-09-08「不加机械闸」裁决一致）。
# 键 = 类目（group_type），值 = 该类的 6 项能力（放/出 × 图/视频/音频）。
CATEGORY_MEDIA_MATRIX: Dict[str, Dict[str, frozenset]] = {
    "keyElement": {
        "place": frozenset({"image", "video", "audio"}),
        "generate": frozenset({"image", "video", "audio"}),
    },
    "shot": {
        "place": frozenset({"video"}),
        "generate": frozenset({"video"}),
    },
    "audio": {
        "place": frozenset({"audio"}),
        "generate": frozenset({"audio"}),
    },
}


def matrix_media_for(group_type: str, capability: str) -> frozenset:
    """查矩阵：某类目在某能力（place=放 / generate=出）下允许的媒体类型。

    未知类目/能力返回空集（= 无声明，调用方按"不约束"处理）。
    纯查表，不做判定——判定策略由调用方裁决（D-3：不加硬判）。
    """
    return CATEGORY_MEDIA_MATRIX.get(
        str(group_type or ""), {}).get(str(capability or ""), frozenset())


def matrix_contract_line(group_type: str) -> str:
    """把矩阵一行渲染成模型可读的正面契约句（供 schema 描述消费）。

    措辞只陈述「该类目能做什么」（正面契约），不写禁令
    （description lint 拦禁令词；且 3333 实证说明层禁令会吓退模型）。
    """
    row = CATEGORY_MEDIA_MATRIX.get(str(group_type or ""))
    if not row:
        return ""
    _label = {"image": "图", "video": "视频", "audio": "音频"}
    place = "/".join(_label[m] for m in ("image", "video", "audio") if m in row["place"])
    gen = "/".join(_label[m] for m in ("image", "video", "audio") if m in row["generate"])
    return f"（该类目可放：{place}；可出：{gen}）"


# ---------- 章节 → 类目绑定（2026-09-23 批9 P-1，用户第四/五轮追问的正面回答） ----------
# 用户原问：「skill 里面这些章节字段到底有没有对应在本项目中，要搞清楚。」
# 全量审计（16 个 Skill）结论分三层（报告 07）：
#   ① 章节名 → 平台映射：✅ 全对应、零缺口（15 个 tag 全部被 SECTION_TAG_STAGES 认）；
#   ② 章节 → 能否注入：⚠️ 4 个发不出去（generation/assembly 不可委派）；
#   ③ **章节 → 字段/承载：❌ 真消费仅 2** —— 用户所指"对应不上"准确落在这层。
#
# 缺口机制：平台有三张映射表，**没有一张是「章节 → 类目」**：
#   CAPABILITY_TOOL_STAGES : 能力 → section 名
#   SECTION_TAG_STAGES     : 章节 tag → stage 名
#   category_for_group_type: 工具入参 group_type → 类目
# ⇒ 章节语义**止步于平台内部代号**，从未落到模型可见的字段上。
# 本表即那条缺失的中间一级（D-2 裁决：落 schema 层；不新增拒收闸）。
#
# 键 = section 名（registry.CAPABILITY_TOOL_STAGES 右值），值 = 故事板类目。
SECTION_CATEGORY_BINDING: Dict[str, str] = {
    "storyboard_ke": CAT_KEY_ELEMENTS,
    "storyboard_shot": CAT_SHOTS,
    "storyboard_audio": CAT_AUDIO_ITEMS,
}


def category_for_section(section: str) -> str:
    """章节 section 名 → 看板类目（空串 = 该章节无故事板承载）。

    消费端示例：委派 `storyboard_design` 时的三章节各自落到哪个类目、
    音色卡（`key_element_audio`）该挂哪个类目 —— 补齐「章节→类目」这一级。
    """
    return SECTION_CATEGORY_BINDING.get(str(section or "").strip(), "")


def sections_for_category(cat_key: str) -> List[str]:
    """类目 → 承载它的全部章节 section（反向查，供审计/契约渲染）。"""
    target = str(cat_key or "").strip()
    return [s for s, c in SECTION_CATEGORY_BINDING.items() if c == target]


# draft patch 允许写入的字段全集（双轨统一，含 imageResolution / genType / desc）
ALLOWED_DRAFT_FIELDS = (
    "label", "tag", "mediaType", "genType", "imgUrl", "videoUrl", "audioUrl", "prompt", "mode",
    "model", "providerId", "resolution", "duration", "aspectRatio", "imageResolution",
    "size", "timbre", "refAssets", "desc",
    # 2026-09-23 批5：音频归属语义（voice=角色音色卡 / bgm / narration / …）
    "audioType",
)

# 新建草稿（storyboard_add_draft / storyboard_create_group 附带）允许的字段：
# = patch 白名单 + id（新建时可显式指定 ID；patch 通道改 id 无意义仍拒收）
ALLOWED_NEW_DRAFT_FIELDS = ALLOWED_DRAFT_FIELDS + ("id",)

# group patch 允许写入的字段全集（shotType 已摘除：分镜镜头语言唯一载体 = desc；
# roughDesc 同批退役写口 2026-09-15：双通道歧义致分镜正文落盲区，
# 存量数据只读保留；badgeLabel 同批退役写口 2026-09-17：用户裁决类别标识
# 全链删除，存量数据只读透传）
ALLOWED_GROUP_FIELDS = (
    "title", "desc", "duration", "timeRange", "prompt", "shotRefs", "summary",
    # 2026-09-23 批5：关键元素组的元素种类（character / scene / prop）
    "elementType",
)


def dedup_shot_refs(refs: Any) -> List[str]:
    """flova 对齐批（2026-09-17）：shotRefs canonical 去重——同一元素的裸名与
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


# ---------- shotRefs canonical 引用键（读口，2026-09-23 批10，事故 4444/P0-A） ----------
# 病灶：**写口与读口口径漂移**。
#   - 写口 `dedup_shot_refs`（见上）以 `strip_type_prefix` 为去重键，
#     docstring 明写「同一元素的裸名与 Element_ 前缀形态算同一引用」；
#   - 读口 `resolve_shot_refs` / `resolve_shot_audio_refs` 却是**逐字精确比对**
#     （`id != ref and title != ref`），而落盘组标题带前缀（`Element_程心`）、
#     shotRefs 存裸名（`程心`）⇒ 恒不命中。
# 实跑取证（4444 / proj-1790159421-bfd25491，真实 state 复算）：
#   22 镜 90 条 shotRefs → image_refs **0**、audio_refs **0**；
#   改用 canonical 键复算 → **90/90 命中**。
# 同源失配在别处**已修过**：`core/prompt_refs.py` 批3 R3 判词「平台在别处
#   （scan_bare_name_mentions、前端 desc-ref-utils）早就做了裸名归一，
#   唯独本引用链漏了，属口径漂移而非设计」——本函数即把该判词落到引用链上。
# 为何是根因而非补丁：同一份 canonical 规则在**同一个文件里**已存在
#   （strip_type_prefix/dedup_shot_refs），本处只是让读口复用写口的口径，
#   未引入新规则、未新增拒收闸。


def canonical_ref_key(ref: Any) -> str:
    """shotRefs 引用键（canonical）：剥容器类型前缀 + 去首尾空白。

    与写口 `dedup_shot_refs` 的去重键、`prompt_refs.build_storyboard_media_map`
    的裸名别名**同一口径**（P1 单一事实源：本函数是引用匹配的唯一入口）。
    """
    return strip_type_prefix(str(ref or "").strip())


# ---------- 元素名括注别名（写口归一，2026-09-26） ----------
# 病灶：模型把别名/关键特征写进组名的**括注**里（`艾AA（AA）`、`曹彬（老年）`、
#    `星环号球形舱（木星轨道）`——模型建组入参原话如此，平台按
#    `normalize_group_title`「名字原样保留」落库），而正文/引用里写的是
#    **括注前的主名**（`艾AA`）。候选名此前只有「完整标题 + 剥容器前缀」两形态，
#    逐字子串比对 ⇒ 恒不命中：desc 内联图块不渲染、裸名绑定落空、闸机漏检。
#    无括注的组名（`程心`）一切正常——同一份代码，只在这一种命名形态上失配。
# 口径：括注是**注释**（别名/年龄态/所在轨道），主名才是引用锚点；
#    故为主名补登别名形态，与既有「最长优先防重叠」同向（主名最短、优先级最低）。

# 括注起始符（半角 + 全角），取**首个**括注之前的部分为主名。
_ALIAS_OPEN_RE = re.compile(r"[（(]")

# 引用匹配的最小候选长度（与前端 descChipNames 的 ≥2 字符守卫同口径）：
# 单字主名（如「A」）歧义过大，不产出别名形态。
_MIN_REF_NAME_LEN = 2


def element_alias_name(title: str) -> str:
    """元素标题的**括注主名**（别名形态）：取首个 `（`/`(` 之前的部分。

    返回空串 = **无括注**，或主名过短（< `_MIN_REF_NAME_LEN`）——
    两种情况都**不产出**别名候选（无括注时主名 == 剥前缀名，已由第二形态覆盖；
    单字主名歧义过大，宁缺毋滥）。
    """
    bare = strip_type_prefix(title)
    parts = _ALIAS_OPEN_RE.split(bare, 1)
    if len(parts) < 2:
        return ""  # 无括注：不产别名（避免与「剥前缀」形态重复）
    main = parts[0].strip()
    return main if len(main) >= _MIN_REF_NAME_LEN else ""


def element_name_variants(title: str) -> List[str]:
    """元素标题的**全部引用形态**（引用匹配候选名的唯一入口，去重保序）。

    形态（按长度降序由调用方负责，本函数只产全集）：
      ① 完整标题（`Element_艾AA（AA）`）——存量落库形态 / 组 id 语义；
      ② 剥容器前缀（`艾AA（AA）`）——模型提示词里的常见写法；
      ③ 括注主名（`艾AA`）——模型正文里的实际写法（本次修复补齐的形态）。

    消费方（**必须同引本函数**，各写一遍正是本次缺陷成因）：
      `build_ref_index`（读口 O(1) 命中）、`scan_bare_name_mentions`（裸名提及）、
      `fc_gates.structure_integrity_gate`（标题覆盖检查）、
      前端 `desc-ref-utils.ts`（desc 内联图块 / 编辑同步，同契约镜像）。
    """
    variants: List[str] = []
    full = str(title or "").strip()
    if full:
        variants.append(full)
    bare = strip_type_prefix(full)
    if bare and bare not in variants:
        variants.append(bare)
    alias = element_alias_name(full)
    if alias and alias not in variants:
        variants.append(alias)
    return variants


def build_ref_index(state: Dict[str, Any], cat_key: str) -> Dict[str, Dict[str, Any]]:
    """建「canonical 引用键 → 分组」索引（供引用解析 O(1) 命中）。

    同一 canonical 键出现多组时**保留先出现者**（与 `prompt_refs` 的
    「后写不覆盖先写」同向：关键元素标题优先）。

    键集含**括注主名别名**（键序 = 完整标题 → 剥前缀 → 主名，
    先出现者胜 = 长名优先）：否则模型传裸主名（`艾AA`）时
    `canonical_ref_key` 产 `艾AA`、而索引里只有 `艾AA（AA）` ⇒ `find_ref_group`
    返回 None，`resolve_shot_refs` 取不到概念图（生成时参考图静默落空）。
    """
    index: Dict[str, Dict[str, Any]] = {}
    for group in state.get(cat_key, []) or []:
        if not isinstance(group, dict):
            continue
        keys = [canonical_ref_key(group.get("title"))]
        alias = element_alias_name(group.get("title"))
        if alias:
            keys.append(alias)
        keys.append(str(group.get("id") or "").strip())
        for key in keys:
            if key and key not in index:
                index[key] = group
    return index


def find_ref_group(state: Dict[str, Any], ref: Any) -> Optional[Dict[str, Any]]:
    """按引用（裸名 / 带前缀标题 / 组 id 三种写法均可）取关键元素组。

    读口唯一入口：`resolve_shot_refs` / `resolve_shot_audio_refs` /
    `web/routes/generate_image.py` / `web/multimodal_builder.py` 四处共用，
    杜绝同一条引用链各写一遍比对式（本次事故正是四处各写一遍且全部逐字比对）。
    """
    cats = (CAT_KEY_ELEMENTS,)
    for cat in cats:
        idx = build_ref_index(state, cat)
        hit = idx.get(canonical_ref_key(ref))
        if hit is not None:
            return hit
    return None


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


# ---------- refAssets 写口归一（2026-09-26） ----------
# 病灶：`refAssets` 的契约是**媒体 URL 列表**（`models.DraftRefRecord.ref_assets`
#   / 前端 `refAssetName`/`refAssetType`/`safeUrl` 全按 URL 消费），而模型的
#   写入口径是**草稿身份**（它在状态快照里看得见的是 `drafts[].id`，看不见
#   Ke 分组标题），于是照抄 `draft-1790359321-a010380d` 落库 —— 实测 79 条全为此形态。
#   后果两处：①前端 `<img src="draft-…">` 被 `safeUrl` 拦成空串 ⇒ 图裂成 alt 文字；
#   ②生成时该字符串被当 URL 塞进 `reference_images` ⇒ **参考图静默落空**（花钱生成白挂）。
# 口径：写口把「能解析到本沙盒草稿的 id」归一为该草稿的媒体 URL；
#   解析不到的（含用户手填的合法 URL、外部链接）**原样保留**——不静默丢弃，
#   与「未知引用由既有回喂通道告知」同档（宁缺毋滥 + 不吞输入）。
# 单一事实源：所有 refAssets 写入路径（建组附带 / 新增卡 / patch）**唯一入口 = 本函数**。

def build_draft_media_index(state: Dict[str, Any]) -> Dict[str, str]:
    """建「草稿 id → 媒体 URL」索引（覆盖全部故事板类别，供 refAssets 归一）。

    只收录**已有媒体**的卡（无媒体卡由 `build_draft_id_set` 另行判定）。
    """
    index: Dict[str, str] = {}
    for cat_key in ALL_CATEGORIES:
        for group in state.get(cat_key, []) or []:
            if not isinstance(group, dict):
                continue
            for d in (group.get("drafts") or []):
                if not isinstance(d, dict):
                    continue
                did = str(d.get("id") or "").strip()
                url = (str(d.get("imgUrl") or "").strip()
                       or str(d.get("videoUrl") or "").strip()
                       or str(d.get("audioUrl") or "").strip())
                if did and url:
                    index[did] = url
    return index


def build_draft_id_set(state: Dict[str, Any]) -> set:
    """建「沙盒内全部草稿 id」集合（含尚无媒体者，供 refAssets 归一判定）。"""
    ids: set = set()
    for cat_key in ALL_CATEGORIES:
        for group in state.get(cat_key, []) or []:
            if not isinstance(group, dict):
                continue
            for d in (group.get("drafts") or []):
                if isinstance(d, dict):
                    did = str(d.get("id") or "").strip()
                    if did:
                        ids.add(did)
    return ids


# ---------- refAssets 条目形态解包（2026-09-30，事故 9999/参考图静默落空） ----------
# 病灶：模型把条目写成**对象**（`{"type": "image", "name": "...", "url": "..."}`），
#   平台此前只用 `str(raw)` 粗暴字符串化 ⇒ 落库成 Python repr 串
#   （`"{'type': 'image', 'name': '设定图·曹彬', 'url': '/workspace/assets/…'}"`）。
#   该串既不是草稿 id 也不是媒体 URL，落进下面的分支 ③「原样保留」**永久留存**，
#   后果两处（与 draft-id 形态同构，只是更难认）：
#     ① 前端 `<img src="{'type'…">` 被 `safeUrl` 拦成空串 ⇒ 参考栏图裂、
#        计数因去重失效而虚高（坏串与真 URL 永不相等）；
#     ② 生成时该串被当 URL 塞进 `reference_images` ⇒ **参考图静默落空**：
#        实测 9999 全部 30 次生图日志 `refs=0`，模型只拿到文字、角色全靠编。
#   口径：**收得宽、存得严** —— 认对象（真 dict / JSON 串 / Python repr 串）并取其
#   `url`；取不到 url 再退回其 `id`/`draftId` 走既有草稿 id 归一；两者皆无才丢弃
#   （WARNING 留痕，不静默吞）。裸串仍走原三条判定，`"whatever"` 之类照旧保留。
# 为何不是写口拒收：拒绝写会让模型连卡都建不成（形态属可无损归一，不属安全边界），
#   与「未知引用由既有回喂通道告知」同档。
_DICT_ENTRY_RE = re.compile(r"^\s*\{.*\}\s*$", re.S)


def unwrap_ref_entry(raw: Any) -> Dict[str, str]:
    """把一条 refAssets 条目解包为 `{"url": …, "id": …}`（解包不出则两者皆空）。

    认三种形态（模型实测都出现过）：
      1. 真 dict（工具入参未被字符串化时）；
      2. JSON 对象串（`{"url": "…"}`，双引号）；
      3. Python repr 串（`{'url': '…'}`，单引号 —— 本次事故的现场形态）。

    第 3 种**不能**用 `json.loads`（单引号非法），故走 `ast.literal_eval`：
    只解析字面量、不执行代码（无副作用面，比 eval 安全）。
    """
    if isinstance(raw, dict):
        obj: Any = raw
    else:
        text = str(raw or "").strip()
        if not _DICT_ENTRY_RE.match(text):
            return {"url": "", "id": ""}
        obj = None
        try:
            parsed = json.loads(text)
            obj = parsed if isinstance(parsed, dict) else None
        except Exception:  # noqa: BLE001 —— 单引号 repr 串在此必然失败，转 literal_eval
            obj = None
        if obj is None:
            try:
                parsed = ast.literal_eval(text)
                obj = parsed if isinstance(parsed, dict) else None
            except Exception:  # noqa: BLE001
                obj = None
        if obj is None:
            return {"url": "", "id": ""}
    url = str(obj.get("url") or obj.get("imgUrl") or "").strip()
    rid = str(obj.get("id") or obj.get("draftId") or obj.get("draft_id") or "").strip()
    return {"url": url, "id": rid}


def normalize_ref_assets(
    state: Dict[str, Any], refs: Any,
) -> List[str]:
    """把 refAssets 归一到**媒体 URL**（写口唯一入口，去重保序留首）。

    判定（按序）：
      ⓪ 条目是**对象形态**（真 dict / JSON 串 / Python repr 串）⇒ 解包取 `url`；
         无 `url` 再退回其 `id` 继续走 ①②；两者皆无 ⇒ 丢弃该条（不能拿 repr 串
         当 URL 发出去），与「未命中即去记号留文字」同向、不静默吞用户输入；
      ① 条目是沙盒草稿 id 且该卡**已有媒体** ⇒ 落其 URL；
      ② 条目是沙盒草稿 id 但该卡**尚无媒体**（图还没出）⇒ 丢弃该条
         （挂空 URL 无意义；与「未命中即去记号留文字」同向，不留误导性占位）；
      ③ 其余（合法 URL / 外部链接 / 未知裸串）⇒ **原样保留**，不吞输入
         （用户手填的素材 URL 必须照常可用）。

    ⚠ 关键分支次序：`str(raw)` 只能用于**裸串**。对象形态必须先解包、且丢弃判据
    必须基于**解包后的 item**——若拿原串去匹配 `{…}`，会把已成功解包出的 URL
    反判成"对象形态"而丢弃（本函数首版即踩此坑，实测 S1/S3 归一出空列表）。
    """
    if not refs:
        return []
    if isinstance(refs, str):
        refs = [refs]
    with_media = build_draft_media_index(state)
    all_ids = build_draft_id_set(state)
    out: List[str] = []
    for raw in refs:
        is_obj_form = isinstance(raw, dict) or bool(
            _DICT_ENTRY_RE.match(str(raw or "").strip()))
        if is_obj_form:
            unwrapped = unwrap_ref_entry(raw)
            item = unwrapped["url"] or unwrapped["id"]
            if not item:
                logger.warning(f"[refAssets] 对象条目无可解析的 url/id，已丢弃：{raw!r}")
                continue
            if unwrapped["url"]:
                # 已直接拿到 URL：不再当草稿 id 二次解释
                if item not in out:
                    out.append(item)
                continue
        else:
            item = str(raw or "").strip()
            if not item:
                continue
        if item in with_media:
            value = with_media[item]
        elif item in all_ids:
            continue  # ② 卡在但还没图：不留空占位
        else:
            value = item  # ③ URL / 未知：原样保留
        if value not in out:
            out.append(value)
    return out


def patch_draft(
    draft: Dict[str, Any], patch: Dict[str, Any], state: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """按 ALLOWED_DRAFT_FIELDS 白名单就地更新 draft，返回 (是否有字段被修改, 被丢弃字段名列表)。
    被丢弃字段透出给调用方（T2 第一步「错误可见」），由调用方决定拒收/告警口径。

    确认状态闭环：提示词被重写（值变化且非空）时，「已确认」标记作废
    （tag 重置为 Agent）——用户提修改 → 模型重写 → 需重新经用户确认，
    避免旧确认被静默继承到新版本提示词。

    `state` 为**必填**（2026-09-26）：refAssets 入参需经 `normalize_ref_assets`
    解析草稿 id → 媒体 URL。写成必填而非可选，是为了让「漏传 = 归一失效」
    在调用点即报错，而不是留下一条静默落到坏值的写路径（G4：覆盖全部调用路径）。
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
            value = patch[field]
            if field == "refAssets":
                value = normalize_ref_assets(state, value)
            draft[field] = value
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
            # shotRefs 写口同口径 canonical 去重 + 归一为元素组全称
            # （与 create_group 三源合并同引 canonicalize_shot_refs；调用方
            # 需自带 state 时走 canonicalize_shot_refs(state, refs) 分支）
            group[field] = dedup_shot_refs(patch[field]) if field == "shotRefs" else patch[field]
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


def append_draft(
    group: Dict[str, Any], draft_data: Dict[str, Any], state: Dict[str, Any],
) -> Dict[str, Any]:
    """向指定 group 添加一个 draft，返回新建的 draft。

    `state` 为**必填**（2026-09-26）：新建卡的 refAssets 同经
    `normalize_ref_assets` 归一（模型建卡时写的是草稿 id，不是媒体 URL）。
    """
    payload = dict(draft_data or {})
    if "refAssets" in payload:
        payload["refAssets"] = normalize_ref_assets(state, payload.get("refAssets"))
    draft = build_draft_dict(payload)
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


def resolve_shot_refs(
    state: Dict[str, Any], group: Optional[Dict[str, Any]], limit: int = 5,
) -> List[Dict[str, str]]:
    """解析分镜的 shotRefs → 对应关键元素的概念图 URL 作为参考图（默认最多 5 张）。

    2026-09-23 批10（事故 4444/P0-A）：比对改走 `find_ref_group`。
    旧实现逐字比对 `id`/`title`，而落盘标题带前缀、shotRefs 存裸名 ⇒ 恒不命中
    （4444 实测 22 镜 image_refs = 0）。canonical 口径见 `canonical_ref_key`。

    2026-09-26：取图加**种类判据**——原实现「组内首张有 imgUrl 的卡」隐式依赖
    卡序（模型建组时设定图恰好在前），一旦组内先有别的图卡就会取错图；
    现优先取**图像类**卡（`infer_media_type == image`，排除音色卡/视频卡），
    同类内仍按原序取首张（不改变既有正确结果）。
    """
    refs: List[Dict[str, str]] = []
    if not group:
        return refs
    shot_refs = group.get("shotRefs") or []
    if not shot_refs:
        return refs
    for ref_title in shot_refs:
        if not isinstance(ref_title, str):
            continue
        ke_group = find_ref_group(state, ref_title)
        if ke_group is None:
            continue
        candidates = [
            d for d in (ke_group.get("drafts") or [])
            if isinstance(d, dict) and (d.get("imgUrl") or "")
        ]
        # 图像类优先（音色卡 mediaType=audio 且无 imgUrl，本就不会入选；
        # video 卡带 imgUrl 时才是真歧义——按种类排到后面）
        pick = next(
            (d for d in candidates if infer_media_type(d) == "image"),
            candidates[0] if candidates else None,
        )
        if pick is not None:
            refs.append({"url": str(pick.get("imgUrl")), "role": "reference"})
    return refs[:limit]


def resolve_shot_audio_refs(
    state: Dict[str, Any], group: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """批 6 · A3：按分镜组 shotRefs 收集关键元素卡的 audioUrl（音色锚点）。

    与 resolve_shot_refs 同构（imgUrl→reference 的姊妹轴）：分镜引用了
    带音色参考的元素时，视频生成自动把该音色挂为 reference_audio，
    对齐外部标杆「按引用自动挂声音锚点」。只读，不改状态。

    2026-09-23 批10（事故 4444/P0-A）两处修复：
    ① 比对照 `resolve_shot_refs` 同改 canonical（`find_ref_group`）；
    ② 音色卡优先取 `audioType == 'voice'` 的卡（Skill 明文的 key_element_audio）。
       归属契约 = 挂在角色**自己的 keyElements 组内**（见 `CATEGORY_MEDIA_MATRIX`
       的 keyElement 行「可放音频」，及 `prompt_refs`/前端 `isVoiceCard` 同口径）。
       非硬判：voice 卡缺失时回落该组任意带 audioUrl 的卡（存量兼容）。
    """
    refs: List[Dict[str, str]] = []
    if not group:
        return refs
    for ref_title in group.get("shotRefs") or []:
        if not isinstance(ref_title, str):
            continue
        ke_group = find_ref_group(state, ref_title)
        if ke_group is None:
            continue
        drafts = [d for d in (ke_group.get("drafts") or []) if isinstance(d, dict)]
        # ① voice 卡优先（音色锚点的规范载体）
        pick = next(
            (d for d in drafts
             if str(d.get("audioUrl") or "").strip()
             and str(d.get("audioType") or "").strip() == "voice"),
            None)
        # ② 回落：该组任意带音源的首张卡（存量兼容，不加硬判）
        if pick is None:
            pick = next(
                (d for d in drafts if str(d.get("audioUrl") or "").strip()), None)
        if pick is not None:
            refs.append({"url": str(pick.get("audioUrl")), "role": "reference_audio"})
    return refs


def parse_element_tokens(text: str) -> List[str]:
    """批 6 · A3：提取文本中的 [元素名] 令牌（外部标杆 形态），去重保序。

    令牌是写在分镜描述里的人可读引用层；匹配不到元素的令牌由调用方
    丢弃（不拒收，不锁死）。

    2026-09-23 批3 附带修复：**跳过 Markdown 转义占位** `\\[...\\]`。
    Skill 模板里的占位符原文是 `\\[角色描述，含年龄/性别/外貌…\\]`
    （方括号被反斜杠转义），原实现把它当令牌提取，产出末尾还粘上反斜杠
    （实测 `'角色描述，含年龄/性别/外貌/服装/标志性细节\\\\'`），
    进而触发「元素令牌未匹配」**误报警告**、污染引用通道。
    转义方括号是**模板占位**而非元素引用，一律不提取。
    """
    tokens: List[str] = []
    # 先剔除转义方括号（`\[` / `\]`），再在剩余文本上做令牌提取；
    # 这样 `\[占位\]` 不会因内部被掏空而残留 `[占位]` 形态。
    cleaned = re.sub(r"\\[\[\]]", "", str(text or ""))
    for raw in re.findall(r"\[([^\[\]]{1,60})\]", cleaned):
        token = raw.strip()
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def scan_bare_name_mentions(
    desc: str, key_elements: List[Dict[str, Any]],
) -> List[str]:
    """K4 批（2026-09-16 对齐 flova）：裸名提及自动绑定——分镜正文里
    提到元素名（原全称/归一裸名/**括注主名**）即自动挂引用（提及即绑定）。

    镜像前端 desc-ref-utils.ts descChipNames 语义：候选源 = keyElements
    全集，形态由 `element_name_variants` **唯一入口**产出（原全称 + 归一裸名
    + 括注主名，Set 去重、≥2 字符守卫、最长优先防重叠）；
    命中规则 = 候选名在 desc 子串出现；返回 = 命中的关键元素组标题
    （shotRefs 存储口径，去重保序）。纯函数，不改状态。

    2026-09-26：候选形态改走 `element_name_variants`——此前只有「完整标题 +
    剥容器前缀」两形态，模型把别名写进组名括注（`艾AA（AA）`）而正文写主名
    （`艾AA`）时**恒不命中**且本函数无「未命中」概念 ⇒ 引用静默落空、零告警。
    """
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
        for cand in element_name_variants(title):
            if len(cand) >= _MIN_REF_NAME_LEN and cand not in seen:
                seen.add(cand)
                candidates.append((cand, title))
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
    hits: List[str] = []
    for cand, title in candidates:
        if cand in text and title not in hits:
            hits.append(title)
    return hits


def canonicalize_shot_refs(state: Dict[str, Any], refs: Any) -> List[str]:
    """把引用归一到**元素组标题**（canonical 全称），canonical 去重保序留首。

    2026-09-25 用户裁决：「不能传裸名，裸名只是 UI 视觉效果，本身必须是含前缀的」。
    裸名（`程心`）与全称（`Element_程心`）此前是**两种落库形态**，导致同一条引用链
    上「存的」与「比对的」口径分叉——全库 8888 项目 47 条引用里 43 条为裸名，
    前端 chip 点击（逐字比对元素标题）91.5% 落空，表现为「有时跳有时不跳」。

    纳入归一的三条路径（同引本函数，P1 单一入口）：
      - 建组写口 `merge_shot_refs`（三源合并后）；
      - 改分组写口 `patch_group` 的 shotRefs 分支；
      - 前端点击读口（`desc-ref-utils.ts` 同契约镜像）。

    命中元素组 → 落其真实 `title`；查无此元素 → **保留原值**（不静默丢弃：
    未知引用由既有回喂通道告知，与「令牌匹配不到不拒收」同档）。纯函数。
    """
    index = build_ref_index(state, CAT_KEY_ELEMENTS)
    out: List[str] = []
    seen: set = set()
    for ref in refs or []:
        if not isinstance(ref, str) or not ref.strip():
            continue
        hit = index.get(canonical_ref_key(ref)) or index.get(ref.strip())
        value = str(hit.get("title")) if hit is not None else ref
        # 去重键必须取**归一后**的形态：`程心` / `Element_程心` / `ke-chengxin`
        # 三种写法指向同一元素时须收敛为一条（若用入参键去重，组 id 写法
        # （canonical_ref_key 不剥 `ke-`）会与标题写法各占一条 = 重复引用）。
        key = canonical_ref_key(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def merge_shot_refs(
    state: Dict[str, Any], desc: str, explicit_refs: Any = None,
) -> List[str]:
    """**shotRefs 三源合并的唯一实现**（2026-09-23 批12，事故 4444/B-1）。

    ## 为什么抽这一层（根因）

    此前**写口与读口各写一遍**，且口径不同：
      - 写口（`storyboard_create_group` 的 aexecute）：显式 `shot_refs`
        ∪ `[元素名]` 令牌 ∪ 裸名提及 —— **三源合并**；
      - 读口（`fc_gates.structure_integrity_gate`）：**只读显式
        `args.get("shot_refs")`**，不看 desc。

    而工具对模型的**文档承诺**是「`shot_refs` 留空时系统自动从分组描述里的
    `[元素名]` 令牌与裸名提及解析合并」。于是模型照文档留空 ⇒ **闸机在合并
    之前就把它拒了**。

    4444 实证（`conv-1790159633` seq55–59）：前 5 次建镜头按文档留空
    `shot_refs`、把元素规范写进 desc 的 `[令牌]` ⇒ **5 次全被拒**
    （回喂「shotRefs 为空」）；此后 22 次改为一律显式重抄 ⇒
    **平台亲手教模型放弃了它的正确行为**。
    全量统计：该子代理 53 次建组，31 次未传 `shot_refs`、22 次传了。

    ## 口径（三源合并 + canonical 去重）

    显式 `shot_refs` ∪ `[元素名]` 令牌匹配 ∪ 裸名提及，**canonical 去重保序留首**
    （裸名与 `Element_` 前缀算同一引用，去重键 = `strip_type_prefix`）。
    与 2026-09-17 flova 对齐批同口径，注释与行为逐字保留。

    **单一事实源**：写口与闸机**必须同引本函数**——两处各写一遍正是本次事故成因。
    纯函数，不改状态。
    """
    explicit = [r for r in (explicit_refs or []) if str(r).strip()]
    tokens = parse_element_tokens(desc or "")
    matched_titles, _unmatched = match_element_titles_report(state, tokens)
    bare_hits = scan_bare_name_mentions(
        desc or "", state.get(CAT_KEY_ELEMENTS, []))
    # 三源合并 → canonical 去重 → **归一为元素组全称**（唯一实现 = canonicalize_shot_refs）。
    # 2026-09-25 用户裁决「不能传裸名」：此前 ① 显式 shot_refs 源原样透传，模型重抄
    # 裸名即落裸名（8888 实测 43/47 条为裸名），前端 chip 点击逐字比对 ⇒ 91.5% 落空。
    return canonicalize_shot_refs(state, list(explicit) + matched_titles + bare_hits)


def match_element_titles_report(
    state: Dict[str, Any], tokens: List[str],
) -> Tuple[List[str], List[str]]:
    """把 [元素名] 令牌匹配到既有关键元素组标题，返回 (匹配标题, 未匹配令牌)。

    匹配规则：精确 → 双向包含（比对面 = `element_name_variants` **全部形态**，
    故 `[艾AA]` / `[艾AA（AA）]` / `[Element_艾AA（AA）]` 三种写法同命）。
    未匹配令牌由调用方决定处置（建组通道丢弃不拒收——令牌是引导不是闸；
    但必须回喂告知模型，防「以为挂上了」）。"""
    title_variants: List[Tuple[str, List[str]]] = []
    for g in (state.get(CAT_KEY_ELEMENTS, []) or []):
        if not isinstance(g, dict):
            continue
        title = str(g.get("title") or "").strip()
        if title:
            title_variants.append((title, element_name_variants(title)))
    matched: List[str] = []
    unmatched: List[str] = []
    for token in tokens or []:
        token = str(token or "").strip()
        if not token:
            continue
        # ① 精确：令牌等于任一形态（含括注主名）
        hit = next((t for t, vs in title_variants if token in vs), None)
        # ② 双向包含：令牌与任一形态互为子串（容 `[启示号实验舱]` 这类简称写法）
        if hit is None:
            hit = next(
                (t for t, vs in title_variants
                 if any(token in v or v in token for v in vs)),
                None)
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
