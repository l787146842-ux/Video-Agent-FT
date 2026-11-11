# -*- coding: utf-8 -*-
"""【已退役 · 仅供考古】一次性迁移：Flova 标签章节 → 通用 Markdown 标题式 Skill。

⚠ 2026-11-11 起**不要再用本脚本处理存量 Skill**：它把「体量 ≥ 15000 字符才拆
references/」写成了硬编码阈值，这正是「16 包里只有 3 个拆出分册、且那 3 个包的
分册指针全部落在注入预算之外」的根因。现行形态是 Flova 六节骨架 + **每个包
统一三本分册**（媒体生成/提示词写作/剪辑交付），由创作助手契约与
`lint_skill_content` 的注入预算校验共同维持，见 `ARCHITECTURE_RULES.md` §2.8。

用法（仅历史参考）：
    python scripts/migrate_skills_to_generic.py --dry-run
    python scripts/migrate_skills_to_generic.py --apply
    python scripts/migrate_skills_to_generic.py --only "AI-短剧一站式生成" --apply

规则：
- 标签章节（<planner>/<script_analyze>/…）→ 固定中文标题；
- `→ **tag**` 箭头（旧 Flova 的章节指针）删除，不保留任何标签语义；
- 只保留通用 frontmatter（name/description/version/source/metadata/license/x-*），
  flow/pause/scripts/resources/schema_version 丢弃；
- ~~体量 ≥ 15000 字符的主文档，把「媒体生成」「提示词写法」拆到 references/~~（已废）；
- apply 前必须存在 data/skills_backup_20261111（整体备份）。

状态：2026-11-11 标签迁移已完成（16 份）；同日后续批已把全部 16 包重写为
Flova 六节骨架并统一拆出三本分册，本脚本的拆分规则随之作废，仅留作历史记录。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "data" / "skills"
BACKUP_DIR = ROOT / "data" / "skills_backup_20261111"
REPORT_PATH = ROOT / "reports" / "skill-generic-migration-20261111.md"

sys.path.insert(0, str(ROOT))

from src.video_agent.skill_runtime import frontmatter  # noqa: E402
from src.video_agent.utils.fileio import atomic_write_text  # noqa: E402
from src.video_agent.web.skill_docs import list_skill_sections  # noqa: E402

# 标签 → 通用章节标题（None = 该标签不是章节，忽略）
TAG_SECTION: Dict[str, str] = {
    "planner": "制作流程",
    "script_analyze": "剧本分析",
    "multimodal_analyze_tool": "剧本分析",
    "resource_prepare_and_analyze": "剧本分析",
    "text_editor": "规格与文档",
    "storyboard_designer": "故事板设计",
    "storyboard_key_elements": "故事板设计",
    "storyboard_shots": "故事板设计",
    "storyboard_audio": "故事板设计",
    "media_generator": "媒体生成",
    "generation": "媒体生成",
    "image_generate": "媒体生成",
    "generate_video": "媒体生成",
    "audio_generate": "媒体生成",
    "write_media_prompt": "提示词写法",
    "write_the_prompt": "提示词写法",
    "video_assembler": "组装导出",
}

SECTION_ORDER = (
    "制作流程", "剧本分析", "规格与文档", "故事板设计",
    "媒体生成", "提示词写法", "组装导出",
)

# 真实工具名：正文里出现时保留，不当作旧章节名替换
REAL_TOOL_NAMES = {
    "script_analyze", "image_generate", "generate_video",
    "audio_generate", "video_assembler", "document_write",
    "read_uploaded_doc", "read_project_doc", "read_skill",
    "storyboard_create_group", "storyboard_patch_draft",
}

DROP_FRONTMATTER_KEYS = {"flow", "pause", "scripts", "resources", "schema_version"}
KEEP_FRONTMATTER_KEYS = {"name", "description", "version", "source", "metadata", "license"}
CN_NUMS = "一二三四五六七八九十"

_TAG_RE = re.compile(r"(?ms)^<([A-Za-z_]+)>\s*$(.*?)^</\1>\s*$")
_ARROW_RE = re.compile(
    r"[ \t]*→[ \t]*\*\*(?:" + "|".join(sorted(TAG_SECTION)) + r")\*\*[ \t]*[。.]?")


def split_tags(body: str) -> Tuple[str, List[Tuple[str, str]]]:
    """返回 (首个标签前的前言, [(tag, 正文)])。"""
    matches = list(_TAG_RE.finditer(body or ""))
    if not matches:
        return body or "", []
    preamble = body[:matches[0].start()]
    out = [(m.group(1).lower(), m.group(2).strip()) for m in matches]
    return preamble, out


# 裸 tag 名（非真实工具）：迁移后正文里仍可能出现，统一换成中文标题
BARE_TAG_TITLES: Dict[str, str] = {
    "media_generator": "媒体生成",
    "write_media_prompt": "提示词写法",
    "write_the_prompt": "提示词写法",
    "storyboard_designer": "故事板设计",
    "storyboard_key_elements": "故事板设计",
    "storyboard_shots": "故事板设计",
    "storyboard_audio": "故事板设计",
    "multimodal_analyze_tool": "剧本分析",
    "resource_prepare_and_analyze": "剧本分析",
    "text_editor": "规格与文档",
}

# 旧章节指针箭头（只删指向非工具章节的，指向真实工具的保留）
_BARE_ARROW_RE = re.compile(
    r"[ \t]*→[ \t]*(?:" + "|".join(sorted(BARE_TAG_TITLES)) + r")[ \t]*[。.]?")


_TOP_SECTION_RE = re.compile(r"^##\s+[一二三四五六七八九十]+、")


def demote_nested_headings(text: str) -> str:
    """把顶层章节内部的 `##`/`###` 整体降一级，避免正文子标题变成兄弟章节。"""
    lines = []
    in_body = False
    for line in (text or "").splitlines():
        if _TOP_SECTION_RE.match(line):
            in_body = True
            lines.append(line)
            continue
        if in_body and re.match(r"^#{2,5}\s+", line):
            lines.append("#" + line)
            continue
        lines.append(line)
    return "\n".join(lines)


def _demote_all(text: str) -> str:
    """章节正文内的标题整体降一级（用于首次迁移，避免子标题变兄弟章节）。"""
    return re.sub(r"(?m)^(#{2,5})\s+", lambda m: "#" + m.group(0), text or "")


def clean_section(text: str) -> str:
    """删旧箭头 + 把非工具名的章节 tag 引用换成中文标题。"""
    text = text or ""
    text = _BARE_ARROW_RE.sub("", text)
    text = _ARROW_RE.sub("", text)
    text = text.replace("「媒体提示词」", "「提示词写法」")
    for tag, title in TAG_SECTION.items():
        text = text.replace(f"<{tag}>", f"「{title}」")
        text = text.replace(f"</{tag}>", "")
        if tag in REAL_TOOL_NAMES:
            continue
        text = text.replace(f"**{tag}**", title)
    # 裸 tag 名（词边界，避免误伤 identifier）
    for tag, title in BARE_TAG_TITLES.items():
        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(tag)}(?![A-Za-z0-9_])", title, text)
    # script_analyze 是真实工具；只有“X 分区/章节/部分”才是旧章节引用
    text = re.sub(
        r"(?<![A-Za-z0-9_])script_analyze(?=\s*(?:分区|章节|部分))",
        "剧本分析", text)
    return text.strip()


def build_doc(slug: str, raw: str) -> Tuple[str, Dict[str, object]]:
    manifest, body, err = frontmatter.split_frontmatter(raw)
    if err:
        raise ValueError(f"frontmatter 解析失败：{err}")
    manifest = manifest or {}
    name = str(manifest.get("name") or slug).strip()
    desc = str(manifest.get("description") or "").strip()

    preamble, tags = split_tags(body)
    grouped: Dict[str, List[str]] = {}
    for tag, text in tags:
        section = TAG_SECTION.get(tag)
        if not section:
            continue
        cleaned = clean_section(text)
        if cleaned:
            grouped.setdefault(section, []).append(cleaned)

    intro = desc
    preamble = clean_section(preamble)
    if preamble:
        intro = (intro + "\n\n" + preamble).strip()

    blocks: List[Tuple[str, str]] = []
    if intro:
        blocks.append(("这个 Skill 做什么", _demote_all(intro)))
    for section in SECTION_ORDER:
        parts = grouped.get(section) or []
        if parts:
            blocks.append((section, _demote_all("\n\n".join(parts))))

    # 体量控制：大包把媒体生成/提示词写法拆到 references/
    refs: List[str] = []
    body_chars = sum(len(t) for _, t in blocks)
    if body_chars >= 15000:
        for section, filename in (("媒体生成", "媒体生成.md"),
                                  ("提示词写法", "提示词写作.md")):
            for i, (title, text) in enumerate(blocks):
                if title != section or len(text) < 3000:
                    continue
                refs.append(filename)
                pointer = f"需要时读 `references/{filename}`。"
                if section == "媒体生成":
                    pointer = ("需要选模型、绑参考图、生成音频时，"
                               f"读 `references/{filename}`。")
                elif section == "提示词写法":
                    pointer = f"写三视图/四视图/表格图/视频提示词时，读 `references/{filename}`。"
                blocks[i] = (section, pointer)

    # 已有 references/ 也列入参考资料
    refs_dir = SKILLS_DIR / slug / "references"
    existing = []
    if refs_dir.is_dir():
        existing = sorted(
            p.name for p in refs_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".md", ".txt"}
        )
    all_refs = list(dict.fromkeys(refs + existing))
    if all_refs:
        lines = "\n".join(f"- `references/{n}`" for n in all_refs)
        blocks.append(("参考资料", "需要细节时读取对应分册：\n\n" + lines))

    lines = [f"# {name}", ""]
    for i, (title, text) in enumerate(blocks):
        lines.append(f"## {CN_NUMS[i]}、{title}")
        lines.append("")
        lines.append(text.strip())
        lines.append("")
    doc_body = "\n".join(lines).rstrip() + "\n"

    keep = {}
    for k, v in manifest.items():
        if k in DROP_FRONTMATTER_KEYS:
            continue
        if k in KEEP_FRONTMATTER_KEYS or str(k).startswith("x-"):
            keep[k] = v
    keep["name"] = name
    keep["description"] = desc
    # name/description 置顶
    ordered = {"name": name, "description": desc}
    for k, v in keep.items():
        if k not in ordered:
            ordered[k] = v
    doc = frontmatter.render_frontmatter(ordered) + doc_body
    meta = {
        "name": name,
        "old_chars": len(raw),
        "new_chars": len(doc),
        "sections": [t for t, _ in blocks],
        "refs": refs,
        "existing_refs": existing,
        "dropped": sorted(k for k in manifest if k not in ordered),
    }
    return doc, meta


def iter_skill_files(only: str = ""):
    for p in sorted(SKILLS_DIR.iterdir(), key=lambda x: x.name):
        if not p.is_dir() or p.name.startswith("."):
            continue
        main = p / frontmatter.SKILL_DOC_NAME
        if not main.exists():
            continue
        if only and p.name != only:
            continue
        yield p.name, main


def _iter_md_files(only: str = ""):
    for slug, main in iter_skill_files(only):
        yield slug, main
        refs = main.parent / "references"
        if refs.is_dir():
            for p in sorted(refs.glob("*.md")):
                yield slug, p


def run_cleanup(only: str = "") -> int:
    """对已迁移文档做二次清理：删残留旧章节名/箭头（幂等）。"""
    if not BACKUP_DIR.is_dir():
        print(f"[FAIL] 缺少整体备份目录：{BACKUP_DIR}")
        return 2
    changed = 0
    for slug, path in _iter_md_files(only):
        raw = path.read_text(encoding="utf-8-sig")
        manifest, body, err = frontmatter.split_frontmatter(raw)
        if err:
            print(f"[FAIL] {slug}/{path.name}: {err}")
            continue
        cleaned = clean_section(body)
        new = (frontmatter.render_frontmatter(manifest) + cleaned + "\n"
               if manifest else cleaned + "\n")
        if new != raw:
            atomic_write_text(path, new)
            changed += 1
            print(f"[CLEAN] {slug}/{path.name}")
    if changed:
        from src.video_agent.skill_runtime.registry import sync_all
        sync_all()
    print(f"[OK] 清理文件：{changed}")
    return 0


def run_demote(only: str = "") -> int:
    """一次性：把旧正文里的 `##` 子标题降为 `###`（幂等，按“非顶层 ##”判定）。"""
    changed = 0
    for slug, path in iter_skill_files(only):
        raw = path.read_text(encoding="utf-8-sig")
        manifest, body, err = frontmatter.split_frontmatter(raw)
        if err:
            print(f"[FAIL] {slug}: {err}")
            continue
        needs = any(
            re.match(r"^##\s+", line) and not _TOP_SECTION_RE.match(line)
            for line in body.splitlines()
        )
        if not needs:
            continue
        new_body = demote_nested_headings(body)
        new = (frontmatter.render_frontmatter(manifest) + new_body + "\n"
               if manifest else new_body + "\n")
        atomic_write_text(path, new)
        changed += 1
        print(f"[DEMOTE] {slug}")
    if changed:
        from src.video_agent.skill_runtime.registry import sync_all
        sync_all()
    print(f"[OK] 降级文件：{changed}")
    return 0


def run_report(only: str = "") -> int:
    """按当前磁盘状态生成迁移报告（不改文件）。"""
    rows = []
    for slug, main in iter_skill_files(only):
        raw = main.read_text(encoding="utf-8-sig")
        manifest, body, _ = frontmatter.split_frontmatter(raw)
        refs_dir = main.parent / "references"
        refs = sorted(p.name for p in refs_dir.glob("*.md")) if refs_dir.is_dir() else []
        rows.append({
            "slug": slug,
            "name": str((manifest or {}).get("name") or slug),
            "chars": len(body),
            "sections": len(list_skill_sections(body)),
            "refs": refs,
        })
    lines = [
        "# Skill 通用化迁移报告（2026-11-11）",
        "",
        f"- 迁移后 Skill 数：{len(rows)}",
        "- 备份目录：`data/skills_backup_20261111`",
        "- 格式：frontmatter(name/description) + Markdown 标题式主文档 + references/ 分册",
        "",
        "| Skill | 正文字数 | 章节数 | 分册 |",
        "| --- | ---: | ---: | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['chars']} | {r['sections']} | "
            f"{'、'.join(r['refs']) or '—'} |")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(REPORT_PATH, "\n".join(lines) + "\n")
    print(f"[OK] 已写报告：{REPORT_PATH}（{len(rows)} 份）")
    return 0


def _install_ports_once() -> None:
    """脚本入口装配 core 端口（幂等）；sync_all 需要 skill_docs 端口。"""
    from src.video_agent.web.port_wiring import install_core_ports
    install_core_ports()


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--cleanup", action="store_true")
    mode.add_argument("--demote", action="store_true")
    mode.add_argument("--report-only", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    _install_ports_once()
    if args.cleanup:
        return run_cleanup(args.only)
    if args.demote:
        return run_demote(args.only)
    if args.report_only:
        return run_report(args.only)

    if args.apply and not BACKUP_DIR.is_dir():
        print(f"[FAIL] 缺少整体备份目录：{BACKUP_DIR}")
        return 2

    rows = []
    failed = []
    for slug, path in iter_skill_files(args.only):
        raw = path.read_text(encoding="utf-8-sig")
        # 已是标题式（无标签章节）：跳过，保证脚本可重复执行
        _, _body, _ = frontmatter.split_frontmatter(raw)
        if not split_tags(_body)[1]:
            print(f"[SKIP] {slug}: 已是标题式（无标签章节）")
            continue
        try:
            doc, meta = build_doc(slug, raw)
        except Exception as e:
            failed.append((slug, str(e)))
            print(f"[FAIL] {slug}: {e}")
            continue
        rows.append((slug, meta))
        action = "APPLY" if args.apply else "DRY"
        print(f"[{action}] {slug}: {meta['old_chars']} -> {meta['new_chars']} 字，"
              f"章节 {len(meta['sections'])}，分册 {meta['refs'] or '无'}")
        if args.apply:
            refs_dir = path.parent / "references"
            # 先写分册，再写主文档（主文档指针引用分册）
            for title, filename in (("媒体生成", "媒体生成.md"),
                                    ("提示词写法", "提示词写作.md")):
                if filename not in meta["refs"]:
                    continue
                _, body, _ = frontmatter.split_frontmatter(raw)
                preamble, tags = split_tags(body)
                parts = [clean_section(t) for tag, t in tags
                         if TAG_SECTION.get(tag) == title]
                text = "\n\n".join(p for p in parts if p)
                if text:
                    refs_dir.mkdir(parents=True, exist_ok=True)
                    atomic_write_text(
                        refs_dir / filename, f"# {title}\n\n{text}\n")
            atomic_write_text(path, doc)

    if args.apply and rows:
        from src.video_agent.skill_runtime.registry import sync_all
        sync_all()
        lines = [
            "# Skill 通用化迁移报告（2026-11-11）",
            "",
            f"- 迁移数量：{len(rows)}",
            f"- 失败：{len(failed)}",
            f"- 备份目录：`data/skills_backup_20261111`",
            "",
            "| Skill | 原字数 | 新字数 | 章节数 | 新增分册 |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
        for slug, meta in rows:
            lines.append(
                f"| {slug} | {meta['old_chars']} | {meta['new_chars']} | "
                f"{len(meta['sections'])} | {'、'.join(meta['refs']) or '—'} |")
        if failed:
            lines += ["", "## 失败", ""] + [f"- {s}: {e}" for s, e in failed]
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(REPORT_PATH, "\n".join(lines) + "\n")
        print(f"[OK] 已写报告：{REPORT_PATH}")

    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
