# -*- coding: utf-8 -*-
"""通用 Skill 结构 lint 回归（2026-11-11 去标签口径）。

- 存量 16 份 skill 全部通过（frontmatter + 至少一个二级标题）；
- 故意改坏 frontmatter / 删光标题 / 残留旧标签 → lint 必须红；
- 只有「制作流程」一节的最小 skill 合法。
"""
import shutil
from pathlib import Path

from scripts.check_skill_anchor_lint import lint_skill_doc

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"


def test_stock_skills_all_pass_anchor_lint():
    """存量 skill 全绿：frontmatter 合法、有二级标题、无残留标签。"""
    packages = [p for p in sorted(SKILLS_DIR.iterdir())
                if p.is_dir() and not p.name.startswith(".") and (p / "SKILL.md").exists()]
    assert len(packages) >= 15, f"存量 skill 数量异常: {len(packages)}"
    for pkg in packages:
        issues = lint_skill_doc(pkg / "SKILL.md")
        assert issues == [], f"[{pkg.name}] 结构漂移: {issues}"


def test_broken_frontmatter_turns_lint_red(tmp_path):
    src = SKILLS_DIR / "AI-短剧一站式生成" / "SKILL.md"
    work = tmp_path / "broken" / "SKILL.md"
    work.parent.mkdir(parents=True)
    text = src.read_text(encoding="utf-8")
    # 改坏方式一：删掉 description
    work.write_text(
        text.replace("description:", "desc_broken:", 1), encoding="utf-8")
    issues = lint_skill_doc(work)
    assert any("description" in i for i in issues), issues


def test_no_heading_turns_lint_red(tmp_path):
    work = tmp_path / "nohead" / "SKILL.md"
    work.parent.mkdir(parents=True)
    work.write_text(
        "---\nname: nohead\ndescription: 测试\n---\n只有正文，没有二级标题。\n",
        encoding="utf-8")
    issues = lint_skill_doc(work)
    assert any("no level-2 heading" in i for i in issues), issues


def test_legacy_tag_turns_lint_red(tmp_path):
    work = tmp_path / "legacy" / "SKILL.md"
    work.parent.mkdir(parents=True)
    shutil.copyfile(SKILLS_DIR / "AI-短剧一站式生成" / "SKILL.md", work)
    work.write_text(
        work.read_text(encoding="utf-8") + "\n<planner>\n残留标签\n</planner>\n",
        encoding="utf-8")
    issues = lint_skill_doc(work)
    assert any("legacy tag" in i and "planner" in i for i in issues), issues


def test_minimal_flow_skill_is_legal(tmp_path):
    work = tmp_path / "minimal" / "SKILL.md"
    work.parent.mkdir(parents=True)
    work.write_text(
        "---\nname: minimal\ndescription: 最小流程\n---\n"
        "# minimal\n\n## 制作流程\n先做什么，再做什么。\n",
        encoding="utf-8")
    assert lint_skill_doc(work) == []
