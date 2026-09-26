"""按规程重采 skill_sections_golden.json（章节指纹快照）。

用法：python scripts/recut_skill_sections_golden.py [--check]
口径与 tests/unit/test_skill_section_robustness.py 的断言逐字一致
（{chars, head[:40]}）；--check 只比对不写盘（人工核对用）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.video_agent.web.skill_docs import split_skill_sections  # noqa: E402

GOLDEN = ROOT / "tests/fixtures/skill_sections_golden.json"
SKILLS_DIR = ROOT / "data/skills"


def fingerprint() -> dict:
    """采集全部 Skill 的章节指纹（按目录名排序）。"""
    out = {}
    for doc in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        got = split_skill_sections(doc.read_text(encoding="utf-8"))
        out[doc.parent.name] = {
            k: {"chars": len(v), "head": v.strip()[:40]} for k, v in got.items()
        }
    return out


def main() -> int:
    now = fingerprint()
    old = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    diffs = []
    for stem in sorted(set(now) | set(old)):
        a, b = old.get(stem), now.get(stem)
        if a == b:
            continue
        keys = sorted(set(a or {}) | set(b or {}))
        for k in keys:
            av = (a or {}).get(k)
            bv = (b or {}).get(k)
            if av != bv:
                diffs.append("%-24s %-16s %s -> %s" % (
                    stem, k,
                    (av or {}).get("chars", "-"), (bv or {}).get("chars", "-")))
    print("[golden] 差异条目 %d：" % len(diffs))
    for d in diffs:
        print("   ", d)
    if "--check" in sys.argv:
        return 1 if diffs else 0
    # **保留既有快照覆盖范围**（只更新已在快照内的 Skill 指纹）：新增 Skill 是否
    # 纳入快照属测试覆盖面决策（S6 只遍历 golden 的键），不在本批顺手扩面——
    # 磁盘上新增但快照未收的 Skill 在此如实列出，交由后续批次裁决。
    added = sorted(set(now) - set(old))
    if added:
        print("[golden] 磁盘新增但**未纳入**快照（覆盖面决策，本批不动）：%s" % added)
    merged = {stem: now[stem] for stem in sorted(old) if stem in now}
    # 行尾恒为 LF（仓库存储口径）：gitattributes 归一在 Windows 工作区不落盘，
    # 直接 write_text 会产 CRLF，造成整文件 449 行伪 diff（内容未变也全红）。
    text = json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    GOLDEN.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    print("[golden] 已重采 %d 条（保留原覆盖范围）-> %s" % (len(merged), GOLDEN))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
