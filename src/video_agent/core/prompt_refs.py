"""
提示词 @引用解析 — 把提示词中的 @名称 映射为实际媒体素材。

前端 PromptEditor 允许用户在提示词里输入 @ 引用参考素材/故事板媒体，
序列化为 "@名称" 文本。生成（出图/出视频）时模型无法理解 "@名称"，
本模块负责：
1. 从故事板状态构建 名称 → (url, kind) 映射（关键元素分组标题 / 草稿 label / 文件名）；
2. 扫描提示词中的 @名称，把被引用但不在参考列表里的素材自动纳入参考列表；
3. 把 @名称 重写为带序号的位置标记（如 [参考图2：Element_月球]），
   让多模态模型精确知道第 N 张参考图对应提示词里的哪个元素。
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS

# @提及匹配：半角 @ 或全角 ＠ + 非空白/非@字符
_MENTION_RE = re.compile(r"[@＠]([^\s@＠]+)")

_KIND_LABEL = {"image": "参考图", "video": "参考视频", "audio": "参考音频"}


def media_of_draft(d: Dict[str, Any]) -> Tuple[str, str]:
    """取草稿的主媒体 (url, kind)：按 mediaType 优先，其次按已有字段兜底"""
    kind = (d.get("mediaType") or "image").lower()
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
    - 关键元素：分组 title（如 Element_月球）
    - 所有草稿：label
    - URL 文件名（兜底，与前端 refAssetName 的文件名规则一致）
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
                        put(g.get("title", ""), url, kind)
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
        name = m.group(1)
        info = media_map.get(name)
        if not info:
            return name  # 未命中：去掉 @，保留文字
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
