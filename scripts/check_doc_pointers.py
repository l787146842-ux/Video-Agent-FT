"""引用完整性门禁（治理瘦身第一批：doc_pointers 与 arch_anchors
合并为一条门禁，检查能力取并集不缩水）。

五类检查：
1. ADR 取代关系双边注记：任一 ADR 头部「取代注记/被取代注记」行引用
   ADR-X，则 ADR-X 头部必须有注记行反向引用本 ADR（单边声明即 FAIL，
   防 ADR-0004 取代 ADR-0003 而 0003 无被取代注记一类漂移）。
2. ARCHITECTURE_RULES.md §十一 文件地图所列 src/video_agent 路径存在性
   （防 web/sse.py 一类死指针）。
3. src/video_agent 注释与 docstring 中引用的模块路径（形如 core/xxx.py、
   web/xxx.py）必须存在；且不得提及退役编排符号（复用
   check_legacy_orchestration 的 FORBIDDEN 清单，单一事实源，防两处漂移）。
4. docs/ 顶层活文档（docs/*.md，不含 adr/audit-history/archive 历史档案）
   中引用的模块路径（src/video_agent/... 全路径与 core/xxx.py 等包内相对
   路径）必须存在；删除线段（~~...~~）为已退役标注，豁免不受检。
5. 宪法锚点（原 check_arch_anchors 职责）：ARCHITECTURE_RULES 承重条款的
   路径 + 不变量符号存在性（锚点登记表 ANCHORS 在脚本内，人工审定的不变量
   登记表，非全文指针扫描）；锚点文件不可解析按漂移处理（不静默放行）。
   增删宪法承重条款时必须同批更新 ANCHORS（门禁冻结见 GOVERNANCE §13.14(f)）。
6. 治理文档脚本/夹具指针防腐（Q27 裁决 2026-09-01）：治理文档提及的
   scripts/check_*.py 与 tests/fixtures/* 必须存在（防 C1a 类删除后
   表述源忘同步再发生）；退役留痕表述用删除线段（~~...~~）标注豁免。
7. 闸机基线数字防腐（Q27）：GOVERNANCE §13.14(f) 冻结基线表的数字必须与
core/gate_registry.GATE_RULES / scripts/acceptance.GATES 实际长度一致。

退役条件（§13.14(c)，两源条件取并集）：指针/锚点漂移连续两季零检出、
ADR 双边注记、文件地图、docs 活文档模块路径与修宪同批更新锚点内化为开发
惯例时裁决下账；或宪法条款全面数据化（锚点并入机器可读登记表且 ANCHORS
清单清空）时裁决锚点部分下账。
输出纯 ASCII 前缀（验收乱码误读教训）。用法：python scripts/check_doc_pointers.py
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_legacy_orchestration as _legacy  # noqa: E402  退役符号清单单一事实源

ADR_DIR = ROOT / "docs" / "adr"
ARCH_RULES = ROOT / "ARCHITECTURE_RULES.md"
PKG = ROOT / "src" / "video_agent"

# 宪法锚点登记表（原 check_arch_anchors.py，随合并迁入）：
# (宪法条款, 相对路径, 顶层符号或 None 仅校验路径)。
ANCHORS = [
    # Rule 1：Planner 唯一入口
    ("Rule1", "src/video_agent/core/planner.py", "Planner"),
    # Rule 2：节点内有界模型循环唯一实现 + 多步上限每步实时读 settings（Q3）
    ("Rule2", "src/video_agent/core/agent_loop.py", "run_agent_loop"),
    # Rule 2：Workflow Runtime 账本+裁判数据层（主体回归，ADR-0004）
    ("Rule2", "src/video_agent/core/workflow_runtime.py", "WorkflowRuntime"),
    # Rule 2：动作语义唯一实现（故事板领域逻辑）
    ("Rule2", "src/video_agent/state/storyboard_ops.py", None),
    # Rule 2 层级例外清偿（D-01）：core 端口 + web 装配点注入
    ("Rule2-D01", "src/video_agent/core/ports.py", None),
    ("Rule2-D01", "src/video_agent/web/port_wiring.py", None),
    ("Rule2-D01", "src/video_agent/core/action_executor.py", None),
    # Rule 3：StateManager 唯一写入点
    ("Rule3", "src/video_agent/state/manager.py", "StateManager"),
    # Rule 4：外部调用必须走 Adapter
    ("Rule4", "src/video_agent/adapters/base_chat.py", "BaseChatAdapter"),
    ("Rule4", "src/video_agent/adapters/base.py", None),
    # Rule 5：Tool 统一注册（risk 分级 deny-by-default）
    ("Rule5", "src/video_agent/tools/base.py", "BaseTool"),
    # Rule 6：提示词外置单一事实源 + 闸机文案外置
    ("Rule6", "src/video_agent/utils/prompts.py", "load_prompt"),
    ("Rule6", "prompts/planner/system_fc.md", None),
    ("Rule6", "prompts/gates/messages.md", None),
    # Rule 7：画布边界（交互唯一封装）
    ("Rule7", "src/video_agent/adapters/canvas_adapter.py", None),
    # §2.0/§2.3：闸机管线唯一入口 + Policy-as-Data 注册表
    ("S2.0", "src/video_agent/core/guard_pipeline.py", None),
    ("S2.3", "src/video_agent/core/gate_registry.py", "GATE_RULES"),
    # §3：前端唯一入口（SolidJS SPA）与 web 装配
    ("S3", "src/web/app.tsx", None),
    ("S3", "src/video_agent/web/app.py", None),
    # 指令治理层（原第十三章迁出，与总纲同权）
    ("Ch13", "docs/GOVERNANCE.md", None),
]

# 注记行：头部清单行（- 开头）含「取代注记/被取代注记」
NOTE_LINE = re.compile(r"^- .*取代注记")
ADR_REF = re.compile(r"ADR-(\d{4})")
# 文件地图目录行 / 路径 token / 括号内附属模块（如 (+chat_opening/chat_consume)）
MAP_DIR = re.compile(r"├── ([A-Za-z_][\w]*)/")
MAP_PY = re.compile(r"[A-Za-z_][\w]*\.py")
MAP_PAREN = re.compile(r"\(\+([^)]+)\)")
# 注释/docstring 中模块路径引用（限 src/video_agent 顶层包，至少一级目录）
PATH_REF = re.compile(
    r"\b(core|web|state|tools|adapters|utils|skill_runtime|storage|eval)"
    r"(?:/[A-Za-z0-9_]+)+\.py\b"
)
# docs 活文档：全路径引用（src/video_agent/...）
DOC_FULL_REF = re.compile(r"src/video_agent(?:/[A-Za-z0-9_]+)+\.py\b")
# 删除线段（~~...~~）：已退役标注，剥除后不送检（防误伤历史表述）
STRIKE = re.compile(r"~~.*?~~", re.S)

# Q27 防腐（裁决 2026-09-01）：治理文档活清单（交接/历史档案类不受检）
GOV_DOCS = (
    "docs/GOVERNANCE.md",
    "ARCHITECTURE_RULES.md",
    "AGENTS.md",
    "docs/未清偿债务清单.md",
)
# 治理文档提及的闸机脚本/夹具指针（夹具要求带名，裸目录引用不受检）
GOV_SCRIPT_REF = re.compile(
    r"scripts/check_[A-Za-z0-9_]+\.py|tests/fixtures/[A-Za-z0-9_.][A-Za-z0-9_./]*")
# §13.14(f) 冻结基线表行（只认表格行，历史注记散文不受检）
BASELINE_RUNTIME_ROW = re.compile(r"\|\s*运行时闸机规则\s*\|\s*(\d+)\s*条")
BASELINE_GATES_ROW = re.compile(r"\|\s*验收门禁脚本\s*\|\s*(\d+)\s*项")


def check_adr_bilateral() -> list:
    """取代/被取代关系必须双边注记（单边声明即漂移）。"""
    hits = []
    texts = {}
    for p in sorted(ADR_DIR.glob("*.md")):
        m = re.match(r"(\d{4})", p.name)
        if m:
            texts[m.group(1)] = p.read_text(encoding="utf-8", errors="ignore")
    for num, text in texts.items():
        for line in text.splitlines():
            if not NOTE_LINE.match(line):
                continue
            for ref in ADR_REF.findall(line):
                if ref == num or ref not in texts:
                    continue
                # 对侧必须有一行注记反向引用本 ADR
                want = re.compile(rf"^- .*取代注记.*ADR-{num}")
                if not any(want.match(l) for l in texts[ref].splitlines()):
                    hits.append(
                        f"ADR-{num} note cites ADR-{ref} but ADR-{ref} has no "
                        f"reciprocal supersede note citing ADR-{num}"
                    )
    return hits


def check_arch_map() -> list:
    """宪法文件地图所列路径必须存在。"""
    hits = []
    text = ARCH_RULES.read_text(encoding="utf-8", errors="ignore")
    block = re.search(r"文件地图.*?```(.*?)```", text, re.S)
    if not block:
        return ["ARCHITECTURE_RULES.md file-map code block not found"]
    cur = None
    for line in block.group(1).splitlines():
        dm = MAP_DIR.search(line)
        if dm:
            cur = dm.group(1)
        if not cur:
            continue
        names = list(MAP_PY.findall(line))
        for grp in MAP_PAREN.findall(line):
            names += [n.strip() + ".py" for n in grp.split("/") if n.strip()]
        for name in names:
            # 目录内优先；顶层兜底（config.py/exceptions.py 与目录同行列举）
            if not (PKG / cur / name).exists() and not (PKG / name).exists():
                hits.append(f"file map pointer {cur}/{name} does not exist")
    return hits


def _docstring_spans(source: str) -> list:
    """ast 提取全部 docstring 的行区间（module/class/function 首语句）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    spans = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            val = body[0].value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                spans.append((val.lineno, val.end_lineno))
    return spans


def check_code_pointers() -> list:
    """注释/docstring：模块路径引用必须存在 + 不得提及退役编排符号。"""
    hits = []
    for p in sorted(PKG.rglob("*.py")):
        try:
            source = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = p.relative_to(ROOT).as_posix()
        lines = source.splitlines()
        spans = _docstring_spans(source)
        segments = []  # (lineno, text)
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                segments.append((i, line))
        for lo, hi in spans:
            segments.append((lo, "\n".join(lines[lo - 1:hi])))
        for lineno, text in segments:
            for ref in PATH_REF.finditer(text):
                path = ref.group(0)
                if not (PKG / path).exists():
                    hits.append(
                        f"{rel}:{lineno}: dead module pointer in comment/docstring: {path}"
                    )
            if _legacy.FORBIDDEN.search(text):
                hits.append(
                    f"{rel}:{lineno}: retired orchestration symbol in comment/docstring"
                )
    return hits


def check_docs_pointers() -> list:
    """docs 顶层活文档：模块路径引用必须存在（历史档案子目录不受检）。"""
    hits = []
    for p in sorted((ROOT / "docs").glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        rel = p.relative_to(ROOT).as_posix()
        for i, line in enumerate(text.splitlines(), 1):
            clean = STRIKE.sub("", line)
            for m in DOC_FULL_REF.finditer(clean):
                if not (ROOT / m.group(0)).exists():
                    hits.append(
                        f"{rel}:{i}: dead module pointer in doc: {m.group(0)}")
            for m in PATH_REF.finditer(clean):
                if not (PKG / m.group(0)).exists():
                    hits.append(
                        f"{rel}:{i}: dead module pointer in doc: {m.group(0)}")
    return hits


def _top_level_names(path: pathlib.Path):
    """ast 提取模块顶层定义符号（类/函数/异步函数/赋值/注解赋值）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return None  # 解析失败按漂移处理由调用方报错（不静默放行）
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


def check_anchors() -> list:
    """宪法锚点：承重条款的路径存在 + 不变量符号定义（原 arch_anchors 闸）。"""
    hits = []
    for clause, rel, symbol in ANCHORS:
        p = ROOT / rel
        if not p.exists():
            hits.append(f"[{clause}] anchor path missing: {rel}")
            continue
        if symbol is None or not rel.endswith(".py"):
            continue
        names = _top_level_names(p)
        if names is None:
            hits.append(f"[{clause}] anchor file not parseable: {rel}")
        elif symbol not in names:
            hits.append(
                f"[{clause}] invariant symbol '{symbol}' not defined in {rel}")
    return hits


def check_gov_script_pointers() -> list:
    """Q27：治理文档提及的闸机脚本/夹具必须存在（退役表述用删除线段豁免）。"""
    hits = []
    for rel in GOV_DOCS:
        p = ROOT / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            clean = STRIKE.sub("", line)
            for m in GOV_SCRIPT_REF.finditer(clean):
                ref = m.group(0).rstrip("/")
                if not (ROOT / ref).exists():
                    hits.append(
                        f"{rel}:{i}: governance doc points to missing "
                        f"script/fixture: {m.group(0)}")
    return hits


def check_gate_baseline_numbers() -> list:
    """Q27：GOVERNANCE §13.14(f) 基线数字必须与注册表/门禁表实际长度一致。

    删/增闸机同批改基线是登记义务；本断言防忘改（数字漂移即红）。
    导入失败（注册表不可解析）按漂移处理，不静默放行；
    GOVERNANCE 文件缺失时跳过（真实仓缺失已由 Ch13 锚点断言报漂移）。
    """
    gov = ROOT / "docs" / "GOVERNANCE.md"
    if not gov.exists():
        return []
    text = gov.read_text(encoding="utf-8", errors="ignore")
    rm = BASELINE_RUNTIME_ROW.search(text)
    am = BASELINE_GATES_ROW.search(text)
    if not rm or not am:
        return ["GOVERNANCE §13.14(f) baseline table rows not found "
                "(gate freeze baseline must stay registered)"]
    hits = []
    try:
        sys.path.insert(0, str(ROOT))
        from src.video_agent.core.gate_registry import GATE_RULES
        import acceptance as _acc
        actual_rules = len(GATE_RULES)
        actual_gates = len(_acc.GATES)
    except Exception as e:
        return [f"gate baseline sources not importable (no silent pass): {e}"]
    if int(rm.group(1)) != actual_rules:
        hits.append(
            f"GOVERNANCE §13.14(f) runtime-gate baseline {rm.group(1)} != "
            f"gate_registry.GATE_RULES actual {actual_rules}")
    if int(am.group(1)) != actual_gates:
        hits.append(
            f"GOVERNANCE §13.14(f) acceptance-gate baseline {am.group(1)} != "
            f"acceptance.GATES actual {actual_gates}")
    return hits


def main() -> int:
    fails = []
    fails += [f"[adr-bilateral] {h}" for h in check_adr_bilateral()]
    fails += [f"[arch-map] {h}" for h in check_arch_map()]
    fails += [f"[code-pointer] {h}" for h in check_code_pointers()]
    fails += [f"[docs-pointer] {h}" for h in check_docs_pointers()]
    fails += [f"[anchor] {h}" for h in check_anchors()]
    fails += [f"[gov-script-pointer] {h}" for h in check_gov_script_pointers()]
    fails += [f"[gate-baseline] {h}" for h in check_gate_baseline_numbers()]
    if fails:
        for h in fails[:30]:
            print(f"[ref_integrity]   {h}")
        print(
            f"[ref_integrity] FAIL: {len(fails)} reference-integrity issue(s). "
            "ADR supersede relations need bilateral notes; file-map and "
            "comment/docstring pointers must reference existing modules; "
            "docs/*.md module pointers must exist; "
            "retired orchestration symbols must not reappear in prose; "
            "constitutional anchors (paths + invariant symbols) must be "
            "updated in the same batch as the constitutional change; "
            "governance docs must not point to missing scripts/fixtures "
            "(retired mentions use ~~strike~~); §13.14(f) baseline numbers "
            "must match gate_registry/acceptance actual lengths."
        )
        return 1
    print(
        "[ref_integrity] PASS: ADR notes bilateral; arch file map valid; "
        "code/docs pointers clean; governance script/fixture pointers valid; "
        "gate baseline numbers consistent; "
        f"{len(ANCHORS)} constitutional anchors intact"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
