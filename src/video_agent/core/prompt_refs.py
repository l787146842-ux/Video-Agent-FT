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
_MENTION_RE = re.compile(
    r"<<<\s*image\\?_([^<>]+?)\s*>>>"
    r"|[@＠]\[?([^\s@＠\[\]]+)\]?"
)

_KIND_LABEL = {"image": "参考图", "video": "参考视频", "audio": "参考音频"}


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


def build_storyboard_media_map(state: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """构建 名称 → {url, kind} 映射（与前端 PromptEditor 命名规则对齐）。

    命名来源（后写不覆盖先写，保证关键元素标题优先）：
    - 关键元素：分组 title（如 Element_月球）**及其剥前缀裸名**（月球）
    - 所有草稿：label
    - URL 文件名（兜底，与前端 refAssetName 的文件名规则一致）

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

    for cat in (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS):
        for g in state.get(cat, []) or []:
            for d in g.get("drafts", []) or []:
                for field in ("imgUrl", "videoUrl", "audioUrl"):
                    url = d.get(field) or ""
                    if not url:
                        continue
                    kind = {"imgUrl": "image", "videoUrl": "video", "audioUrl": "audio"}[field]
                    # 关键元素用分组标题命名（对齐前端 refAssetName）
                    if cat == CAT_KEY_ELEMENTS:
                        # 2026-09-26：形态集走 `element_name_variants` 唯一入口
                        # （全称 + 剥前缀 + **括注主名**）。此前只登记前两式，
                        # 模型在提示词里写主名（`<<<image_艾AA>>>`）时查表落空
                        # ⇒ 引用静默降级为纯文字（与 desc 内联块同一处口径缺口）。
                        for _name in element_name_variants(g.get("title", "")):
                            put(_name, url, kind)
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
    - @名称 重写为 [参考图N：名称]（N 为该素材在最终列表中的序号）；
      未命中 / 超限的 @名称 仅去掉 @ 前缀保留文字，避免模型困惑。
    """
    refs: List[str] = [u for u in (base_refs or []) if u][:max_refs]

    def index_of(url: str) -> int:
        return refs.index(url) if url in refs else -1

    def replace(m: re.Match) -> str:
        name = (m.group(1) or m.group(2) or "").strip()
        info = media_map.get(name)
        if not info:
            return name  # 未命中：去掉记号，保留文字
        url = info["url"]
        idx = index_of(url)
        if idx < 0:
            if len(refs) >= max_refs:
                return name  # 超限：无法随请求发送，仅保留文字
            refs.append(url)
            idx = len(refs) - 1
        label = _KIND_LABEL.get(info.get("kind", "image"), "参考图")
        return f"[{label}{idx + 1}：{name}]"

    resolved = _MENTION_RE.sub(replace, prompt or "")
    return resolved, refs
