"""提示词预算门禁（宪法 13.6 落地为 CI/pre-commit 断言，B1 清偿 D4）。

统计口径 = 「模型可见禁令」：
1. prompts/**/*.md 全文中的「严禁/不得」；
2. src/video_agent/{core,skill_runtime,web}/**/*.py 中字符串字面量里的「严禁/不得」，
   排除 docstring（模块/类/函数首语句）与注释（非模型可见）。

预算：合计 ≤ 8（宪法 13.6）。另断言：
- system_fc.md 文件字节 ≤ 7168（13.6 协议预算；文本协议 system.md 已退役，P2e 单轨收敛）；
- 动作定义唯一性：协议模板不再内联动作清单（文本动作定义已随 4-4 双轨退役删除，ADR-0001）；
- include 引用完整性：{{include:path}} 目标文件存在。

Skill 直注禁令独立账本（C6，任务#22）：data/skills/*.md 的「严禁/不得」
不并入 BUDGET=8，单独计账：当前 WARN 观察项（正文清洗留长期路线图 #33），
基线棘轮锁死当前计数（166）——超过基线即 FAIL，只降不升。

另附运行时观察项（P3-17，非硬门禁不影响退出码）：
- 读 live_metrics 落盘的组装样本（data/prompt_sections.jsonl），统计组装总长
  P95，>48k 字符只在输出中 WARN，供周报观察。

用法：python scripts/check_prompt_budget.py   （退出码非 0 即失败）
"""
import ast
import io
import json
import math
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
# Skill 直注禁令独立账本（C6）：data/skills/*.md 行级命中基线棘轮，只降不升；
# 下调基线需同步完成对应存量的正文清洗（长期路线图 #33）。
SKILLS_MD_DIR = ROOT / "data" / "skills"
SKILL_BAN_BASELINE = 164
# 运行时组装总长观察阈值（字符）：P95 超限仅 WARN（周报观察项，不作硬门禁）
P95_WARN_CHARS = 48000
SECTIONS_SAMPLE_FILE = ROOT / "data" / "prompt_sections.jsonl"

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


def collect_skill_ban_violations() -> list:
    """Skill 直注禁令独立账本（C6）：data/skills/*.md 行级「严禁/不得」命中。

    与 BUDGET=8 主账本分离（Skill 正文清洗留长期路线图 #33，不在本门禁扩面）。
    """
    out = []
    for f in sorted(SKILLS_MD_DIR.glob("*.md")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if BAN_RE.search(line):
                out.append(f"{f.relative_to(ROOT)}:{i}")
    return out


def runtime_total_p95():
    """从 live_metrics 落盘样本读组装总长序列，返回 (P95, 样本数)；无样本返回 (None, 0)。

    样本由 core/live_metrics.record_sections 在真实运行时追加（pytest 不落盘），
    坏行忽略（样本文件允许有历史噪声）。"""
    if not SECTIONS_SAMPLE_FILE.exists():
        return None, 0
    totals = []
    for line in SECTIONS_SAMPLE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        t = rec.get("total")
        if isinstance(t, int) and t >= 0:
            totals.append(t)
    if not totals:
        return None, 0
    totals.sort()
    idx = max(0, math.ceil(0.95 * len(totals)) - 1)
    return totals[idx], len(totals)


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

    # 4.5）Skill 直注禁令独立账本（C6）：WARN 观察项 + 基线棘轮（超基线 FAIL）
    skill_viols = collect_skill_ban_violations()
    if len(skill_viols) > SKILL_BAN_BASELINE:
        print(
            f"[check_prompt_budget] Skill 直注禁令 {len(skill_viols)} 处"
            f"（基线 {SKILL_BAN_BASELINE}，棘轮只降不升）FAIL"
        )
        ok = False
    else:
        print(
            f"[check_prompt_budget] Skill 直注禁令独立账本: {len(skill_viols)} 处"
            f"（基线 {SKILL_BAN_BASELINE}，棘轮锁死）WARN-观察项（不并入 BUDGET={BUDGET}）"
        )

    # 5）运行时组装总长遥测（P3-17 周报观察项：只 WARN 不失败，不改退出码）
    p95, n = runtime_total_p95()
    if p95 is None:
        print("[check_prompt_budget] 运行时组装样本：无（data/prompt_sections.jsonl 缺失或无有效样本，观察项跳过）")
    else:
        flag = "WARN" if p95 > P95_WARN_CHARS else "OK"
        print(f"[check_prompt_budget] 运行时组装总长 P95={p95} 字符（样本 {n} 条，观察阈值 {P95_WARN_CHARS}）{flag}")

    print("[check_prompt_budget]", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
