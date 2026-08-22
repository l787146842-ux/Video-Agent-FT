# -*- coding: utf-8 -*-
"""原料闸 v3 判定家族（requires_inputs 声明消费，任务#35 B2）。

frontmatter v3 `requires_inputs` 声明优先于 v2 `flow.script_required`，两路语义
不叠加（声明了 v3 清单就只按清单判定；未声明回落 script_required 旧路径，
未迁移 manifest 行为零变化）。

客观满足判定（无创作空间，机器一眼可判）：
- script：同 gates_script.script_present（uploadedDocs 或 analysis 摘要）；
- doc：uploadedDocs 登记或 assets 文档类登记；
- music/video/image：assets 登记的 type 别名命中，或 url/名称扩展名命中。
"""
from pathlib import Path
from typing import Any, Dict, List

# 顺序敏感：先完整加载 prompt_gates（其尾块 re-export 会连带加载 gates_script），
# 再取 gates_script 符号——反向首入会在尾块处撞上半初始化模块
from src.video_agent.core import prompt_gates  # noqa: F401
from src.video_agent.core.gates_script import script_present
from src.video_agent.skill_runtime import registry

# 原料类型中文标签（提醒文案与元数据头共用，单一表述源）
INPUT_TYPE_LABELS: Dict[str, str] = {
    "script": "剧本",
    "music": "音乐",
    "video": "视频",
    "image": "图片",
    "doc": "文档",
}

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# assets 登记项 type 字段（前端附件 kind）的归一别名
_ASSET_TYPE_ALIASES: Dict[str, tuple] = {
    "music": ("music", "audio"),
    "video": ("video",),
    "image": ("image", "photo"),
    "doc": ("doc", "document", "file", "text"),
}
_TYPE_EXTS: Dict[str, set] = {
    "music": _AUDIO_EXTS,
    "video": _VIDEO_EXTS,
    "image": _IMAGE_EXTS,
}


def _asset_hit(state: Dict[str, Any], input_type: str) -> bool:
    """assets 登记列表中是否存在指定类型的素材（type 别名或扩展名命中）。"""
    aliases = _ASSET_TYPE_ALIASES.get(input_type, ())
    exts = _TYPE_EXTS.get(input_type, set())
    for a in (state or {}).get("assets") or []:
        if not isinstance(a, dict):
            continue
        t = str(a.get("type") or "").strip().lower()
        if aliases and t in aliases:
            return True
        if exts:
            suffix = Path(str(a.get("url") or a.get("name") or "")).suffix.lower()
            if suffix in exts:
                return True
    return False


def input_present(state: Dict[str, Any], input_type: str) -> bool:
    """某类原料是否已客观就绪（白名单外类型保守视为已满足，不误拦）。"""
    if input_type == "script":
        return script_present(state)
    if input_type == "doc":
        return bool((state or {}).get("uploadedDocs")) or _asset_hit(state, "doc")
    if input_type in _TYPE_EXTS:
        return _asset_hit(state, input_type)
    return True


def missing_required_inputs(
    state: Dict[str, Any], skill: str,
) -> List[Dict[str, Any]]:
    """v3 声明中 required 且客观未满足的原料项清单。

    读取路径经 registry.skill_requires_inputs（测试 patch 目标）；
    未声明/全部已满足返回空表。"""
    out: List[Dict[str, Any]] = []
    for item in registry.skill_requires_inputs(skill):
        if item.get("required") and not input_present(state, item.get("type") or ""):
            out.append(item)
    return out


def input_remind_message(missing: List[Dict[str, Any]]) -> str:
    """非剧本类（或混合）原料缺失的提醒文案（声明带 hint 优先用 hint）。"""
    parts: List[str] = []
    for m in missing or []:
        label = INPUT_TYPE_LABELS.get(str(m.get("type") or ""), str(m.get("type") or ""))
        hint = str(m.get("hint") or "").strip()
        parts.append(hint or f"本 Skill 需要{label}素材，尚未检测到上传/登记")
    return (
        "原料未就绪：" + "；".join(parts)
        + "。请先提供相应素材，素材到达后继续推进。"
    )
