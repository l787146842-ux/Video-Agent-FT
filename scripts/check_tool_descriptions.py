# -*- coding: utf-8 -*-
"""Tool description hygiene gate (dsh-style positive contract only).

AST scan src/video_agent/tools/**.py for class-level `description = (...)`
attributes on BaseTool subclasses, flagging three pollution classes:

  1. 禁令句 (prohibition/negation): "不得" / "禁止" / "不要" / "不允许" /
     "不属于" / "不承载" / "违规" / "是错误的"
     → 说明层禁令会吓退模型（3333 项目实证），且属流程纪律层职责，
       工具描述只留正面契约（2026-09-12 裁决）。

  2. 流程纪律句 (turn/batch discipline): "本轮立即结束" / "本轮结束" /
     "停轮" / "同批提交" / "批次纪律" / "同一响应"
     → 停轮/批次契约唯一家 = iron_rules_header + skill_runtime DISCIPLINE，
       工具描述不复述（P1 单一事实源）。

  3. 他层阶段名单 (cross-layer stage roster): 单条 description 内出现
     ≥2 个 PIPELINE_STAGE_KINDS 成员（script_analyze / storyboard_key_elements /
     storyboard_shots / storyboard_audio / write_media_prompt）
     → 阶段名单唯一源 = core/subagent.py::PIPELINE_STAGE_KINDS，
       工具描述枚举即复述（ run_subagent 硬编码阶段名单事故，2026-09-15 铺满批）。

Fail-closed: unreadable files, syntax errors and missing scan dirs are
reported as marker violations — "cannot scan" is never "nothing wrong".

Exit 0 = clean; exit 1 = violations.
Usage: python scripts/check_tool_descriptions.py
"""
import ast
import pathlib
import re
import sys
from typing import List, Set, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIR = ROOT / "src" / "video_agent" / "tools"

# 阶段名单唯一源（与 core/subagent.py::PIPELINE_STAGE_KINDS 同步；
# 此处内联字面量以避免 gate 脚本反向依赖生产代码——gate 自包含）。
PIPELINE_STAGE_KINDS: Set[str] = {
    "script_analyze",
    "storyboard_key_elements",
    "storyboard_shots",
    "storyboard_audio",
    "write_media_prompt",
}

# 禁令/否定句模式（说明层禁令 = 反模式，2026-09-12 裁决）
BANNED_PROHIBITION: List[Tuple[str, str]] = [
    ("不得", "prohibition: 说明层禁令（应改正面契约或下沉流程纪律层）"),
    ("禁止", "prohibition: 说明层禁令（应改正面契约或下沉流程纪律层）"),
    ("不要", "prohibition: 说明层禁令（应改正面契约或下沉流程纪律层）"),
    ("不允许", "prohibition: 说明层禁令（应改正面契约或下沉流程纪律层）"),
    ("不属于", "prohibition: 说明层归属禁令（应改正面契约）"),
    ("不承载", "prohibition: 说明层否定契约（应改正面契约）"),
    ("违规", "prohibition: 说明层违规措辞（应改正面契约）"),
    ("是错误的", "prohibition: 说明层否定判词（应改正面契约）"),
]

# 流程纪律句模式（停轮/批次契约唯一家 = iron_rules + skill_runtime）
BANNED_FLOW_DISCIPLINE: List[Tuple[str, str]] = [
    ("本轮立即结束", "flow-discipline: 停轮契约（唯一家=iron_rules_header/skill_runtime）"),
    ("本轮结束", "flow-discipline: 停轮契约（唯一家=iron_rules_header/skill_runtime）"),
    ("停轮", "flow-discipline: 停轮契约（唯一家=iron_rules_header/skill_runtime）"),
    ("同批提交", "flow-discipline: 批次契约（唯一家=skill_runtime DISCIPLINE 第6条）"),
    ("批次纪律", "flow-discipline: 批次契约（唯一家=skill_runtime DISCIPLINE 第6条）"),
    ("同一响应", "flow-discipline: 批次契约（唯一家=skill_runtime DISCIPLINE 第6条）"),
]


def _ascii_safe(text: str) -> str:
    """ASCII-safe summary (Windows GBK console safety)."""
    return "".join(c if c.isascii() else "?" for c in text)


def _check_description(text: str) -> List[str]:
    """Return list of violation reasons for one description string."""
    reasons: List[str] = []
    for pattern, reason in BANNED_PROHIBITION:
        if pattern in text:
            reasons.append(f"{reason} [hit={_ascii_safe(pattern)!r}]")
    for pattern, reason in BANNED_FLOW_DISCIPLINE:
        if pattern in text:
            reasons.append(f"{reason} [hit={_ascii_safe(pattern)!r}]")
    # 他层阶段名单：单条 description 内 ≥2 个 PIPELINE_STAGE_KINDS 成员
    stage_hits = sorted({s for s in PIPELINE_STAGE_KINDS if s in text})
    if len(stage_hits) >= 2:
        reasons.append(
            "cross-layer stage roster: description enumerates "
            f"{len(stage_hits)} PIPELINE_STAGE_KINDS members "
            f"(single source = core/subagent.py::PIPELINE_STAGE_KINDS) "
            f"[hits={','.join(stage_hits)}]")
    return reasons


def _extract_class_descriptions(tree: ast.Module) -> List[Tuple[int, str, str]]:
    """Yield (lineno, class_name, description_text) for BaseTool subclasses.

    只扫 class 级 `description = (...)` 赋值（工具 schema 元数据）；
    Field(description=...) 等入参级描述不在本闸范围（属另一层契约）。
    """
    results: List[Tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # 只关心 BaseTool 子类（按 bases 名字匹配，避免反向依赖生产代码）
        base_names = set()
        for b in node.bases:
            if isinstance(b, ast.Name):
                base_names.add(b.id)
            elif isinstance(b, ast.Attribute):
                base_names.add(b.attr)
        if "BaseTool" not in base_names:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "description":
                    try:
                        value = ast.literal_eval(stmt.value)
                    except (ValueError, SyntaxError):
                        # 非字面量（如函数调用拼接）→ 跳过，不假装校验
                        continue
                    if isinstance(value, str):
                        results.append((stmt.lineno, node.name, value))
    return results


def _scan_file(path: pathlib.Path) -> List[Tuple[int, str, List[str]]]:
    """Return (lineno, class_name, reasons) for violations in one file.

    fail-closed：读不动 / 解析不动一律记为标记违规。
    """
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        return [(0, "__unreadable__", [f"unreadable file: {e}"])]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [(getattr(e, "lineno", 1) or 1, "__syntax_error__",
                 [f"syntax error: {e}"])]

    violations: List[Tuple[int, str, List[str]]] = []
    for lineno, class_name, text in _extract_class_descriptions(tree):
        reasons = _check_description(text)
        if reasons:
            violations.append((lineno, class_name, reasons))
    return violations


def main() -> int:
    all_violations: List[Tuple[str, int, str, List[str]]] = []
    if not SCAN_DIR.is_dir():
        # fail-closed：声明的扫描目录不存在 = 扫描面失效
        try:
            rel_dir = SCAN_DIR.relative_to(ROOT).as_posix()
        except ValueError:
            rel_dir = str(SCAN_DIR)
        all_violations.append(
            (rel_dir, 0, "__missing_scan_dir__",
             ["declared scan dir missing (scan surface broken)"]))
    else:
        for py_file in sorted(SCAN_DIR.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            rel = py_file.relative_to(ROOT).as_posix()
            for lineno, class_name, reasons in _scan_file(py_file):
                all_violations.append((rel, lineno, class_name, reasons))

    if all_violations:
        print(f"[check_tool_descriptions] FAIL: {len(all_violations)} "
              "tool description(s) polluted:")
        for rel, lineno, class_name, reasons in all_violations[:30]:
            print(f"  {rel}:{lineno} {class_name}")
            for r in reasons:
                print(f"    - {r}")
        if len(all_violations) > 30:
            print(f"  ... and {len(all_violations) - 30} more")
        print("")
        print("Fix: rewrite description as positive contract only; move "
              "prohibition/flow-discipline prose to iron_rules_header.md or "
              "skill_runtime.md DISCIPLINE; remove hardcoded stage rosters "
              "(single source = core/subagent.py::PIPELINE_STAGE_KINDS).")
        print("Ref: prompts/planner/subagent.md (two-bucket mapping); "
              "AGENTS.md P1 (single source of truth).")
        return 1
    print("[check_tool_descriptions] PASS: tool descriptions clean "
          "(positive contract only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
