"""通用 Markdown 标题解析（Agent Skills 开放标准口径）。

只认 Markdown 标题，不认任何平台私有标签。代码围栏（``` / ~~~）内的
`#` 不算标题。所有区间基于传入原文的字符偏移，`content[start:end]`
即该标题覆盖的整段（含父标题下的子标题）。

本模块是 skill 章节解析的唯一事实源：`read_skill(section=...)` 的章节
匹配、选中注入的标题目录、lint 的标题检查都消费这里。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

_FENCE_RE = re.compile(r"^(```+|~~~+)")
_HEAD_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")


@dataclass(frozen=True)
class SkillHeading:
    """一个 Markdown 标题及其覆盖区间。"""

    level: int
    title: str
    # 标题行起点（含 `#`）
    start: int
    # 标题行之后的正文起点
    body_start: int
    # 本节结束：下一个同级或更高级标题的起点；没有则文末
    end: int
    # 原始标题行（含行尾换行，供注入面原样保留）
    head_line: str


def list_headings(content: str) -> List[SkillHeading]:
    """按出现顺序列出全部 Markdown 标题（跳过代码围栏内容）。"""
    content = content or ""
    lines = content.splitlines(keepends=True)
    found: List[SkillHeading] = []
    offset = 0
    fence: Optional[str] = None
    for raw in lines:
        stripped = raw.strip()
        fm = _FENCE_RE.match(stripped)
        if fm:
            marker = fm.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            offset += len(raw)
            continue
        if fence is None:
            hm = _HEAD_RE.match(raw.rstrip("\r\n"))
            if hm:
                found.append(
                    SkillHeading(
                        level=len(hm.group(1)),
                        title=hm.group(2).strip(),
                        start=offset,
                        body_start=offset + len(raw),
                        end=len(content),
                        head_line=raw,
                    )
                )
        offset += len(raw)
    # 回填 end：下一个同级或更高级标题之前
    for i, h in enumerate(found):
        for nxt in found[i + 1:]:
            if nxt.level <= h.level:
                found[i] = SkillHeading(
                    level=h.level, title=h.title, start=h.start,
                    body_start=h.body_start, end=nxt.start,
                    head_line=h.head_line,
                )
                break
    return found


def outline_headings(content: str, max_level: int = 2) -> List[SkillHeading]:
    """目录用标题：优先取二级标题；没有二级时取最浅一层。

    只有一级标题（或没有标题）时返回空表——单标题文档不需要目录。
    """
    heads = list_headings(content)
    if not heads:
        return []
    level2 = [h for h in heads if h.level == 2]
    if level2:
        return level2
    shallowest = min(h.level for h in heads)
    if shallowest >= 2:
        return [h for h in heads if h.level == shallowest]
    # 仅一级标题：多于一个才认为有目录意义
    h1 = [h for h in heads if h.level == 1]
    return h1 if len(h1) > 1 else []


def outline_lines(content: str, max_level: int = 2) -> List[str]:
    """目录行：`- 标题`（按原文顺序）。"""
    return [f"- {h.title}" for h in outline_headings(content, max_level)]


def find_heading(content: str, title: str) -> Optional[SkillHeading]:
    """按标题文本找章节：先精确（忽略大小写/空白），再子串包含。"""
    wanted = (title or "").strip()
    if not wanted:
        return None
    heads = list_headings(content)
    norm = wanted.casefold().replace(" ", "")
    for h in heads:
        if h.title.casefold().replace(" ", "") == norm:
            return h
    for h in heads:
        if norm and norm in h.title.casefold().replace(" ", ""):
            return h
    return None


def section_text(content: str, title: str) -> Optional[str]:
    """返回标题对应的正文（不含标题行本身，含其子标题）；未命中返回 None。"""
    h = find_heading(content, title)
    if h is None:
        return None
    return content[h.body_start:h.end]


def heading_titles(content: str) -> List[str]:
    """全部标题文本（按出现顺序，含各级）。"""
    return [h.title for h in list_headings(content)]
