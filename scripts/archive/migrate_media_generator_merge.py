# -*- coding: utf-8 -*-
"""一次性迁移（步骤 1a / D-24 媒体生成支前置）：生成类章节标签统一为 <media_generator>。

用户裁决（2026-10-01）：把所有的生成章节全部合并为一个 <media_generator> 媒体生成章节，
**所有 skill**；planner 的生成步骤对应章节全部改为 <media_generator>（步骤 2，见姊妹脚本）。

规则（只动外壳标签，**正文逐字不改**）：

  R1 多标签合并：`<image_generate>` / `<generate_video>` / `<audio_generate>` 连续出现的
     整块，合并为单个 `<media_generator>`；各段正文按出现顺序以**空行**相接。
  R2 单标签更名：孤立的 `<generation>` 更名为 `<media_generator>`（同映射目标，纯对齐形状）。
  R3 已是 `<media_generator>` 的包零改动（宣言式概念短片 / 新-Skill）。

为什么这是**字节中性**的：`skill_docs.split_skill_sections` 里
`SECTION_TAG_STAGES` 早已把这四个 tag 全部映射到同一个 `generation` 阶段键，
收集时对每段做 `.strip()`、再以 `"\\n\\n".join` 拼接。合并后单标签的 body 为
`"\\n" + "\\n\\n".join(段) + "\\n"`，再经同一个 `.strip()` ⇒ 与合并前**逐字节相等**。
故 `tests/fixtures/skill_sections_golden.json` 的 `generation` 指纹（chars/head）
**不应变化**——本脚本跑完必须用 `recut_skill_sections_golden.py --check` 证明「差异 0」。

用法（已归档于 scripts/archive/，root = parents[2]；默认 dry-run 只报告，不落盘）：
    python scripts/archive/migrate_media_generator_merge.py
    python scripts/archive/migrate_media_generator_merge.py --apply
退出码：0 = 全部规则命中且无遗留；1 = 有未匹配形态（fail-loud，不落盘）。

已执行完毕（2026-10-01，14 个包改写 / 2 个本就是合并形态零改动）。防回潮兜底 =
`tests/fixtures/skill_sections_golden.json`（本次**逐字节中性**，指纹零变化，无需重采）
+ `scripts/check_skill_anchor_lint.py` + `scripts/check_stage_face_consistency.py`。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"

# 参与合并的生成类标签（有序：按文件内实际出现顺序处理，不重排正文）
GEN_TAGS = ("image_generate", "generate_video", "audio_generate")
TARGET = "media_generator"
# 规则 2：孤立的平台名标签（同映射目标）更名对齐
RENAME_ONLY = ("generation",)

# 匹配「独占一行的标签 + 其正文」；非贪婪到同名闭合标签
_BLOCK = re.compile(
    r"^<(?P<tag>{tags})>[ \t]*\n(?P<body>.*?)\n^</(?P=tag)>[ \t]*$".format(
        tags="|".join(GEN_TAGS + RENAME_ONLY)),
    re.S | re.M,
)


def migrate(text: str, name: str, report: List[str]) -> str:
    """返回改写后的全文；每条改动写进 report。未匹配形态直接抛 ValueError。"""
    if "\r" in text:
        raise ValueError(f"{name}: 含 CR，行尾形态非 LF，中止")

    matches = list(_BLOCK.finditer(text))
    if not matches:
        if "<media_generator>" in text:
            report.append("  [R3 跳过] 已是 <media_generator>，零改动")
            return text
        raise ValueError(f"{name}: 未找到任何生成类章节标签，中止")

    tags = [m.group("tag") for m in matches]
    # 连续性校验：匹配块之间的间隙只允许空白（保证「合并为一章」语义成立）
    for prev, cur in zip(matches, matches[1:]):
        gap = text[prev.end():cur.start()]
        if gap.strip():
            raise ValueError(
                f"{name}: <{prev.group('tag')}> 与 <{cur.group('tag')}> 之间夹带正文，中止")

    # R3：唯一的匹配就是 media_generator（不在 GEN_TAGS/RENAME_ONLY 内，故不会走到这里）
    if len(tags) == 1 and tags[0] in RENAME_ONLY:
        m = matches[0]
        body = m.group("body").strip()
        if not body:
            raise ValueError(f"{name}: <{m.group('tag')}> 段为空，中止")
        new = f"<{TARGET}>\n{body}\n</{TARGET}>"
        if body not in new:
            raise ValueError(f"{name}: 更名后正文丢失，中止")
        out = text[:m.start()] + new + text[m.end():]
        report.append(f"  [R2 更名] <{m.group('tag')}> → <{TARGET}>"
                      f"（正文 {len(body)} 字符逐字保留）")
        return out

    # R1：多标签合并
    bodies = [m.group("body").strip() for m in matches]
    for tag, body in zip(tags, bodies):
        if not body:
            raise ValueError(f"{name}: <{tag}> 段为空，中止")
    merged_body = "\n\n".join(bodies)
    new = f"<{TARGET}>\n{merged_body}\n</{TARGET}>"
    for body in bodies:
        if body not in new:
            raise ValueError(f"{name}: 合并后正文丢失，中止")
    out = text[:matches[0].start()] + new + text[matches[-1].end():]
    report.append(
        f"  [R1 合并] {'+'.join('<%s>' % t for t in tags)} → <{TARGET}>"
        f"（{'+'.join(str(len(b)) for b in bodies)} 字符，正文逐字保留）")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真改（默认 dry-run 只报告）")
    args = ap.parse_args()

    docs = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    report: List[str] = [
        f"扫描 {len(docs)} 个 Skill 包（{'APPLY' if args.apply else 'DRY-RUN'}）"]
    changed = 0
    unchanged = 0
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
        else:
            unchanged += 1
            report.append(f"### {doc.parent.name}")
            report.extend(sub)

    report.append("")
    report.append(f"合计：{changed} 个文件{'已改写' if args.apply else '待改写'} / "
                  f"{unchanged} 个零改动 / {len(docs)} 个扫描")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
