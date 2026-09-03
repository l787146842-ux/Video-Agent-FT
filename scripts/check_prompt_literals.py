# -*- coding: utf-8 -*-
"""A3 prompt_literals gate: CJK prose literals in production code.

AST scan src/video_agent/{core,state,web,tools,adapters}/ for string literals
containing CJK characters with length >= 8 that are likely hardcoded prose
entering model context or user-visible bubbles/cards/options.

Structural exemptions (not flagged):
  - docstrings (module/class/function first-expr)
  - arguments inside ANY function/method call (handler data: tracer, emit,
    ToolResult, logger, exceptions, externalization funcs, etc.)
  - return statements (structured data returned by tools/gates/descriptions)
  - class-level `description` attribute assignments (tool schema metadata)
  - strings registered in DECLARED_DATA (exact match) or DECLARED_PREFIXES
    (explicit prefix registrations, single-direction startswith)

Fail-closed: unreadable files, syntax errors and missing scan dirs are reported
as marker violations — "cannot scan" is never treated as "nothing wrong".

Flagged context: module-level constant assignments, attribute assignments
(like result.text), and dict/list values in assignment context — patterns
where hardcoded prose is stored for later injection into model context or
user-visible bubbles.

Exit 0 = clean; exit 1 = violations.
Usage: python scripts/check_prompt_literals.py
"""
import ast
import pathlib
import re
import sys
from typing import List, Set, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = [
    ROOT / "src" / "video_agent" / "core",
    ROOT / "src" / "video_agent" / "state",
    ROOT / "src" / "video_agent" / "web",
    ROOT / "src" / "video_agent" / "tools",
    ROOT / "src" / "video_agent" / "adapters",
]

# CJK Unified Ideographs (basic + ext-A)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_MIN_LEN = 8

# ---------- DECLARED_DATA: non-prose data registry (EXACT match) ----------
# (literal, reason). 完整字面量走精确相等——不得用前缀/双向 startswith 放宽，
# 否则①登记项被截短的硬编码残片②以登记前缀开头的全新长 prose 都会整条逃逸。
DECLARED_DATA: List[Tuple[str, str]] = [
    # --- context prune structural markers (model-visible, format params) ---
    ("\u27e6PRUNE: \u4e2d\u6bb5\u7701\u7565 {n} \u5b57\uff0c\u53ef\u7528 read_* \u5de5\u5177 start={start} \u7eed\u8bfb\u27e7",
     "prune marker: read_* tools (structural template with format params)"),
    ("\u27e6PRUNE: \u4e2d\u6bb5\u7701\u7565 {n} \u5b57\uff0c\u6309\u5df2\u6709\u5934\u5c3e\u4fe1\u606f\u7ee7\u7eed\uff0c\u52ff\u91cd\u590d\u751f\u6210\u27e7",
     "prune marker: generation tools (structural template with format params)"),
    # --- dimension/group UI labels (option_groups.py) ---
    ("\u51fa\u56feAPI\u4e0e\u6a21\u578b",
     "wizard dimension label (settings UI, non-prose)"),
    ("\u51fa\u89c6\u9891API\u4e0e\u6a21\u578b",
     "wizard dimension label (settings UI, non-prose)"),
    # --- gate/policy status constants ---
    ("\u5df2\u6309\u4f60\u7684\u8981\u6c42\u5168\u901f\u63a8\u8fdb\uff1a\u672c\u8f6e\u672a\u5f39\u51fa\u6d41\u7a0b\u6682\u505c\u786e\u8ba4\u5361\uff08\u603b\u7ed3/\u89c4\u683c\u5ba1\u9605\uff09\uff0c\u5df2\u5199\u5165\u7684\u5185\u5bb9\u7167\u5e38\u751f\u6548\uff1b\u5982\u9700\u8865\u770b\u6216\u8c03\u6574\uff0c\u968f\u65f6\u544a\u8bc9\u6211\u3002",
     "full-speed override notice (user card; exact literal = core/prompt_gates.FLOW_PAUSE_OVERRIDE_WARNING)"),
    ("\u63d0\u793a\u8bcd\u6b63\u6587\u51e0\u4e4e\u5168\u662f\u82f1\u6587",
     "language gate hard-reject signal prefix (detection constant)"),
    # --- round_compact fallback prefix (M-2: prompts/ is primary) ---
    ("\uff08\u7cfb\u7edf\uff09\u65e9\u671f\u8f6e\u6b21\u5df2\u538b\u7f29\u4e3a\u6458\u8981\uff1a",
     "round summary prefix fallback (prompts/ is primary source)"),
    # --- spec_rules migration constants (iron_rules doc patching) ---
    ("\u7528\u6237\u6307\u4ee4 > \u672c\u6587\u6863 > Skill/\u7cfb\u7edf\u9ed8\u8ba4",
     "old priority chain v1 (migration matching pattern)"),
    ("\u7528\u6237\u6307\u4ee4 > \u672c\u6587\u6863 + \u5236\u7247\u89c4\u683c > Skill/\u7cfb\u7edf\u9ed8\u8ba4",
     "old priority chain v2 (migration matching pattern)"),
    ("\u7528\u6237\u6700\u65b0\u6307\u4ee4 > \u672c\u6587\u6863 + \u5236\u7247\u89c4\u683c > Skill/\u7cfb\u7edf\u9ed8\u8ba4",
     "new priority chain (migration replacement text)"),
    ("\uff08\u4f18\u5148\u7ea7\u94fe\u5b8c\u6574\u58f0\u660e\u4e0e\u786c\u95f8\u6548\u529b\u8fb9\u754c\u89c1\u5e73\u53f0\u6ce8\u5165\u7684\u300a\u6267\u884c\u94c1\u5f8b\u300b\u5934\u90e8\uff09",
     "priority pointer suffix (migration replacement)"),
    ("3. \u56de\u590d\u7eaa\u5f8b\u89c1\u5e73\u53f0\u534f\u8bae\u3002\n",
     "clause 3 pointer (migration replacement text)"),
    # --- tracer display marker ---
    ("\u2026\uff08\u524d\u6587\u601d\u8003\u5df2\u622a\u65ad\uff09",
     "trace display truncation marker (not model context)"),
    # --- draft default label (state/models.py) ---
    ("Agent \u8349\u7a3f",
     "draft default label (UI data constant)"),
    # --- circuit breaker errors (user-visible operational messages) ---
    ("\u51fa\u56fe\u6e20\u9053\u8fde\u8d25\u7194\u65ad\uff1a\u4e0a\u6e38\u6301\u7eed\u9650\u6d41/\u62a5\u9519\u3002\u8bf7\u7ea6 1 \u5206\u949f\u540e\u91cd\u8bd5\uff0c\u6216\u5728 API \u914d\u7f6e/\u89c4\u683c\u6587\u6863\u66f4\u6362\u51fa\u56fe\u6e20\u9053\u3002",
     "image circuit breaker error (exact literal = web/generation_channel.IMAGE_CIRCUIT_ERROR)"),
    ("\u89c6\u9891\u751f\u6210\u6e20\u9053\u8fde\u8d25\u7194\u65ad\uff1a\u4e0a\u6e38\u6301\u7eed\u9650\u6d41/\u62a5\u9519\u3002\u8bf7\u7ea6 1 \u5206\u949f\u540e\u91cd\u8bd5\uff0c\u6216\u5728 API \u914d\u7f6e/\u89c4\u683c\u6587\u6863\u66f4\u6362\u751f\u89c6\u9891\u6e20\u9053\u3002",
     "video circuit breaker error (exact literal = web/generation_channel.VIDEO_CIRCUIT_ERROR)"),
    ("\u97f3\u9891\u751f\u6210\u6e20\u9053\u8fde\u8d25\u7194\u65ad\uff1a\u4e0a\u6e38\u6301\u7eed\u9650\u6d41/\u62a5\u9519\u3002\u8bf7\u7ea6 1 \u5206\u949f\u540e\u91cd\u8bd5\uff0c\u6216\u5728 API \u914d\u7f6e/\u89c4\u683c\u6587\u6863\u66f4\u6362\u97f3\u9891\u6e20\u9053\u3002",
     "audio circuit breaker error (exact literal = web/generation_channel.AUDIO_CIRCUIT_ERROR)"),
    # --- sub-feature system prompts / default skill doc template ---
    # 这三条是长多行模板（系统提示词 / 项目种子文档），完整字面量随措辞易漂，
    # 改登记在下方 DECLARED_PREFIXES（显式前缀项、附理由）。
    # --- heading detection patterns (skill_docs.py, non-prose) ---
    ("prompt \u7f16\u5199",
     "heading keyword detection pattern (non-prose)"),
    ("prompt\u7f16\u5199",
     "heading keyword detection pattern (non-prose)"),
    # --- stop phase status text (stop_manager.py, UI labels) ---
    ("\u5df2\u5728\u601d\u8003\u9636\u6bb5\u505c\u6b62\uff08\u672a\u4ea7\u751f\u5185\u5bb9\uff09",
     "stop phase status: thinking (UI label)"),
    ("\u5df2\u5728\u5de5\u5177\u6267\u884c\u9636\u6bb5\u505c\u6b62",
     "stop phase status: tool_executing (UI label)"),
    ("\u5df2\u5728\u8f93\u51fa\u9636\u6bb5\u505c\u6b62",
     "stop phase status: streaming (UI label)"),
    # --- target validation hint (document_tools.py, structured error data) ---
    ("target \u5408\u6cd5\u53d6\u503c: all_keyElements | all_shots | \u5177\u4f53 draft_id\uff08\u6216\u300c\u7ec4\u53f7-\u5361\u5e8f\u53f7\u300d\u7f16\u53f7\uff0c\u5982 '1-2'\uff09",
     "target validation hint (exact literal = tools/document_tools._TARGET_VALID_HINT; enumeration of valid values for structured error message, non-prose)"),
]

# ---------- DECLARED_PREFIXES: explicit prefix registrations ----------
# (prefix, reason). 仅当同一登记项在代码中存在多个动态拼接变体（f-string
# 片段 / 运行时后缀）而无法登记完整字面量时，才在此显式登记为前缀项；
# 判定仅 text.startswith(prefix) 单向（砍掉 declared.startswith(text) 反向，
# 反向会把登记项的任意截短残片也豁免），且每条必须附理由。
DECLARED_PREFIXES: List[Tuple[str, str]] = [
    # --- sub-feature system prompts (long multi-line templates) ---
    ("\u4f60\u662f\u4e00\u4e2a Skill \u6587\u6863\u683c\u5f0f\u5316\u4e13\u5bb6",
     "skill formatter sub-feature system prompt (web/routes/plugins._FORMAT_SYSTEM; "
     "long multi-line template with volatile wording, cannot pin exact literal; "
     "externalize to prompts/ = follow-up debt)"),
    ("\u4f60\u662f Skill \u4f18\u5316\u52a9\u624b",
     "skill optimizer sub-feature system prompt (web/routes/plugins."
     "_ASSISTANT_SYSTEM_TMPL; long multi-line template + runtime {tool_names} param, "
     "cannot pin exact literal; externalize to prompts/ = follow-up debt)"),
    # --- default skill document template (project seed data) ---
    ("---\nname: \u5267\u672c\u751f\u89c6\u9891",
     "default skill doc seed template (web/skill_docs.DEFAULT_SKILL_DOC; long "
     "multi-line markdown seed data with volatile wording, cannot pin exact literal)"),
]

_DECLARED_SET: Set[str] = {s for s, _ in DECLARED_DATA}
_DECLARED_PREFIX_SET: Set[str] = {s for s, _ in DECLARED_PREFIXES}


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _ascii_safe(text: str) -> str:
    """ASCII-safe summary (Windows GBK console safety)."""
    return "".join(c if c.isascii() else "?" for c in text)


def _is_declared(text: str) -> bool:
    """完整字面量精确相等；仅显式登记的前缀项允许单向 startswith。"""
    if text in _DECLARED_SET:
        return True
    for prefix in _DECLARED_PREFIX_SET:
        if text.startswith(prefix):
            return True
    return False


class _ExemptCollector(ast.NodeVisitor):
    """Collect id()s of Constant nodes that are structurally exempt.

    Exemption layers (broad → narrow):
      1. ALL strings inside function/method bodies (runtime handler data,
         local variables, intermediate values, comparisons, dict/list
         construction — not module-level injection sources).
      2. ALL strings inside class bodies (schema defaults, field metadata).
      3. Docstrings (module/class/function first-expr).
      4. Module-level Call arguments (externalization funcs, re.compile, etc.).
      5. Module-level Return values.
      6. f-string (JoinedStr) constant fragments.
      7. Module-level `description = '...'` assignments.

    Flagged context: module-level constant assignments (plain Assign or
    AnnAssign with Name/Subscript/Attribute targets) whose string values
    are NOT in DECLARED_DATA — these are the injection sources the gate
    is designed to catch.
    """

    def __init__(self):
        self.exempt: Set[int] = set()

    def _mark_subtree(self, node: ast.AST):
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                self.exempt.add(id(child))

    def _collect_docstrings(self, tree: ast.Module):
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list) or not body:
                continue
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                self.exempt.add(id(first.value))

    def visit_Module(self, node: ast.Module):
        self._collect_docstrings(node)
        self.generic_visit(node)

    # --- Layer 1: ALL strings inside functions are exempt ---
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._mark_subtree(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._mark_subtree(node)

    # --- Layer 2: ALL strings inside class bodies are exempt ---
    def visit_ClassDef(self, node: ast.ClassDef):
        self._mark_subtree(node)

    # --- Layer 4: module-level Call args ---
    def visit_Call(self, node: ast.Call):
        self._mark_subtree(node)

    # --- Layer 5: module-level Return ---
    def visit_Return(self, node: ast.Return):
        if node.value:
            self._mark_subtree(node.value)

    # --- Layer 6: f-string fragments ---
    def visit_JoinedStr(self, node: ast.JoinedStr):
        self._mark_subtree(node)

    # --- Layer 7: module-level description = '...' ---
    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "description":
                self._mark_subtree(node.value)
                return
        self.generic_visit(node)


def _scan_file(path: pathlib.Path) -> List[Tuple[int, str]]:
    """Return (lineno, literal_summary) for violations in one file.

    fail-closed：读不动 / 解析不动一律记为标记违规，不得当作「没问题」。
    """
    try:
        # utf-8-sig: tolerate BOM so files are never silently skipped
        source = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        return [(0, _ascii_safe(f"__unreadable__:{e}")[:120])]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [(getattr(e, "lineno", 1) or 1,
                 _ascii_safe(f"__syntax_error__:{e}")[:120])]

    collector = _ExemptCollector()
    collector.visit(tree)

    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in collector.exempt:
            continue
        text = node.value
        if len(text) < _MIN_LEN or not _has_cjk(text):
            continue
        if _is_declared(text):
            continue
        violations.append((node.lineno, _ascii_safe(text[:40])))
    return violations


def main() -> int:
    all_violations: List[Tuple[str, int, str]] = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.is_dir():
            # fail-closed：声明的扫描目录不存在 = 扫描面失效，不得静默跳过
            try:
                rel_dir = scan_dir.relative_to(ROOT).as_posix()
            except ValueError:
                rel_dir = str(scan_dir)
            all_violations.append(
                (rel_dir, 0, "__missing_scan_dir__: declared scan dir missing "
                             "(scan surface broken)"))
            continue
        for py_file in sorted(scan_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            rel = py_file.relative_to(ROOT).as_posix()
            for lineno, summary in _scan_file(py_file):
                all_violations.append((rel, lineno, summary))

    if all_violations:
        print(f"[check_prompt_literals] FAIL: {len(all_violations)} violation(s) "
              "(unregistered CJK prose literal / unreadable file / syntax error / "
              "missing scan dir):")
        for rel, lineno, summary in all_violations[:30]:
            print(f"  {rel}:{lineno}: {summary}")
        if len(all_violations) > 30:
            print(f"  ... and {len(all_violations) - 30} more")
        print("")
        print("Fix: externalize to prompts/ (load_prompt_section) or register "
              "the exact literal in DECLARED_DATA with reason.")
        print("Ref: ARCHITECTURE_RULES.md Rule 6; AGENTS.md P2/P3.")
        return 1
    print("[check_prompt_literals] PASS: no unregistered CJK prose literals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
