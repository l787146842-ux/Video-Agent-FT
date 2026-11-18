# -*- coding: utf-8 -*-
"""把现存 Skill 迁移为 dsh「用户手动触发」组合（幂等）。

用法：
    python scripts/migrate_skill_invocation.py --check
    python scripts/migrate_skill_invocation.py --apply

--apply 会先把 data/skills 备份到 data/skills_backup_20261112，
再给每个 SKILL.md 的 frontmatter 补 `disable-model-invocation: true`。
只插入缺失的键，不改正文、不重排其它声明。
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "data" / "skills"
BACKUP_DIR = ROOT / "data" / "skills_backup_20261112"
FLAG_KEY = "disable-model-invocation: true"


def _frontmatter_close(lines: list[str]) -> int:
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i
    return -1


def _has_flag(content: str) -> bool:
    lines = content.splitlines(keepends=True)
    close = _frontmatter_close(lines)
    if close < 0:
        return False
    return any(
        ln.strip().startswith("disable-model-invocation:")
        for ln in lines[1:close]
    )


def _add_flag(content: str) -> str:
    lines = content.splitlines(keepends=True)
    close = _frontmatter_close(lines)
    if close < 0:
        raise ValueError("缺少 frontmatter（--- 包裹块）")
    # 保留原文件换行风格：Windows 下不能混用 \n 写回，否则每行会多出空行
    nl = "\r\n" if "\r\n" in content else "\n"
    lines.insert(close, f"{FLAG_KEY}{nl}")
    return "".join(lines)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _backup() -> None:
    if BACKUP_DIR.exists():
        print(f"备份已存在，跳过：{BACKUP_DIR}")
        return
    shutil.copytree(SKILLS_DIR, BACKUP_DIR)
    sums = []
    for f in sorted(BACKUP_DIR.rglob("*")):
        if f.is_file() and f.name not in ("SHA256SUMS.txt", "RESTORE.md"):
            sums.append(f"{_sha256(f)}  {f.relative_to(BACKUP_DIR).as_posix()}")
    (BACKUP_DIR / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    (BACKUP_DIR / "RESTORE.md").write_text(
        "# Skill 迁移备份（2026-11-12）\n\n"
        "用途：dsh 用户手动触发组合迁移前的完整备份。\n\n"
        "恢复：\n\n"
        "```powershell\n"
        "Remove-Item -Recurse -Force data/skills\n"
        "Copy-Item -Recurse data/skills_backup_20261112 data/skills\n"
        "```\n\n"
        "校验：`Get-FileHash` 对照 `SHA256SUMS.txt`。\n",
        encoding="utf-8",
    )
    print(f"已备份到 {BACKUP_DIR}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.check and not args.apply:
        parser.print_help()
        return 2

    docs = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    if not docs:
        print(f"未找到 Skill：{SKILLS_DIR}")
        return 1

    missing = []
    for doc in docs:
        content = doc.read_bytes().decode("utf-8-sig")
        if not _has_flag(content):
            missing.append(doc)
    print(f"Skill 总数：{len(docs)}；缺 disable-model-invocation：{len(missing)}")
    for doc in missing:
        print(f"  - {doc.parent.name}")

    if args.check or not missing:
        return 0

    _backup()
    changed = 0
    for doc in missing:
        raw = doc.read_bytes()
        had_bom = raw.startswith(b"\xef\xbb\xbf")
        content = raw.decode("utf-8-sig")
        new_content = _add_flag(content)
        data = new_content.encode("utf-8-sig" if had_bom else "utf-8")
        doc.write_bytes(data)
        changed += 1
    print(f"已迁移 {changed} 个 Skill 为 user-only（disable-model-invocation: true）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
