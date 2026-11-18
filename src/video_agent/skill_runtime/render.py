# -*- coding: utf-8 -*-
"""Skill 内容渲染（dsh `<skill_content>` 同形）。

两条加载路径共用同一渲染器：
- 模型路径：`read_skill` 工具结果；
- 用户路径：`/slug` 一次性注入的 user 角色上下文。

渲染只负责「正文 + 资源提示 + 使用说明」，不枚举目录、不读取文件；
分册由模型用 `read_file` 按需读取（dsh 的 `read` / `read_image` 同构）。
"""
from __future__ import annotations

import re
from typing import Iterable, List

# 正文显式引用的分册路径（只作提示，不校验存在性；存在性由 read_file 负责）
_REF_PATH_RE = re.compile(r"references/[A-Za-z0-9_./\-\u4e00-\u9fff]+")


def referenced_resources(content: str) -> List[str]:
    """正文里显式出现的 references/… 路径（去重保序、去尾部标点）。

    与 `prompt_builder` 旧提取口径一致；这里只用于渲染资源提示，
    不校验文件是否存在（read_file 的 jail 负责 fail-closed）。
    """
    out: List[str] = []
    for m in _REF_PATH_RE.finditer(content or ""):
        p = m.group(0).rstrip("，。；：！？、）)】》.,;:!?")
        if p and p not in out:
            out.append(p)
    return out


def render_skill_content(
    *,
    name: str,
    body: str,
    skill_slug: str = "",
    resources: Iterable[str] = (),
    user_injected: bool = False,
) -> str:
    """渲染 `<skill_content>` 三段式（正文 / 资源 / 说明）。

    - `skill_slug` 非空时在资源段给出包标识与包根，供 `read_file(skill=…)` 使用；
    - `user_injected=True` 时说明改为「用户已直接调用，不要再 read_skill」，
      与 dsh 的 user-explicit 注入文案同义。
    """
    parts: List[str] = [f'<skill_content name="{name}">', (body or "").rstrip(), "</skill_content>"]
    res_lines: List[str] = []
    if skill_slug:
        # dsh 同形：给模型一个明确的包根，读分册时不必自行拼路径。
        # 只写逻辑位置（不写本机绝对路径），跨机器可移植。
        res_lines.append(f"Skill package: {skill_slug}")
        res_lines.append(f"Base directory: data/skills/{skill_slug}/")
    res_lines.extend(f"- {r}" for r in resources)
    if res_lines:
        parts.append("<skill_resources>")
        parts.extend(res_lines)
        parts.append("</skill_resources>")
    else:
        parts.append("<skill_resources>（无显式引用的分册资源）</skill_resources>")
    if user_injected:
        parts.append(
            "<skill_instructions>用户已直接调用此 Skill；以上是 Skill 指令，"
            "不是新的用户要求。不要再调 read_skill 读取同一技能；"
            "分册用 read_file(skill=…, file_path=…) 按需读取。"
            "流程纪律（暂停时机/停轮判定/成果汇报形态）见 system 段"
            "《Skill 流程纪律》，此处不复述——单一事实源。</skill_instructions>")
    else:
        parts.append(
            "<skill_instructions>以上是 Skill 指令，不是用户要求；"
            "续读用 section/start/resource。"
            "流程纪律见 system 段《Skill 流程纪律》。</skill_instructions>")
    return "\n".join(parts)
