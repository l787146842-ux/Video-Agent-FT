"""提示词预算门禁（宪法 13.6 落地为 CI/pre-commit 断言，B1 清偿 D4）。

统计口径 = 「模型可见禁令」：
1. prompts/**/*.md 全文中的「严禁/不得」；
2. src/video_agent/{core,skill_runtime,web}/**/*.py 中字符串字面量里的「严禁/不得」，
   排除 docstring（模块/类/函数首语句）与注释（非模型可见）。

预算：合计 ≤ 8（宪法 13.6）。另断言：
- system_fc.md 文件字节 ≤ 7168（13.6 协议预算；文本协议 system.md 已退役，P2e 单轨收敛）；
- 动作定义唯一性：协议模板不再内联动作清单（文本动作定义已随 4-4 双轨退役删除，ADR-0001）；
- include 引用完整性：{{include:path}} 目标文件存在。

用法：python scripts/check_prompt_budget.py   （退出码非 0 即失败）
"""
import ast
import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
CODE_DIRS = ["src/video_agent/core", "src/video_agent/skill_runtime", "src/video_agent/web"]
BUDGET = 8
BYTE_BUDGET = 7168
BAN_RE = re.compile(r"严禁|不得")

# 已知非指令型字面量白名单（正则模式等），逐条注明原因
WHITELIST = [
    # spec_rules._NO_BLOCK_RE：匹配模型输出中自造「系统…不得…」块的剥离正则，非注入指令
    "src/video_agent/core/spec_rules.py",
]


def _docstring_ranges(path: pathlib.Path):
    """用 AST 精确定位全部 docstring 的行范围（模块/类/函数首语句）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ranges.append((body[0].lineno, getattr(body[0], "end_lineno", body[0].lineno)))
    return ranges


def iter_string_tokens(path: pathlib.Path):
    """产出非 docstring 的字符串字面量 token。"""
    src = path.read_text(encoding="utf-8")
    doc_ranges = _docstring_ranges(path)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except tokenize.TokenError:
        print(f"[check_prompt_budget] tokenize 失败: {path}")
        return
    for tok in tokens:
        if tok.type == tokenize.STRING:
            in_doc = any(a <= tok.start[0] <= b for a, b in doc_ranges)
            if in_doc:
                continue
            yield tok


def collect_violations() -> list:
    out = []
    # 1) prompts md
    for f in sorted(PROMPTS.rglob("*.md")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if BAN_RE.search(line):
                out.append(f"{f.relative_to(ROOT)}:{i}")
    # 2) 代码字符串字面量（排除注释与 docstring 近似）
    for d in CODE_DIRS:
        for f in sorted((ROOT / d).rglob("*.py")):
            if str(f.relative_to(ROOT)).replace("\\", "/") in WHITELIST:
                continue
            for tok in iter_string_tokens(f):
                if BAN_RE.search(tok.string):
                    out.append(f"{f.relative_to(ROOT)}:{tok.start[0]}")
    return out


def main() -> int:
    ok = True
    viols = collect_violations()
    print(f"[check_prompt_budget] 模型可见「严禁/不得」: {len(viols)} 处（预算 {BUDGET}）")
    for v in viols:
        print("  -", v)
    if len(viols) > BUDGET:
        ok = False

    for name in ("planner/system_fc.md",):
        f = PROMPTS / name
        size = f.stat().st_size
        status = "OK" if size <= BYTE_BUDGET else "OVER"
        print(f"[check_prompt_budget] {name}: {size} B（预算 {BYTE_BUDGET}）{status}")
        if size > BYTE_BUDGET:
            ok = False

    sys_text = (PROMPTS / "planner/system_fc.md").read_text(encoding="utf-8")
    if re.search(r"^- (add_group|update_draft|write_document|generate_image|generate_video):", sys_text, re.M):
        print("[check_prompt_budget] system_fc.md 仍内联动作清单（动作通道唯一 = FC 工具，ADR-0001）")
        ok = False

    for f in sorted(PROMPTS.rglob("*.md")):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\{\{include:([^}]+)\}\}", text):
            target = (PROMPTS / m.group(1).strip()).resolve()
            if not target.exists():
                print(f"[check_prompt_budget] include 目标缺失: {f.relative_to(ROOT)} -> {m.group(1)}")
                ok = False

    print("[check_prompt_budget]", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
