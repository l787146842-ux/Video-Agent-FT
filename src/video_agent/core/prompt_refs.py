"""
提示词引用解析 — 把提示词中的 @名称 / <<<image_名称>>> 映射为实际媒体素材。

前端 PromptEditor 允许用户在提示词里输入 @ 引用参考素材/故事板媒体，
序列化为 "@名称" 文本；Skill 模板（外部标杆方言）则用 <<<image_名称>>>。
生成（出图/出视频）时模型无法理解这些记号，本模块负责：
1. 从故事板状态构建 名称 → (url, kind) 映射（关键元素分组标题 / 草稿 label / 文件名）；
2. 扫描提示词中的两类引用记号，把被引用但不在参考列表里的素材自动纳入参考列表；
3. 把记号重写为带序号的位置标记（如 [参考图2：Element_月球]），
   让多模态模型精确知道第 N 张参考图对应提示词里的哪个元素。
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.video_agent.state.models import (
    CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS,
    # 2026-09-23 批11（事故 4444/P1-5）：mediaType 缺省取值唯一推导入口
    infer_media_type,
)
from src.video_agent.state.storyboard_ops import element_name_variants

# 引用记号匹配（两式同义，2026-09-07 外部标杆 记号兼容裁决）：
# 1) 半角 @ 或全角 ＠ + 名称（平台原生，前端 PromptEditor 序列化产物）；
# 2) <<<image_名称>>>（外部标杆 Skill 模板方言）——抄自 外部标杆 的 Skill 原样可用，
#    命中与 @ 同轨处理，未命中同 @ 去记号留名称。
#
# 2026-09-23 批3（Q4/Q6，用户裁决「引用记号必须能工作」）：修三条独立根因——
#   R1 方括号被吞：原排除类不含 [ ]，`@[程心]` 捕获出 `[程心]` → 查 map 必落空。
#      现将可选的 [ ] 包络排除在捕获组外（@[名] 与 @名 等价）。
#   R2 转义下划线：Skill 模板原文是 `<<<image\_场景>>>`（Markdown 转义，字符码 92
#      反斜杠），原正则要求裸 `image_` → 连匹配都不成立、整段原样进入生成请求。
#      现容许 `image` 与 `_` 之间存在可选反斜杠。
#   两条都不改变「未命中即去记号留文字」的既有语义。
#
# 2026-10-06 事故 9999/正文内联引用批（用户裁决 A）：**名称捕获不得吞标点**。
# 病灶：字符集 `[^\s@＠\[\]]+` 排除面太窄 ⇒ 中文标点被吞进名称，查 map 落空、
# 静默去记号留文字。实测 13 类常见后接字符里只有空白/换行 2 类能解析：
# `@程心，` / `@程心。` / `@程心）` / `@程心说` **全部失败**——而中文正文里
# 标点紧跟才是常态。修法见 `_match_longest_name`（最长前缀回退），
# 既不吞标点、也不误伤名字本身带标点的元素（如 `艾AA（AA）`）。
_MENTION_RE = re.compile(
    r"<<<\s*image\\?_([^<>]+?)\s*>>>"
    r"|[@＠]\[?([^\s@＠\[\]]+)\]?"
)

_KIND_LABEL = {"image": "参考图", "video": "参考视频", "audio": "参考音频"}

# 音频扩展名（与 `web/generation_submit.is_audio_url` 同口径）：
# 仅用于给**不在 media_map 里的裸 URL** 判类型，使「按类型编号」与发送侧分桶一致。
_AUDIO_URL_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


def _match_longest_name(raw: str, media_map: Dict[str, Dict[str, str]]) -> Tuple[str, str]:
    """把 @ 捕获到的原始串解析为 (命中的名称, 未消费的尾部)。

    2026-10-06 事故 9999/正文内联引用批：`_MENTION_RE` 的名称捕获是**贪婪**的
    （只要不是空白/@/方括号就吞），故 `@程心，` 捕获出 `程心，`、`@程心说`
    捕获出 `程心说`，两者查 map 都落空 ⇒ **静默去记号留文字**（不报错、不回喂），
    正文里的引用大面积失效而不自知。

    本函数按**最长前缀回退**解析：从整串开始逐字符缩短，首个命中 media_map 的
    即为名称，其余部分原样归还给调用方（拼回提示词，不丢字）。

    这样同时成立：
    - `@程心，` → 命中 `程心`，尾部 `，` 保留（标点不再被吞）；
    - `@艾AA（AA）` → 若全串就是 map 键则整体命中（名字自带标点不被截断）；
    - `@不存在` → 无命中，返回 ("", 原串) 交调用方走既有「去记号留文字」语义。

    复杂度 O(len(raw)) 次 dict 查表，名称长度量级，可忽略。
    """
    s = raw or ""
    while s:
        if s in media_map:
            return s, raw[len(s):]
        s = s[:-1]
    return "", raw or ""


def media_of_draft(d: Dict[str, Any]) -> Tuple[str, str]:
    """取草稿的主媒体 (url, kind)：按 mediaType 优先，其次按已有字段兜底。

    2026-09-23 批11（事故 4444/P1-5）：mediaType 的缺省取值改走
    `models.infer_media_type` 唯一入口——未填 mediaType 但填了 audioType
    的音频卡此前被本处读成 image，与构建工厂/闸机是同一处口径漂移。
    """
    kind = infer_media_type(d)
    if kind == "video":
        url = d.get("videoUrl") or d.get("imgUrl") or ""
        return url, "video"
    if kind == "audio":
        url = d.get("audioUrl") or ""
        return (url, "audio") if url else ("", "image")
    url = d.get("imgUrl") or d.get("videoUrl") or d.get("audioUrl") or ""
    if d.get("videoUrl") and url == d.get("videoUrl"):
        return url, "video"
    if d.get("audioUrl") and url == d.get("audioUrl"):
        return url, "audio"
    return url, "image"


def _group_has_visual_card(group: Dict[str, Any]) -> bool:
    """该关键元素组是否存在**视觉卡**（图像/视频）——按卡的 mediaType 判定，
    **不看是否已出图**（2026-10-16 音色抢名批）。

    判据必须走 `infer_media_type`（唯一缺省入口）而非「有无 imgUrl」：
    「组内只有音色卡」与「组内有设定图但尚未出图」在 URL 面上无法区分，
    若按 URL 判就会在「图未生成」的时间窗内把组标题让给音频 ⇒ 原故障按时间窗
    复发。按**卡种类**判则两种形状天然分开，与出图进度无关。
    """
    for d in group.get("drafts", []) or []:
        if not isinstance(d, dict):
            continue
        if infer_media_type(d) in ("image", "video"):
            return True
    return False


def build_storyboard_media_map(state: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """构建 名称 → {url, kind} 映射（与前端 PromptEditor 命名规则对齐）。

    命名来源（**先到先得**，同名后到不覆盖）：
    - 关键元素：分组 title（如 Element_月球）**及其剥前缀裸名**（月球）
    - 所有草稿：label
    - URL 文件名（兜底，与前端 refAssetName 的文件名规则一致）

    2026-10-16 音色抢名批（用户裁决「先写引用、音频出来自动解析」配套）：
    **音色卡（mediaType=audio）不得抢占关键元素组标题**。病灶：音色卡与角色
    设定图同组，标题登记只记「该组第一张有媒体的卡」——音色卡排在前面时
    （9999 实测 `音色·程心` 在 `设定图·程心` 之前）音频抢走组标题，导致
    `@程心` 解析成**参考音频**而非角色图；一旦音频落地，全篇 `@角色名`
    会集体从「角色的脸」变成「角色的声音」，画面生成失控。
    修法：组标题登记**分两遍**——
      ① 先只由视觉卡（image/video）登记组标题；
      ② 仅当该组**没有任何视觉卡**（纯音色卡组）时，才允许音频兜底登记组标题
         （否则 @AA 这类「只有音色卡」的形状会静默降级为纯文字）。
    label 与文件名两路不受影响：音色卡仍可用 `音色·程心`（label）引用。

    2026-09-23 批3 R3（Q4/Q6）：写口 `normalize_group_title` **无条件补类型前缀**
    （`Element_程心`），而模型在提示词里写的是**裸名**（`<<<image_程心>>>`）——
    实跑全量 110 次引用中带前缀者 0 次，即**110 次引用命中 0 次**。
    平台在别处（`scan_bare_name_mentions`、前端 `desc-ref-utils`）**早就做了裸名归一**，
    唯独本引用链漏了，属口径漂移而非设计。故此处为关键元素标题补登裸名别名，
    与其余各层口径对齐（前缀名仍保留，向后兼容既有带前缀写法）。
    """
    media_map: Dict[str, Dict[str, str]] = {}

    def put(name: str, url: str, kind: str) -> None:
        name = (name or "").strip()
        if not name or not url:
            return
        if name not in media_map:
            media_map[name] = {"url": url, "kind": kind}

    def put_title_aliases(group: Dict[str, Any], url: str, kind: str) -> None:
        # 2026-09-26：形态集走 `element_name_variants` 唯一入口
        # （全称 + 剥前缀 + **括注主名**）。此前只登记前两式，
        # 模型在提示词里写主名（`<<<image_艾AA>>>`）时查表落空
        # ⇒ 引用静默降级为纯文字（与 desc 内联块同一处口径缺口）。
        for _name in element_name_variants(group.get("title", "")):
            put(_name, url, kind)

    for cat in (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS):
        for g in state.get(cat, []) or []:
            if not isinstance(g, dict):
                continue
            # 组标题登记的两遍法（仅关键元素有组标题语义）：
            # 第一遍（视觉卡优先）在下方循环内完成；第二遍（音频兜底）就此打标。
            title_reserved = cat == CAT_KEY_ELEMENTS and _group_has_visual_card(g)
            audio_fallback_done = False
            for d in g.get("drafts", []) or []:
                if not isinstance(d, dict):
                    continue
                for field in ("imgUrl", "videoUrl", "audioUrl"):
                    url = d.get(field) or ""
                    if not url:
                        continue
                    kind = {"imgUrl": "image", "videoUrl": "video", "audioUrl": "audio"}[field]
                    if cat == CAT_KEY_ELEMENTS:
                        if kind == "audio":
                            # 音频：组标题只在「纯音色卡组」才兜底登记一次
                            if not title_reserved and not audio_fallback_done:
                                put_title_aliases(g, url, kind)
                                audio_fallback_done = True
                        else:
                            # 视觉卡：无条件登记组标题（真正的「角色图」语义）
                            put_title_aliases(g, url, kind)
                    put(d.get("label", ""), url, kind)
                    fname = Path(str(url).split("?")[0].split("#")[0]).name
                    put(fname, url, kind)
    return media_map


def resolve_prompt_mentions(
    prompt: str,
    base_refs: List[str],
    media_map: Dict[str, Dict[str, str]],
    max_refs: int = 5,
) -> Tuple[str, List[str]]:
    """解析提示词中的 @提及，返回 (重写后的提示词, 最终参考素材 URL 列表)。

    - base_refs：草稿已有的参考素材（refAssets），保持原顺序；
    - @名称 命中的素材若不在 base_refs 且未满上限则自动追加；
    - @名称 重写为 [参考图N：名称]（N = 该素材在**同类型素材**中的序号）；
      未命中 / 超限的 @名称 仅去掉 @ 前缀保留文字，避免模型困惑。

    2026-10-19 音色引用批（用户裁决「图和音频各算各的」）：
    标记序号**按素材类型独立编号**，不再是「在总列表里排第几」。病灶（9999 实测）：
    S2 合并列表 = 4 张图 + 1 条音色，音色排在总列表第 5 位 ⇒ 正文写成
    `[参考音频5：音色·程心]`；而发送时按类型分桶（`generation_submit` 的
    out_audios 桶），音频桶里**只有 1 条** ⇒ 模型收到 1 条音频，文本却说「第 5 条」，
    对不上号。按类型编号后 `[参考音频1：音色·程心]` 与音频桶序号一致。
    图片侧口径不变（`参考图N` 仍是图片桶内序号，既有实产与测试全部保持）。
    """
    refs: List[str] = [u for u in (base_refs or []) if u][:max_refs]

    def kind_of(url: str) -> str:
        info = media_map.get(url) or {}
        kind = str(info.get("kind") or "")
        if kind in ("image", "video", "audio"):
            return kind
        # 未在映射里（外部裸 URL 等）：与 `generation_submit.is_audio_url` 同口径
        clean = str(url or "").strip().lower().split("?")[0].split("#")[0]
        return "audio" if clean.endswith(_AUDIO_URL_EXTS) else "image"

    def index_in_kind(url: str) -> int:
        """该素材在**同类型素材**中的 0 基序号（类型内首次出现序）。"""
        want = kind_of(url)
        seen: List[str] = []
        for u in refs:
            if kind_of(u) == want and u not in seen:
                seen.append(u)
        return seen.index(url) if url in seen else -1

    def replace(m: re.Match) -> str:
        raw = (m.group(1) or m.group(2) or "").strip()
        # 2026-10-06 事故 9999：@ 式走「最长前缀回退」，避免中文标点被吞进名称
        # （<<<image_>>> 式有闭合定界符，名称天然无歧义，原样查表即可）。
        tail = ""
        if m.group(2) is not None:
            name, tail = _match_longest_name(raw, media_map)
            info = media_map.get(name) if name else None
        else:
            name = raw
            info = media_map.get(name)
        if not info:
            return name + tail  # 未命中：去掉记号，保留文字（含标点尾部）
        url = info["url"]
        idx = index_in_kind(url)
        if idx < 0:
            if len(refs) >= max_refs:
                return name + tail  # 超限：无法随请求发送，仅保留文字
            refs.append(url)
            idx = index_in_kind(url)
        label = _KIND_LABEL.get(info.get("kind", "image"), "参考图")
        return f"[{label}{idx + 1}：{name}]" + tail

    resolved = _MENTION_RE.sub(replace, prompt or "")
    return resolved, refs
