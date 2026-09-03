# -*- coding: utf-8 -*-
"""Provider 注入工具名字面量门禁（I-3 声明驱动，2026-09-03 裁决 Q1 批准）。

根因：core/fc_tool_runner.py 的 execute() 曾对 image_generate（single/batch 双分支）
与 generate_video 按工具名字面量写 if/elif 特例注入 provider，违背项目 policy-as-data
范式。修复后 provider 注入统一走「查工具 provider_kind 声明 → core/provider_injection
统一注入器」。

门禁范围（精准、不脆弱误报，只覆盖 provider 注入轴）：只锁**声明了
provider_kind 的生成类工具名**（当前 = image_generate / generate_video，由 tools/**.py
的类声明 AST 动态发现，新增 provider 工具自动纳管）。断言这些工具名不作为
**字符串常量（含子串）**出现在 core/fc_tool_runner.py 中。
本门禁只钉死 provider 注入轴这一条不变量：调度器对 provider 工具名不得写
字面量特例分支（必经 provider_kind 声明→注入器）。它**不**宣称「调度器不认
任何具体工具名」——调度器对 workflow_pause / storyboard_* / read_* 等非-provider
工具名的字面量引用属其他调度职责，不在本门禁边界内。

为何用 AST 而非 grep：
- 忽略注释——fc_tool_runner 内说明「消除 image_generate/generate_video 特例」的
  留痕注释合法含这些词，grep 会误报；AST 只看真实字符串常量节点。
- 只锁 provider 工具而非「任何已注册工具名」：调度器对 workflow_pause（暂停后
  处理）/ storyboard_*（建组账本）/ read_*（只读回喂类工具白名单，用于抑制
  SSE_ACTIONS_APPLIED 状态快照下发，见 fc_tool_runner.py 的 `name not in (…read_*…)`
  判定；与已退役的只读并行无关）等的字面量引用属其**其他调度职责**、
  非 provider 注入根因，不在本门禁范围（blanket 锁会误伤且超出 I-3 边界）。

provider 工具名事实源 = tools/**.py 中 `provider_kind = "..."` 非空的工具类的
`name = "..."`（与运行时 BaseTool 子类发现同源口径，见 core/provider_injection）。
输出纯 ASCII（N1/N7 乱码误读教训延续）。

用法：python scripts/check_fc_tool_name_literals.py   （退出码非 0 即失败）
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "src" / "video_agent" / "tools"
RUNNER = ROOT / "src" / "video_agent" / "core" / "fc_tool_runner.py"


def _class_str_attr(node: ast.ClassDef, attr: str):
    """取类体内 `attr = "<常量>"` 的字符串值（无则 None）。"""
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == attr:
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        return stmt.value.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id == attr and isinstance(stmt.value, ast.Constant) \
                    and isinstance(stmt.value.value, str):
                return stmt.value.value
    return None


def _discover_provider_tool_names():
    """AST 扫描 tools/**.py，收集声明了非空 provider_kind 的工具类 name。"""
    names = set()
    for p in sorted(TOOLS_DIR.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            kind = _class_str_attr(node, "provider_kind")
            if not kind or not kind.strip():
                continue
            tool_name = _class_str_attr(node, "name")
            if tool_name and tool_name.strip():
                names.add(tool_name.strip())
    return names


def _runner_string_literals():
    """AST 收集 fc_tool_runner.py 中全部字符串常量值（忽略注释）。

    防绕过归一：
    - ast.walk 已递归到 f-string（JoinedStr）内部的 Constant 片段，自然覆盖；
    - 相邻字符串字面量隐式拼接（"a" "b"）Python AST 已折叠为单一 Constant；
    - 额外重建每个 JoinedStr 的字面片段拼接（concat 其 Constant.values），
      兼顾工具名跨 f-string 字面片段拼接的形态。
    匹配阶段再按「常量值含任一 provider 工具名子串」判定（非整串相等），
    使模块级变量间接引用（字面仍需以 Constant 形式出现）与包裹字串均不可遗漏。
    """
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.value, getattr(node, "lineno", 0)))
        elif isinstance(node, ast.JoinedStr):
            # f-string 字面片段拼接（跳过 FormattedValue 动态部分）
            frag = "".join(
                v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            if frag:
                out.append((frag, getattr(node, "lineno", 0)))
    return out


def main() -> int:
    provider_names = _discover_provider_tool_names()
    if not provider_names:
        # 事实源为空说明发现逻辑失效（工具声明形态变更）——门禁自身失效即红，
        # 不静默 PASS（避免形同虚设）。
        print("[check_fc_tool_name_literals] FAIL - discovered no provider_kind tools; "
              "discovery logic stale (expected image_generate/generate_video).")
        return 1
    literals = _runner_string_literals()
    # 子串包含判定（非整串相等）：防拼接/f-string/包裹字串绕过；
    # 注释已被 AST 天然排除，放宽不误报。
    violations = [
        (v, ln) for (v, ln) in literals
        if any(pn in v for pn in provider_names)
    ]
    if violations:
        print(f"[check_fc_tool_name_literals] FAIL - provider tool name literal(s) "
              f"hardcoded in fc_tool_runner.py ({len(violations)} hit(s)):")
        for v, ln in violations[:20]:
            print(f"  core/fc_tool_runner.py:{ln}: {v!r}")
        print("payoff: provider injection must be declaration-driven - dispatch via "
              "core/provider_injection.inject() keyed on the tool's provider_kind, "
              "never an `if name == \"<tool>\"` branch in the runner.")
        return 1
    print("[check_fc_tool_name_literals] PASS - no provider tool name literal in "
          f"fc_tool_runner.py (locked: {', '.join(sorted(provider_names))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
