# -*- coding: utf-8 -*-
"""一次性迁移（步骤 2 / D-24 媒体生成支本体）：planner 生成步骤 → <media_generator>。

用户裁决（2026-10-01，三步方案第 2 条）：planner 的生成步骤，对应的章节全部改为
<media_generator>。用户基准 = Flova 原版 planner（箭头后一律是**章节 tag**，
不是本项目的工具名）：第 4/5/6/7 步 → media_generator。

规则（**只在 <planner> 段内生效**，其余正文零改动）：

  R1 箭头字段回写：`→ **image_generate**` / `→ **generate_video**` / `→ **audio_generate**`
     （粗体与非粗体两种形态）→ `→ **media_generator**`。箭头位置是「本章节归谁管」的
     语义位，必须指向**本文档真实存在的章节 tag**；工具名占位是本批要治的病灶。
  R2 生成前置内联去工具名：`先经 storyboard_patch_draft 写入草稿` → `先写入草稿`。
     理由有二：① 该工具在 MAIN_AGENT_DENY 内、**主代理物理调不到**，planner（主代理
     读本）点名它属「散文宣称了不存在的授权」；② 它是子代理阶段的事，planner 只需
     保留下达顺序（先有稿再生成）这一事实。

明确**不动**（边界，逐条有裁决依据）：
  - `→ **document_write**`（规格文档步）：用户裁决「保留不改」，本文档无同名章节，已知例外。
  - `→ **storyboard_designer**` / `→ **video_assembler**`：本就是本文档真实章节 tag。
  - 非箭头的句中工具提及（如「再调用 **generate_video**」「随 generate_video 的音色参考
    机制」）：不属 D-24 ①② 范围；且主代理确实持有 generate_video（花钱闸在主线程），
    该表述是真事实。本脚本只报告其数量，不改。
  - `新-Skill` 的 `resource_prepare_and_analyze` / `text_editor`：外来宿主词表，另案。

用法（已归档于 scripts/archive/，root = parents[2]；默认 dry-run 只报告，不落盘）：
    python scripts/archive/migrate_planner_media_arrows.py
    python scripts/archive/migrate_planner_media_arrows.py --apply
退出码：0 = 全部规则命中且无遗留；1 = 有未匹配形态（fail-loud，不落盘）。

已执行完毕（2026-10-01，14 个包改写 / 2 个零改动；R1 ×20、R2 ×28）。
影响面实测**只落在 planning 章节**（14 条 golden 差异全为 planning，越界 0）；
`tests/fixtures/skill_sections_golden.json` 已按规程重采（保留原覆盖范围）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"

# R1：箭头后的生成类工具名（粗体可选）→ 章节 tag
ARROW_RE = re.compile(
    r"→\s*\*{0,2}\s*(?:image_generate|generate_video|audio_generate)\s*\*{0,2}")
ARROW_NEW = "→ **media_generator**"

# R2：生成前置内联的整句替换（工具名去掉，语义保留）
INLINE_OLD = "先经 storyboard_patch_draft 写入草稿"
INLINE_NEW = "先写入草稿"

# 只报告、不改的句中工具提及
MENTION_RE = re.compile(
    r"(?<![A-Za-z_])(?:image_generate|generate_video|audio_generate)(?![A-Za-z0-9_])")


def migrate(text: str, name: str, report: List[str]) -> str:
    if "\r" in text:
        raise ValueError(f"{name}: 含 CR，行尾形态非 LF，中止")

    m = re.search(r"<planner>(.*?)</planner>", text, re.S)
    if not m:
        raise ValueError(f"{name}: 无 <planner> 段，中止")
    head, body, tail = text[:m.start(1)], m.group(1), text[m.end(1):]

    # ---- R1 ----
    n_arrow = len(ARROW_RE.findall(body))
    if n_arrow:
        body = ARROW_RE.sub(ARROW_NEW, body)
        report.append(f"  [R1 箭头回写] 生成类箭头 → **media_generator** ×{n_arrow}")

    # ---- R2 ----
    n_inline = body.count(INLINE_OLD)
    if n_inline:
        body = body.replace(INLINE_OLD, INLINE_NEW)
        report.append(f"  [R2 去工具名] 「{INLINE_OLD}」→「{INLINE_NEW}」 ×{n_inline}")

    # ---- 对账：生成类章节引用必须已回写干净 ----
    leftover_arrow = ARROW_RE.findall(body)
    if leftover_arrow:
        raise ValueError(f"{name}: 箭头回写残留 {leftover_arrow}")
    if "storyboard_patch_draft" in body and INLINE_OLD in body:
        raise ValueError(f"{name}: 内联去名残留")

    # ---- 只报告：句中（非箭头）生成工具提及 ----
    mentions = MENTION_RE.findall(body)
    if mentions:
        report.append(f"  [保留·非箭头] 句中工具提及 {len(mentions)} 处（不属 D-24 范围，"
                      f"且主代理确实持有该工具）：{sorted(set(mentions))}")

    return head + body + tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真改（默认 dry-run 只报告）")
    args = ap.parse_args()

    docs = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    report: List[str] = [
        f"扫描 {len(docs)} 个 Skill 包（{'APPLY' if args.apply else 'DRY-RUN'}）"]
    changed = unchanged = 0
    tot_arrow = tot_inline = 0
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        sub: List[str] = []
        try:
            new = migrate(text, doc.parent.name, sub)
        except ValueError as e:
            print(f"[FAIL] {e}")
            return 1
        for line in sub:
            if line.startswith("  [R1"):
                tot_arrow += int(line.rsplit("×", 1)[1])
            if line.startswith("  [R2"):
                tot_inline += int(line.rsplit("×", 1)[1])
        if new != text:
            changed += 1
            report.append(f"### {doc.parent.name}")
            report.extend(sub)
            if args.apply:
                doc.write_text(new, encoding="utf-8", newline="\n")
        else:
            unchanged += 1
    report.append("")
    report.append(f"合计：{changed} 个文件{'已改写' if args.apply else '待改写'} / "
                  f"{unchanged} 个零改动 / {len(docs)} 个扫描")
    report.append(f"      R1 箭头回写 ×{tot_arrow}；R2 去工具名 ×{tot_inline}")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
