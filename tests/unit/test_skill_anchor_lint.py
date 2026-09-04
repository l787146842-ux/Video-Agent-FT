# -*- coding: utf-8 -*-
"""批 4 · 漂移 lint（V3-3 收窄口径）回归：章节锚点存在性。

- 存量 15 份 skill 全部通过（planner 必备 / 锚点合法 / 开闭配对）；
- 故意改坏一份 skill 的章节锚点 → lint 必须红（拼错锚点 = 解析器
  静默丢段 = 运行时漂移，这就是本 lint 的存在理由）；
- script_analyze 空章节合法（M6）；暂停行/依赖行不做格式检查（V3-3）。
"""
import shutil
from pathlib import Path

from scripts.check_skill_anchor_lint import lint_skill_doc

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"


def test_stock_skills_all_pass_anchor_lint():
    """存量 skill 全绿：锚点合法、planner 在场、开闭配对。"""
    packages = [p for p in sorted(SKILLS_DIR.iterdir())
                if p.is_dir() and not p.name.startswith(".") and (p / "SKILL.md").exists()]
    assert len(packages) >= 15, f"存量 skill 数量异常: {len(packages)}"
    for pkg in packages:
        issues = lint_skill_doc(pkg / "SKILL.md")
        assert issues == [], f"[{pkg.name}] 锚点漂移: {issues}"


def test_broken_anchor_turns_lint_red(tmp_path):
    """故意改坏一份 skill 的章节锚点 → lint 必须红（验收口径）。"""
    src = SKILLS_DIR / "AI-短剧一站式生成" / "SKILL.md"
    work = tmp_path / "broken" / "SKILL.md"
    work.parent.mkdir(parents=True)
    text = src.read_text(encoding="utf-8")
    shutil.copyfile(src, work)
    # 改坏方式一：planner 拼错（流程唯一源丢失）
    (work.parent / "SKILL.md").write_text(
        text.replace("<planner>", "<plannerx>", 1), encoding="utf-8")
    issues = lint_skill_doc(work)
    assert any("missing <planner>" in i for i in issues), issues
    # 改坏方式二：私造未知锚点
    (work.parent / "SKILL.md").write_text(
        text + "\n<storyboard_key_element>\n正文\n</storyboard_key_element>\n",
        encoding="utf-8")
    issues = lint_skill_doc(work)
    assert any("unknown anchor" in i and "storyboard_key_element" in i for i in issues), issues
    # 改坏方式三：未闭合标签
    (work.parent / "SKILL.md").write_text(
        text.replace("</planner>", "", 1), encoding="utf-8")
    issues = lint_skill_doc(work)
    assert any("unclosed" in i for i in issues), issues


def test_empty_script_analyze_is_legal(tmp_path):
    """M6：script_analyze 空章节合法（商品宣传短片形态），不误报。"""
    src = SKILLS_DIR / "商品宣传短片" / "SKILL.md"
    issues = lint_skill_doc(src)
    assert issues == [], f"空分析章节被误伤: {issues}"
