# -*- coding: utf-8 -*-
"""一次性迁移：Skill 故事板三章合并回 <storyboard_designer> + planner 字段回写。

已执行完毕（2026-09-25，D-24 故事板支清偿 / 冻结#16 部分翻案放行；14 个 Skill 包改写，
`宣言式概念短片` 与 `新-Skill` 本就是合并形态故零改动）。防回潮兜底 = 重采后的
`tests/fixtures/skill_sections_golden.json`（S6 章节黄金快照）+ `scripts/check_skill_anchor_lint.py`
+ `scripts/check_stage_face_consistency.py`（章节 tag 100% 被 SECTION_TAG_STAGES 覆盖）。
本脚本是 L-0821C 批 `migrate_skill_executor_names.py`（三拆）的**反向操作**，两者同处本目录留档。

用户裁决（2026-09-25）：

1. **章节合并**：`<storyboard_key_elements>` / `<storyboard_shots>` / `<storyboard_audio>`
   三章合并为单个 `<storyboard_designer>`（原版形态）。三段正文**逐字不改**，
   只删 4 行内层标签、首尾改名，段间统一一个空行。
2. **planner 字段回写**（口径：除规格文档步 `document_write` 外，指向本文档真实章节 tag；
   正文里的工具名「原版有就留、没有就删」——实测原版 planner 词表只有
   media_generator / storyboard_designer / text_editor / video_assembler /
   resource_prepare_and_analyze / reply_to_user / write_the_prompt，
   故事板三件套与 read_uploaded_doc 原版均无）：
   - 素材分析步 `read_uploaded_doc` → `script_analyze`；
   - 故事板步整组指代三件套 → `storyboard_designer`；
   - 故事板步内「登记/绑定素材·音色进草稿」语义的单个三件套内联 → 删工具名、留动作；
   - `多人对话访谈` 混合箭头 → `**image_generate**`（用户裁决）。
3. **明确不动**：生成步骤全部内联（「提示词先经 storyboard_patch_draft 写入草稿」等，28 处）、
   媒体字段（image_generate / generate_video / audio_generate 及其章节错位，用户「后面有大计划」）、
   `document_write`、`workflow_pause` / `reply_to_user`、三章正文、planner 之外的正文、
   `宣言式概念短片` 与 `新-Skill`（已是合并形态）。

用法（已归档于 scripts/archive/，root = parents[2]；默认 dry-run 只报告，不落盘）：
    python scripts/archive/migrate_storyboard_sections_merge.py
    python scripts/archive/migrate_storyboard_sections_merge.py --apply
退出码：0 = 全部规则命中且无遗留；1 = 有未匹配形态（fail-loud，不落盘）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"

TRIO = ("storyboard_create_group", "storyboard_add_draft", "storyboard_patch_draft")
# 登记绑定语义（故事板步）；含「写入草稿」的是生成前置语义 → 生成步，不动
REGISTER = re.compile(r"登记|绑定|注册|参考字段|参考资产")

BLOCK = re.compile(
    r"<storyboard_key_elements>\n(?P<ke>.*?)\n</storyboard_key_elements>\n+"
    r"<storyboard_shots>\n(?P<shots>.*?)\n</storyboard_shots>\n+"
    r"<storyboard_audio>\n(?P<au>.*?)\n</storyboard_audio>",
    re.S,
)
GROUP = re.compile(r"storyboard_create_group\s*/\s*storyboard_add_draft\s*/\s*"
                   r"storyboard_patch_draft")
# 混合箭头特例（多人对话访谈 步骤5）
MIXED_ARROW = "**storyboard_patch_draft、image_generate**"
# 单个内联的删除形态（按此顺序尝试；未命中即 fail-loud）
DELETE_FORMS: Tuple[Tuple[str, str], ...] = (
    ("（**storyboard_patch_draft**）", ""),
    ("（storyboard_patch_draft）", ""),
    ("(**storyboard_patch_draft**)", ""),
    ("(storyboard_patch_draft)", ""),
    ("通过 **storyboard_patch_draft** ", ""),
    ("通过 storyboard_patch_draft ", ""),
    ("经 **storyboard_patch_draft** ", ""),
    ("经 storyboard_patch_draft ", ""),
)


def _clause(text: str, pos: int) -> str:
    """取 pos 所在分句（按 。；：\n 切），用于登记/生成语义判定。"""
    start = max((text.rfind(s, 0, pos) for s in "。；：\n"), default=-1) + 1
    ends = [text.find(s, pos) for s in "。；：\n"]
    end = min(e for e in ends if e >= 0) if any(e >= 0 for e in ends) else len(text)
    return text[start:end]


def migrate(text: str, name: str, report: List[str]) -> str:
    """返回改写后的全文；每条改动写进 report。未匹配形态直接抛 ValueError。"""
    if "\r" in text:
        raise ValueError(f"{name}: 含 CR，行尾形态非 LF，中止")
    out = text

    # ---- 规则 1：三章合并 ----
    m = BLOCK.search(out)
    if m:
        merged = (f"<storyboard_designer>\n{m.group('ke')}\n\n{m.group('shots')}"
                  f"\n\n{m.group('au')}\n</storyboard_designer>")
        for tag in ("ke", "shots", "au"):
            if not m.group(tag).strip():
                raise ValueError(f"{name}: {tag} 段为空，中止")
        body_same = all(m.group(t) in merged for t in ("ke", "shots", "au"))
        if not body_same:
            raise ValueError(f"{name}: 合并后正文丢失，中止")
        out = out[:m.start()] + merged + out[m.end():]
        report.append(f"  [R1 章节合并] 三章 → <storyboard_designer>"
                      f"（ke {len(m.group('ke'))} + shots {len(m.group('shots'))}"
                      f" + audio {len(m.group('au'))} 字符，正文逐字保留）")
    elif "<storyboard_key_elements>" in out:
        raise ValueError(f"{name}: 三章形态不符预期（不相邻或空行异常），中止")

    # ---- planner 段落定位（规则 2-5 只在 planner 内生效）----
    pm = re.search(r"<planner>(.*?)</planner>", out, re.S)
    if not pm:
        report.append("  [跳过] 无 <planner> 段")
        return out
    head, body, tail = out[:pm.start(1)], pm.group(1), out[pm.end(1):]

    # ---- 规则 2：素材分析步 ----
    n = body.count("read_uploaded_doc")
    if n:
        body = body.replace("read_uploaded_doc", "script_analyze")
        report.append(f"  [R2 素材分析] read_uploaded_doc → script_analyze ×{n}")

    # ---- 规则 3：故事板步整组指代 ----
    groups = GROUP.findall(body)
    if groups:
        body = GROUP.sub("storyboard_designer", body)
        report.append(f"  [R3 故事板步] 三件套整组指代 → storyboard_designer ×{len(groups)}")

    # ---- 规则 4：混合箭头特例 ----
    if MIXED_ARROW in body:
        body = body.replace(MIXED_ARROW, "**image_generate**")
        report.append("  [R4 混合箭头] **storyboard_patch_draft、image_generate** → **image_generate**")

    # ---- 规则 5：登记类单个内联删工具名（生成前置类一律不动）----
    # 先在原文上收集全部命中与判定，再逆序删除，避免边删边找导致偏移错位。
    occurrences = sorted(
        (m.start(), m.group(0))
        for t in TRIO for m in re.finditer(re.escape(t), body)
    )
    spans: List[Tuple[int, int, str, str]] = []  # (start, end, form, clause)
    kept = 0
    for idx, _name in occurrences:
        clause = _clause(body, idx)
        if not REGISTER.search(clause) or "写入草稿" in clause:
            kept += 1  # 生成前置类：生成步骤不改（用户裁决）
            continue
        form = next((f for f in DELETE_FORMS if f[0] in clause), None)
        if form is None:
            raise ValueError(f"{name}: 登记类内联无匹配删除形态 → {clause.strip()[:90]}")
        pos = body.find(form[0], max(0, idx - 40))
        if pos < 0 or pos > idx:
            raise ValueError(f"{name}: 删除形态定位失败 → {form[0]}")
        spans.append((pos, pos + len(form[0]), form[0], clause))
    for a, b, _, _ in spans:
        if any(a < b2 and a2 < b for a2, b2, _, _ in spans if (a2, b2) != (a, b)):
            raise ValueError(f"{name}: 删除区间重叠，中止")
    for start, end, form, clause in sorted(spans, reverse=True):
        body = body[:start] + body[end:]
        report.append(f"  [R5 删工具名] {form!r} ← 分句：{clause.strip()[:70]}")

    # 对账：每处三件套命中要么被删、要么被判为生成前置类保留，不允许第三种下场
    if len(occurrences) != len(spans) + kept:
        raise ValueError(f"{name}: 命中对账不平 occurrences={len(occurrences)} "
                         f"deleted={len(spans)} kept={kept}")
    if kept:
        report.append(f"  [保留] 生成前置类内联 {kept} 处（生成步骤不改，用户裁决）")
    return head + body + tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真改（默认 dry-run 只报告）")
    args = ap.parse_args()

    docs = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    report: List[str] = [f"扫描 {len(docs)} 个 Skill 包（{'APPLY' if args.apply else 'DRY-RUN'}）"]
    changed = 0
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        sub: List[str] = []
        try:
            new = migrate(text, doc.parent.name, sub)
        except ValueError as e:
            print(f"[FAIL] {e}")
            return 1
        if new != text:
            changed += 1
            report.append(f"### {doc.parent.name}")
            report.extend(sub)
            if args.apply:
                doc.write_text(new, encoding="utf-8", newline="\n")
        elif sub:
            report.append(f"### {doc.parent.name}（无改动）")
            report.extend(sub)

    report.append("")
    report.append(f"合计：{changed} 个文件{'已改写' if args.apply else '待改写'} / {len(docs)} 个扫描")
    text = "\n".join(report)
    print(text.encode("ascii", "replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
