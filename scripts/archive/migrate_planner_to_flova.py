# -*- coding: utf-8 -*-
"""一次性迁移：按 Flova 基准整体替换 Skill 的 `<planner>` 章节（用户裁决 2026-10-02）。

用户指令与逐项裁决（2026-10-02）：
  基准 = `C:\\Users\\ASUS\\Desktop\\skill\\<slug>.md`（Flova 原版 skill）。
  1. **范围**：只替换「Flova 本身有箭头」的文件（10 个）。Flova 自身零箭头的
     4 个（古风甜宠短剧 / 宣言式概念短片 / 未来科幻真人电影 / 李安美学风格短片）
     与箭头顶替不完整的，**保持我方现状不动**。
  2. **箭头目标**：Flova 指向我方不存在章节的（`image_generate` / `generate_video` /
     `audio_generate` / `bind_asset`）**统一映射为 `media_generator`**——与
     D-24 媒体生成支已确立口径一致，不重新引入「箭头指向空章节」的病。
  3. **保留原样**：箭头后的 `script_analyze` 与 `document_write`（用户指定）——
     即 Flova 的 `resource_prepare_and_analyze` → `script_analyze`、
     `text_editor` → `document_write`。
  4. **模型参数**：剥离（平台裁决「全局设置为唯一权威源」）。范围内 10 个文件
     经实测**无**写死模型参数，本规则作防御性兜底。
  5. **平台特有块**：整段替换、一并删除（用户裁决）。

另注（脚本内明示，防误读）：
  - 规格文档名 `Final_Video_Spec.md` **归一为本项目现行名 `制片规格.md`**：
    平台 `is_spec_doc_name` 两名皆认，但本项目存量项目（9999 等）与
    `DEFAULT_SKILL_DOC`/协议段均用 `制片规格.md`，若改回 Flova 名会让模型
    在既有项目里**另建第二份规格文档**。属有意的单点偏离，已在提交留痕。

用法（已归档于 scripts/archive/，root = parents[2]；默认 dry-run 只报告，不落盘）：
    python scripts/archive/migrate_planner_to_flova.py
    python scripts/archive/migrate_planner_to_flova.py --apply
退出码：0 = 全部规则命中且无遗留；1 = 有未匹配形态（fail-loud，不落盘）。

已执行完毕（2026-10-02，10 个包改写 / 6 个跳过）。影响面实测**只落 `planning` 章节**
（14 条 golden 差异全为 planning，越界 0）；`tests/fixtures/skill_sections_golden.json`
已按规程重采（保留原覆盖范围）。改后复跑 = 16/16 零改动（幂等）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"
FLOVA_DIR = Path(r"C:\Users\ASUS\Desktop\skill")

# 箭头目标映射（顺序敏感：先做别名→本项目名，再兜底→media_generator）。
# 键用「词边界」正则匹配，故箭头/非箭头、粗体/非粗体**全形态**一网打尽
# （实测 flova 里 text_editor 有 9 处粗体箭头 + 1 处非粗体箭头；
#   resource_prepare_and_analyze 另有 1 处非箭头交叉引用）。
ARROW_MAP: Tuple[Tuple[str, str], ...] = (
    ("resource_prepare_and_analyze", "script_analyze"),   # 用户指定保留
    ("text_editor", "document_write"),                    # 用户指定保留
    ("image_generate", "media_generator"),
    ("generate_video", "media_generator"),
    ("audio_generate", "media_generator"),
    ("bind_asset", "media_generator"),
)

# 我方**不存在**的 flova 专名（无论出现在箭头后、粗体、正文交叉引用），一律不得残留：
#   ① 章节交叉引用（「完整规则见 media_generator 与 write_the_prompt」）中的
#      flova 章节名 → 我方对应章节名；
#   ② bind_asset（资产绑定）：我方无此工具，绑定动作由 media_generator 承接。
CROSSREF_MAP: Tuple[Tuple[str, str], ...] = (
    ("write_the_prompt", "write_media_prompt"),
    ("multimodal_analyze_tool", "script_analyze"),
)

# 规格文档名归一（本项目现行名）
SPEC_OLD = "Final_Video_Spec.md"
SPEC_NEW = "制片规格.md"
# 裸名（无 .md 后缀，如「进入Final_Video_Spec与Storyboard前」）也一并归一
SPEC_OLD_BARE = "Final_Video_Spec"

# 写死模型参数（范围实测为空，防御性兜底；命中即 fail-loud 让人工裁决，
# 不静默删改正文——避免把「剥离」做成不可见的语义破坏）
MODEL_PARAM_RE = re.compile(
    r"(Seedance|GPT\s*Image|Kling|可灵|即梦|Midjourney|Flux|SDXL|"
    r"Runway|Vidu|Sora|Veo|Pika|Hailuo|海螺|万相|通义|"
    r"\d+K高清|\d+p|\d+fps|Nano\s*Banana|ElevenLabs|Suno|MediaKit)")

# 替换后仍不得出现的「我方不存在的箭头目标」（对账用）
OUR_TAGS = {"planner", "script_analyze", "storyboard_designer",
            "media_generator", "write_media_prompt", "video_assembler",
            "document_write"}

_PLANNER = re.compile(r"<planner>(.*?)</planner>", re.S)
_ARROW = re.compile(r"(→\s*\*\*)([a-z_]+)(\*\*)")


def _planner_body(text: str, name: str) -> str:
    m = _PLANNER.search(text)
    if not m:
        raise ValueError(f"{name}: 无 <planner> 段，中止")
    return m.group(1)


def rewrite(planner: str, name: str, report: List[str]) -> str:
    """把 Flova planner 正文改写为本项目口径（返回新正文，不含标签）。"""
    body = planner.strip("\n")

    # ---- S1 规格文档名归一（先长后短：带 .md 的先替换，再处理裸名） ----
    n_spec = body.count(SPEC_OLD)
    if n_spec:
        body = body.replace(SPEC_OLD, SPEC_NEW)
    n_bare = body.count(SPEC_OLD_BARE)
    if n_bare:
        body = body.replace(SPEC_OLD_BARE, "制片规格")
    if n_spec or n_bare:
        report.append(f"  [S1 规格名] {SPEC_OLD_BARE} → 制片规格"
                      f"（带 .md ×{n_spec} / 裸名 ×{n_bare}）")

    # ---- S2 目标名映射（全形态：箭头 / 粗体 / 正文交叉引用，一网打尽） ----
    counts = {}
    for old, rep in ARROW_MAP + CROSSREF_MAP:
        n = len(re.findall(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", body))
        if n:
            body = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", rep, body)
            counts[f"{old}→{rep}"] = counts.get(f"{old}→{rep}", 0) + n
    for k, v in sorted(counts.items()):
        report.append(f"  [S2 映射] {k} ×{v}")

    # ---- S3 模型参数兜底检查（命中即 fail-loud，交人工） ----
    hits = sorted(set(MODEL_PARAM_RE.findall(body)))
    if hits:
        raise ValueError(
            f"{name}: 正文含写死模型参数 {hits} —— 需人工裁决剥离方式，"
            f"本脚本不静默删改（防不可见语义破坏）")

    # ---- 对账 A：箭头目标必须全部落在我方真实章节内 ----
    bad = sorted({t for _, t in ((m.group(1), m.group(2))
                                 for m in _ARROW.finditer(body))
                  if t not in OUR_TAGS})
    if bad:
        raise ValueError(f"{name}: 映射后仍有非本项目箭头目标 {bad}（对账不平）")

    # ---- 对账 B：我方不存在的 flova 专名一律不得残留 ----
    leftover = sorted({k for k in
                       ("Final_Video_Spec", "resource_prepare_and_analyze",
                        "text_editor", "bind_asset", "write_the_prompt",
                        "multimodal_analyze_tool")
                       if k in body})
    if leftover:
        raise ValueError(f"{name}: 仍残留 flova 专名 {leftover}（对账不平）")

    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真改（默认 dry-run 只报告）")
    args = ap.parse_args()

    if not FLOVA_DIR.is_dir():
        print(f"[FAIL] Flova 基准目录不存在：{FLOVA_DIR}")
        return 1

    docs = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    report: List[str] = [
        f"扫描 {len(docs)} 个 Skill 包（{'APPLY' if args.apply else 'DRY-RUN'}）",
        f"基准目录：{FLOVA_DIR}",
        ""]
    changed = skipped = 0
    for doc in docs:
        slug = doc.parent.name
        text = doc.read_text(encoding="utf-8")
        fp = FLOVA_DIR / f"{slug}.md"
        if not fp.exists():
            skipped += 1
            report.append(f"### {slug}\n  [跳过] Flova 无对应文件")
            continue
        fl_planner = _planner_body(fp.read_text(encoding="utf-8"), slug)
        # 范围判定：Flova 本身有箭头才替换（用户裁决）
        if not _ARROW.search(fl_planner):
            skipped += 1
            report.append(f"### {slug}\n  [跳过] Flova 版零箭头（用户裁决：只替换有箭头的）")
            continue

        sub: List[str] = []
        try:
            new_body = rewrite(fl_planner, slug, sub)
        except ValueError as e:
            print(f"[FAIL] {e}")
            return 1

        m = _PLANNER.search(text)
        new_text = text[:m.start(1)] + "\n" + new_body + "\n" + text[m.end(1):]
        if new_text == text:
            skipped += 1
            report.append(f"### {slug}\n  [无差异]")
            continue
        changed += 1
        old_len = len(m.group(1))
        report.append(
            f"### {slug}  planner {old_len} → {len(new_body)} 字符")
        report.extend(sub)
        if args.apply:
            doc.write_text(new_text, encoding="utf-8", newline="\n")

    report.append("")
    report.append(f"合计：{changed} 个文件{'已改写' if args.apply else '待改写'} / "
                  f"{skipped} 个跳过 / {len(docs)} 个扫描")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
