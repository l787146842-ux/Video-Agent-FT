# -*- coding: utf-8 -*-
"""能力面 ⊇ 委派面 一致性闸（2026-09-23 批9 P-2，用户裁决「补 lint 防漂移」）。

## 为什么需要这道闸

2026-09-22 批6「三阶段合并」把三个故事板原子阶段从**委派面**退役
（`PIPELINE_STAGE_KINDS` 由 5 个收敛为 3 个），但**能力面**
（`PIPELINE_CAPABILITY_TOOLS`）仍留着 7 个名字。两边从 8 处漂移至今
（2026-09-23 全量审计实测），**没有任何门禁拦过**——这正是本闸补的洞。

漂移的实际代价：4 个 Skill 章节因「能力面有名字、委派面没有」而
**永远无法注入执行者**（`<image_generate>` / `<generate_video>` /
`<audio_generate>` / `<video_assembler>`；其中 `<video_assembler>` 影响
16/16 个 Skill），章节正文取得到却发不出去。详见
`reports/2222-3333-事故根因-20260923/07-全量Skill章节对应审计.md`。

## 本闸断言三条

1. **委派面 ⊆ 能力面**：`PIPELINE_STAGE_KINDS` 的每个名字都必须能在
   `PIPELINE_CAPABILITY_TOOLS` 里找到（或是有意登记的合并阶段别名）。
   违反 = 某个可委派阶段在能力面无对应章节来源（派出去也没章节可注入）。
2. **能力面每个名字要么可委派、要么在豁免表内**：能力面出现「委派面没有、
   又无人消费」的名字即 FAIL（除非显式登记豁免 + 理由）——这正是本闸
   要防的漂移形态。
3. **每个 Skill 的章节 tag 100% 被 `SECTION_TAG_STAGES` 覆盖**：
   当前 16/16 满分，钉住防回退（新增章节 tag 忘记登记映射即被拦）。

## 豁免表纪律（与 R2_BASELINE / DECLARED_PREFIXES 同口径）

`CAPABILITY_ONLY_EXEMPT` 只减不增；清空即销账。每条必须附理由与
登记来源（本次批9 登记的是「批6 合并遗留、待 D-8 裁决处置」）。

Fail-closed：读不动 / import 失败一律记违规——"cannot scan" 不等于"没问题"。

Exit 0 = clean；exit 1 = violations。
Usage: python scripts/check_stage_face_consistency.py
"""
import pathlib
import sys
from typing import Dict, List, Set, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 能力面出现、委派面没有的名字 —— 逐条登记豁免 + 理由。
# 纪律：只减不增。批6 合并遗留项待 D-8 裁决（补进委派面 / 显式登记不注入），
# 裁决落地后本表应随之收缩。
CAPABILITY_ONLY_EXEMPT: Dict[str, str] = {
    "storyboard_key_elements": "批6 合并遗留：已并入 storyboard_design（章节仍由 capability 名定位）",
    "storyboard_shots": "批6 合并遗留：同上",
    "storyboard_audio": "批6 合并遗留：同上",
    "audio_generate": "D-8 待裁决：章节不可注入（无承载章节，见 D-24）",
    "video_assembler": "D-8 待裁决：章节不可注入（影响 16/16 Skill，见 D-24）",
}

# 委派面出现、能力面没有的名字 —— 合并阶段的合法别名（有意为之，非漂移）。
DELEGATE_ONLY_ALLOWED: Set[str] = {"storyboard_design"}


def _load_faces() -> Tuple[Set[str], Set[str], Dict[str, str], Set[str], Set[str]]:
    """导入两集合 + 章节映射 + Skill 章节 tag 全集（fail-closed）。"""
    from src.video_agent.core.subagent import PIPELINE_STAGE_KINDS
    from src.video_agent.skill_runtime.registry import PIPELINE_CAPABILITY_TOOLS
    from src.video_agent.web.skill_docs import SECTION_TAG_STAGES

    delegate = set(PIPELINE_STAGE_KINDS)
    capability = set(PIPELINE_CAPABILITY_TOOLS)
    tag_stages = dict(SECTION_TAG_STAGES)

    # 全部 Skill 实际书写的章节 tag（独占行、成对闭合形态）
    import io
    import re
    skills_dir = ROOT / "data" / "skills"
    tags: Set[str] = set()
    if skills_dir.is_dir():
        for f in sorted(skills_dir.glob("*/SKILL.md")):
            text = io.open(f, encoding="utf-8", errors="replace").read()
            tags.update(re.findall(r"^<([a-zA-Z_][a-zA-Z0-9_]*)>\s*$", text, re.M))
    return delegate, capability, tag_stages, tags, set()


def _ascii_safe(text: str) -> str:
    """ASCII-safe 摘要（Windows GBK 终端安全；同 check_tool_descriptions 口径）。"""
    return "".join(c if c.isascii() else "?" for c in text)


def main() -> int:
    violations: List[str] = []
    notes: List[str] = []

    try:
        delegate, capability, tag_stages, skill_tags, _ = _load_faces()
    except Exception as e:  # fail-closed：扫不动不是没问题
        print(f"[check_stage_face_consistency] FAIL: 无法装载事实源: {e}")
        return 1

    # ---- 断言 1：委派面 ⊆ 能力面（允许合并阶段别名）----
    missing_in_capability = sorted(delegate - capability - DELEGATE_ONLY_ALLOWED)
    if missing_in_capability:
        violations.append(
            "委派面名字在能力面无对应（派出去也没章节可注入）: "
            + ", ".join(missing_in_capability))

    # ---- 断言 2：能力面 ⊆ 委派面 ∪ 豁免 ----
    capability_only = sorted(capability - delegate - set(CAPABILITY_ONLY_EXEMPT))
    if capability_only:
        violations.append(
            "能力面出现「委派面没有、又未登记豁免」的名字（漂移）: "
            + ", ".join(capability_only))

    # 豁免表自身卫生：登记了但已不在能力面 = 死条目，须删
    stale = sorted(set(CAPABILITY_ONLY_EXEMPT) - capability)
    if stale:
        violations.append(
            "豁免表含已不在能力面的死条目（须删除）: " + ", ".join(stale))

    # ---- 断言 3：Skill 章节 tag 100% 被映射表覆盖 ----
    uncovered = sorted(t for t in skill_tags if t not in tag_stages)
    if uncovered:
        violations.append(
            f"Skill 章节 tag 未被 SECTION_TAG_STAGES 覆盖（{len(uncovered)} 个）: "
            + ", ".join(uncovered))

    # ---- 信息性输出（不进退出码）----
    # 注意：输出一律 ASCII-safe——Windows GBK 终端无法编码 ⊆/⊇ 等符号，
    # 会在 print 处抛 UnicodeEncodeError 把「通过」伪装成「失败」
    # （acceptance.py 模块 docstring 记载的同型事故）。
    notes.append(f"capability face = {len(capability)} names / "
                 f"delegate face = {len(delegate)} names")
    notes.append(f"skill section tags = {len(skill_tags)}, "
                 + ("all mapped" if not uncovered else f"{len(uncovered)} unmapped"))
    if CAPABILITY_ONLY_EXEMPT:
        notes.append(f"exempt entries = {len(CAPABILITY_ONLY_EXEMPT)} (shrink-only)")

    if violations:
        print(f"[check_stage_face_consistency] FAIL: {len(violations)} violation(s)")
        for v in violations:
            print(f"  - {_ascii_safe(v)}")
        print("")
        print("Fix: keep capability/delegate faces in sync (a new stage must be "
              "registered in both); register intentionally capability-only names "
              "in CAPABILITY_ONLY_EXEMPT with a reason.")
        return 1

    print("[check_stage_face_consistency] PASS: capability >= delegate, "
          "all skill section tags mapped")
    for n in notes:
        print(f"  - {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
