# -*- coding: utf-8 -*-
"""通用 Skill 结构 lint（2026-11-11 通用化迁移后口径）。

检查项：
  ① 每份 <slug>/SKILL.md 必须有 frontmatter，且含 name/description；
  ② 正文至少有一个二级标题（`## `），否则章节无法被阅读/续读；
  ③ 不得残留旧平台标签独占行（`<planner>` 等）——标签已降为普通文本，
     残留会让作者误以为仍有机制；
  ④ 建议包含「流程/步骤」类二级标题（缺省只告警，不判 FAIL）。

用法：python scripts/check_skill_anchor_lint.py [--dir data/skills]
退出码：PASS 0 / FAIL 1（输出 slug 做 ASCII 转义，GBK 终端不伪装结论）。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.video_agent.skill_runtime import frontmatter  # noqa: E402

_LEGACY_TAG_RE = re.compile(r"^\s*</?([A-Za-z_][A-Za-z0-9_]*)>\s*$")
_H2_RE = re.compile(r"(?m)^##\s+\S")
_FLOW_RE = re.compile(r"(?m)^##\s+[^\n]*(?:流程|步骤)")


def lint_skill_doc(path: pathlib.Path) -> list:
    """返回违规清单（空 = 通过）。"""
    issues = []
    text = path.read_text(encoding="utf-8", errors="replace")
    manifest, body, err = frontmatter.split_frontmatter(text)
    if err:
        issues.append(f"frontmatter parse error: {err}")
    elif not isinstance(manifest, dict):
        issues.append("missing frontmatter (--- name/description ---)")
    else:
        for key in ("name", "description"):
            value = manifest.get(key)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"frontmatter missing required key: {key}")
    if not _H2_RE.search(body or ""):
        issues.append("no level-2 heading (need at least one '## ' section)")
    for lineno, line in enumerate((body or "").splitlines(), 1):
        m = _LEGACY_TAG_RE.match(line)
        if m:
            issues.append(
                f"line {lineno}: legacy tag <{m.group(1)}> (tags are plain text now; remove it)")
    if _H2_RE.search(body or "") and not _FLOW_RE.search(body or ""):
        # 非阻断提示：由调用方决定是否计入（当前只打印，不进 issues）
        pass
    return issues


def main() -> int:
    skills_dir = ROOT / "data" / "skills"
    if "--dir" in sys.argv:
        skills_dir = pathlib.Path(sys.argv[sys.argv.index("--dir") + 1])
    if not skills_dir.is_dir():
        print(f"[check_skill_anchor_lint] FAIL: skills dir missing: {skills_dir}")
        return 1
    total, bad, warn = 0, [], []
    for pkg in sorted(skills_dir.iterdir()):
        doc = pkg / "SKILL.md"
        if not pkg.is_dir() or pkg.name.startswith(".") or not doc.exists():
            continue
        total += 1
        issues = lint_skill_doc(doc)
        if issues:
            bad.append((pkg.name, issues))
        else:
            body = frontmatter.strip_frontmatter(
                doc.read_text(encoding="utf-8", errors="replace"))
            if not _FLOW_RE.search(body or ""):
                warn.append(pkg.name)
    for slug in warn:
        print(f"[check_skill_anchor_lint] WARN "
              f"{slug.encode('ascii', 'backslashreplace').decode()}: "
              "no 'flow/steps' level-2 heading (recommended)")
    if bad:
        for slug, issues in bad:
            print(f"[check_skill_anchor_lint] FAIL {slug.encode('ascii', 'backslashreplace').decode()}:")
            for i in issues:
                print(f"  - {i}")
        print(f"[check_skill_anchor_lint] FAIL: {len(bad)}/{total} skill doc(s) drifted")
        return 1
    print(f"[check_skill_anchor_lint] PASS: {total} skill doc(s), "
          f"frontmatter + headings legal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
