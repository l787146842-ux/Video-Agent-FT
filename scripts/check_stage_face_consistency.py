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
`reports/2222-3333-事故根因-20260923/07-全量Skill章节对应审计.md`（该审计报告正文已归档删除，结论已固化为本闸断言）。

## 本闸断言三条

1. **委派面 ⊆ 能力面**：`PIPELINE_STAGE_KINDS` 的每个名字都必须能在
   `PIPELINE_CAPABILITY_TOOLS` 里找到（或是有意登记的合并阶段别名）。
   违反 = 某个可委派阶段在能力面无对应章节来源（派出去也没章节可注入）。
2. **能力面每个名字要么可委派、要么在豁免表内**：能力面出现「委派面没有、
   又无人消费」的名字即 FAIL（除非显式登记豁免 + 理由）——这正是本闸
   要防的漂移形态。
3. （已退役）2026-11-11 通用 skill 迁移后 Skill 正文不再有标签章节，
   原「章节 tag 100% 被映射表覆盖」断言删除；本闸只校验 1、2 两条。

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
#
# 2026-10-01 媒体生成支（步骤3）更新：本闸最初记录的洞——「4 个 Skill 章节因
# 能力面有名字、委派面没有而**永远无法注入执行者**」——其**媒体生成部分已清偿**：
# `generation` 章现由可委派阶段 `media_generate`（媒体生成）注入。
# 因此下表的 `audio_generate` 理由由「章节不可注入」收敛为「能力词非委派阶段，
# 其章节已随 media_generate 注入」。条目**仍保留**是因为它作为能力词确实不在
# 委派面（`available_tools` 口径不变）；`video_assembler` 仍属未清偿
# （组装阶段按 Skill 由用户在工作台操作，无对应委派工具）。
CAPABILITY_ONLY_EXEMPT: Dict[str, str] = {
    "storyboard_key_elements": "批6 合并遗留：已并入 storyboard_design（章节仍由 capability 名定位）",
    "storyboard_shots": "批6 合并遗留：同上",
    "storyboard_audio": "批6 合并遗留：同上",
    "audio_generate": "能力词（供 available_tools 探针）；其 generation 章节已由 media_generate 阶段注入（2026-10-01 媒体生成支）",
    "video_assembler": "平台工具已落地（成片合成/方案落盘/推画布），但组装由主代理直接执行，不进委派面",
}

# 委派面出现、能力面没有的名字 —— 合并阶段的合法别名（有意为之，非漂移）。
# 委派面出现、能力面没有的名字 —— 合并阶段的合法别名（有意为之，非漂移）。
# 注：`media_generate` **不在**此列——它同时是能力词（PIPELINE_CAPABILITY_TOOLS），
# 断言 1 直接成立，无需别名豁免。
DELEGATE_ONLY_ALLOWED: Set[str] = {"storyboard_design"}


def _load_faces() -> Tuple[Set[str], Set[str], Dict[str, str], Set[str], Set[str]]:
    """导入两集合（fail-closed）。

    2026-11-11 通用 skill 迁移：Skill 正文不再有标签章节，原「章节 tag 覆盖」
    断言随之退役；本脚本只校验委派面与能力面的一致性。
    """
    from src.video_agent.core.subagent import PIPELINE_STAGE_KINDS
    from src.video_agent.skill_runtime.registry import PIPELINE_CAPABILITY_TOOLS

    delegate = set(PIPELINE_STAGE_KINDS)
    capability = set(PIPELINE_CAPABILITY_TOOLS)
    return delegate, capability, {}, set(), set()


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

    # ---- 信息性输出（不进退出码）----
    # 注意：输出一律 ASCII-safe——Windows GBK 终端无法编码 ⊆/⊇ 等符号，
    # 会在 print 处抛 UnicodeEncodeError 把「通过」伪装成「失败」
    # （acceptance.py 模块 docstring 记载的同型事故）。
    notes.append(f"capability face = {len(capability)} names / "
                 f"delegate face = {len(delegate)} names")
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
