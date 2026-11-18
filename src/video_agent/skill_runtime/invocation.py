# -*- coding: utf-8 -*-
"""Skill 调用策略（dsh 四组合）与用户 `/slug` 手势解析。

dsh 事实（`docs/subsystems/skills.md` + `tool-skill/README.md`）：
- `modelInvocable` / `userInvocable` 两个正向布尔，四组合全保留；
- 用户 `/name` 由 pre-step listener 扫描真正的用户消息，命中
  `userInvocable=true` 的技能后，把完整 `<skill_content>` 作为 user 角色
  上下文一次性注入；不调用 skill 工具；同一消息内重复只注入一次；
- 未知名字、用户禁用技能保持普通文本。

本项目保留四组合，现存技能通过 frontmatter 设为 user-only。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime.render import (
    referenced_resources,
    render_skill_content,
)

# 空白分隔的 /slug；`(?<!\S)` 保证前面是行首或空白，避免把 `a/b` 当命令。
# slug 允许中文（现有目录名）、字母、数字、下划线、连字符、点。
_SLUG_TOKEN_RE = re.compile(r"(?<!\S)/([^\s/]+)")

# token 尾部常见标点（用户直接写在句子里时）——只剥尾部，不改中间字符。
_TOKEN_TRAIL = "，。；：！？、）)】》.,;:!?\"'“”‘’"


def extract_slug_tokens(text: str) -> List[str]:
    """提取用户消息中的 `/slug` token（去重保序）。"""
    out: List[str] = []
    for m in _SLUG_TOKEN_RE.finditer(str(text or "")):
        token = m.group(1).rstrip(_TOKEN_TRAIL).strip()
        if token and token not in out:
            out.append(token)
    return out


def _norm(s: str) -> str:
    return (
        (s or "").strip().casefold()
        .replace(" ", "").replace("-", "").replace("_", "")
        .replace(".md", "").replace(".txt", "")
    )


def resolve_user_skill(token: str) -> Optional[registry.SkillEntry]:
    """把 `/slug` token 解析为 user-invocable 的可加载技能。

    只做精确 slug/name 与归一化相等匹配；不做包含匹配，避免
    `/短剧` 误命中长名字技能。未知/停用/模型专用一律返回 None，
    由调用方保持普通文本。
    """
    token = (token or "").strip()
    if not token:
        return None
    entries = registry.user_catalog_entries()
    for e in entries:
        if token == e.slug or token == e.name:
            return e
    wn = _norm(token)
    if not wn:
        return None
    for e in entries:
        if wn in (_norm(e.slug), _norm(e.name)):
            return e
    return None


def build_user_skill_content(entry: registry.SkillEntry) -> str:
    """渲染用户 `/slug` 一次性注入块（完整正文 + 资源提示 + 说明）。"""
    body = str(entry.content or "").strip()
    return render_skill_content(
        name=entry.name,
        body=body,
        skill_slug=entry.slug,
        resources=referenced_resources(body),
        user_injected=True,
    )


def resolve_user_skills(text: str) -> List[registry.SkillEntry]:
    """扫描用户消息，返回按出现顺序去重的 user-invocable 技能列表。"""
    out: List[registry.SkillEntry] = []
    seen: set = set()
    for token in extract_slug_tokens(text):
        entry = resolve_user_skill(token)
        if entry is None or entry.slug in seen:
            continue
        seen.add(entry.slug)
        out.append(entry)
    return out


def render_user_skills(text: str) -> Tuple[List[registry.SkillEntry], str]:
    """返回 (命中的技能列表, 一次性注入正文)。

    多个技能按出现顺序拼接；同一技能只注入一次；未命中不产生内容。
    """
    entries = resolve_user_skills(text)
    if not entries:
        return [], ""
    return entries, "\n\n".join(build_user_skill_content(e) for e in entries)
