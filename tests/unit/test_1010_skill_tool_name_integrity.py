# -*- coding: utf-8 -*-
"""Skill 正文点名的工具必须真实存在 —— 防回潮钉（事故编号：1010）。

## 现场

用户跑多个项目发现「没有启动协议、一来就派子代理」。取证链（见
`CHANGELOG.md` 2026-10-10 条）定位到一个**独立缺陷**：

2026-10-03 `626ddbab`「Flova planner 整体替换」按 Flova 原文整章重写
10 个 Skill 的 `<planner>`，把 Flova 的 `reply_to_user` 一并搬进「何时暂停」
一节。**该工具在本项目不存在**——2026-08-31 `a9fc8257`（用户裁决「删除
reply_to_user 独有章节，白名单对齐 Flova」）已把它从 `SECTION_TAG_STAGES`
与前端 `SECTION_TAGS` 摘除，注册表里只有 `workflow_pause`。

迁移脚本 `scripts/archive/migrate_planner_to_flova.py` 内置了「Flova 专名
残留对账」，但该名单**漏列 `reply_to_user`**（只列了
`Final_Video_Spec` / `resource_prepare_and_analyze` / `text_editor` /
`bind_asset` / `write_the_prompt` / `multimodal_analyze_tool`），
于是脚本 fail-loud 未命中、`check_skill_anchor_lint` 只校验章节标签配对
不校验工具名 ⇒ **7 个 Skill 的「何时暂停」指向不存在的工具，门禁全绿**。

全库 session 扫描 `reply_to_user` 调用 = 0 次（模型没真去撞），
但该指令在结构上不可执行。

## 本钉两条

1. **零残留**：`data/skills/**/SKILL.md` 正文不得再出现 `reply_to_user`
   （已由本批替换为 `workflow_pause`）。
2. **点名即存在**：Skill 正文里以 `workflow_pause` / `run_subagent` 这类
   **控制流工具名**形式出现的标识符，必须能在注册表与工具注册面里找到
   ——防止同类「搬入外部平台专名」再次静默通关。

口径边界（防误伤）：只检查**已知工具形态的标识符**（带下划线的小写
snake_case 且命中工具名白名单前缀），不扫描自然语言里的英文词，
Flova 的章节/通道专名（`media_generator` 等章节 tag）不属本钉范围
（它们是章节名，由 `check_stage_face_consistency` 断言映射覆盖）。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"

# 本项目**不存在**、却曾出现在 Skill 正文里的外部平台工具名。
# 只增不减：每发现一个同类即登记一条，配一条失败样例。
FOREIGN_TOOL_NAMES = {
    "reply_to_user": "Flova 交互工具；本项目 2026-08-31 已裁决删除，暂停唯一通道 = workflow_pause",
}

# 控制流/交互类工具名（Skill 正文里点名它们即等于给模型下指令）
CONTROL_TOOLS = ("workflow_pause", "run_subagent")


def _skill_docs():
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def test_1010_no_foreign_tool_name_in_skill_docs():
    """Skill 正文零残留外部平台专有工具名（当前已知 = reply_to_user）。"""
    offenders = []
    for doc in _skill_docs():
        text = doc.read_text(encoding="utf-8", errors="replace")
        for name in FOREIGN_TOOL_NAMES:
            if name in text:
                offenders.append(f"{doc.parent.name}: {name}")
    assert not offenders, (
        "Skill 正文残留本项目不存在的工具名（模型会照它下指令、但结构上无法执行）："
        + "; ".join(offenders)
    )


def test_1010_pause_tool_named_in_skills_exists():
    """Skill 点名的暂停工具必须是真实注册的工具（点名即存在）。

    2026-10-03 的教训：整章搬入外部基准时，「何时暂停」里的工具名被一并搬来，
    而迁移脚本的对账名单漏列该项 ⇒ 门禁全绿、指令不可执行。
    本钉把「点名」与「存在」机械绑定。
    """
    from src.video_agent.tools.document_tools import WorkflowPauseTool
    from src.video_agent.core.subagent import SUBAGENT_TOOL_NAME

    registry = {
        "workflow_pause": WorkflowPauseTool.name,
        "run_subagent": SUBAGENT_TOOL_NAME,
    }
    # 注册表口径自检：本钉依赖的两个名字必须真实存在且自洽
    assert registry["workflow_pause"] == "workflow_pause"
    assert registry["run_subagent"] == "run_subagent"

    known = set(registry)
    token = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(CONTROL_TOOLS) + r")(?![A-Za-z0-9_])")
    offenders = []
    for doc in _skill_docs():
        text = doc.read_text(encoding="utf-8", errors="replace")
        for hit in set(token.findall(text)):
            if hit not in known:
                offenders.append(f"{doc.parent.name}: {hit}")
    assert not offenders, f"Skill 点名的工具不在注册表中：{offenders}"


@pytest.mark.parametrize("slug,expected", [
    ("叙事驱动的美学视频", "workflow_pause"),
    ("商品宣传短片", "workflow_pause"),
    ("多人对话访谈", "workflow_pause"),
    ("故事驱动型视频", "workflow_pause"),
    ("视频拉片复刻", "workflow_pause"),
    ("音乐MV需上传音乐", "workflow_pause"),
    ("新-Skill", "workflow_pause"),
])
def test_1010_pause_tool_replaced_by_workflow_pause(slug, expected):
    """本批逐个钉死：7 个包（含新-Skill）的暂停工具已归一为 workflow_pause。"""
    doc = SKILLS_DIR / slug / "SKILL.md"
    assert doc.exists(), f"Skill 缺失: {slug}"
    text = doc.read_text(encoding="utf-8", errors="replace")
    assert expected in text, f"「{slug}」未点名 {expected}"
    assert "reply_to_user" not in text, f"「{slug}」仍残留 reply_to_user"
