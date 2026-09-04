# -*- coding: utf-8 -*-
"""Skill 章节锚点漂移 lint（Skill 流程跑通修复批 4 · V3-3 收窄后口径）。

只管一处：章节锚点存在性——
  ① 每份 <slug>/SKILL.md 必须有 <planner>（流程唯一源，渐进式披露按它取段）；
  ② 正文出现的 <tag> 锚点必须在合法词表内（SECTION_TAG_STAGES 键集，
     含源平台兼容别名）——拼错/私造锚点 = 解析器静默丢段 = 运行时漂移；
  ③ 每个 <tag> 必须有配对 </tag>（split_skill_sections 依赖闭合对）。
「何时暂停：」行与「依赖关系：」行均不做格式检查（暂停行 9 种写法必误报，
依赖行有散文体异类——V3-3 用户裁决）。
script_analyze 章节允许为空（M6：无分析轴的 skill 合法，如商品宣传短片）。

用法：python scripts/check_skill_anchor_lint.py [--dir data/skills]
退出码：PASS 0 / FAIL 1（输出 slug 做 ASCII 转义，GBK 终端不伪装结论）。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.video_agent.web.skill_docs import SECTION_TAG_STAGES  # noqa: E402

VALID_TAGS = set(SECTION_TAG_STAGES.keys())
_OPEN_TAG_RE = re.compile(r"^\s*<([A-Za-z_][A-Za-z0-9_]*)>\s*$")
_CLOSE_TAG_RE = re.compile(r"^\s*</([A-Za-z_][A-Za-z0-9_]*)>\s*$")


def lint_skill_doc(path: pathlib.Path) -> list:
    """返回违规清单（空 = 通过）。"""
    issues = []
    text = path.read_text(encoding="utf-8", errors="replace")
    opens, closes = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        m = _OPEN_TAG_RE.match(line)
        if m:
            opens.append((lineno, m.group(1)))
        m = _CLOSE_TAG_RE.match(line)
        if m:
            closes.append((lineno, m.group(1)))
    tags = [t for _, t in opens]
    if "planner" not in tags:
        issues.append("missing <planner> section (flow source of truth)")
    for lineno, t in opens:
        if t not in VALID_TAGS:
            issues.append(f"line {lineno}: unknown anchor <{t}> "
                          f"(not in SECTION_TAG_STAGES; typo = silent section drop)")
    open_counts = {}
    for _, t in opens:
        open_counts[t] = open_counts.get(t, 0) + 1
    close_counts = {}
    for _, t in closes:
        close_counts[t] = close_counts.get(t, 0) + 1
    for t, n in open_counts.items():
        if close_counts.get(t, 0) != n:
            issues.append(f"<{t}> unclosed: {n} open vs {close_counts.get(t, 0)} close")
    for t, n in close_counts.items():
        if open_counts.get(t, 0) == 0:
            issues.append(f"</{t}> without opening tag")
    return issues


def main() -> int:
    skills_dir = ROOT / "data" / "skills"
    if "--dir" in sys.argv:
        skills_dir = pathlib.Path(sys.argv[sys.argv.index("--dir") + 1])
    if not skills_dir.is_dir():
        print(f"[check_skill_anchor_lint] FAIL: skills dir missing: {skills_dir}")
        return 1
    total, bad = 0, []
    for pkg in sorted(skills_dir.iterdir()):
        doc = pkg / "SKILL.md"
        if not pkg.is_dir() or pkg.name.startswith(".") or not doc.exists():
            continue
        total += 1
        issues = lint_skill_doc(doc)
        if issues:
            bad.append((pkg.name, issues))
    if bad:
        for slug, issues in bad:
            print(f"[check_skill_anchor_lint] FAIL {slug.encode('ascii', 'backslashreplace').decode()}:")
            for i in issues:
                print(f"  - {i}")
        print(f"[check_skill_anchor_lint] FAIL: {len(bad)}/{total} skill doc(s) drifted")
        return 1
    print(f"[check_skill_anchor_lint] PASS: {total} skill doc(s), all anchors legal & paired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
