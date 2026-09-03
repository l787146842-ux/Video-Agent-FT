# -*- coding: utf-8 -*-
"""Web 层 chat adapter 旁路门禁（I-2 旁路面拆除，2026-09-03 裁决 Q1 批准）。

根因：web/generation_dispatch.py 曾有两个 chat-completion 旁路函数（其符号名
已入 check_legacy_orchestration 退役清单锁死，本脚本不重述该字面），在
**web 层直接构造 OpenAICompatChatAdapter** 调 LLM，绕过 Planner/闸机/
StateManager（违宪法 Rule 1：Planner 唯一决策入口）。已删除并入
check_legacy_orchestration 符号锁死。本门禁再钉一条**结构面**防线：web/** 不得
直接实例化任何 *ChatAdapter——聊天 adapter 的唯一合法构造点是 adapters/factory.py
（在 web/** 之外），web 层若需 LLM 能力必须经 Planner 主循环或接收上游传入的
adapter 实例，不得自建旁路。

判定规则（按**导入符号表**，不按名字后缀字符串匹配）：
1. 先收集本文件的两张符号表：
   - adapter 类别名集（指向 *ChatAdapter 类的本地名）：
     `from m import XChatAdapter` / `... as A`（含 as 别名，别名正是后缀匹配的盲区）、
     `import m.XChatAdapter` / `... as A`、`class XChatAdapter:`（本文件内定义），
     以及赋值别名传递闭包：`A = XChatAdapter` / `A = mod.XChatAdapter` / `A = B`。
   - 模块名集（本文件中绑定到模块/包对象的本地名）：import 语句绑定的名字，
     以及 `m = importlib.import_module(...)` 的赋值目标。
2. 构造点判定：
   - `Name` 命中 adapter 别名集 → 直接构造（`OpenAICompatChatAdapter(...)`、`OCA(...)`）
   - `Attribute` 需**同时**满足：value 形如模块名（Name / Name.a.b 链）且
     ① attr 命中 adapter 别名集，或 ② attr 形如类名（首字母大写 + 以 ChatAdapter 结尾）
     且链根名命中模块名集（覆盖 `from pkg import mod` 后 `mod.XChatAdapter(...)`）。
     据此 `factory.buildChatAdapter()` / `getChatAdapter()` 这类**返回 adapter 的工厂
     方法调用不命中**（attr 首字母小写、且不在别名集）——名字后缀
     endswith("ChatAdapter") 会把它们误报成旁路。
   - `getattr(mod, "<...ChatAdapter>")(...)` 动态构造逃逸 → 命中。

正当工具性 LLM 调用不受影响（豁免边界）：
- web/history_compact.py 会话压缩摘要——**接收上游传入的 adapter 参数**调
  `adapter.chat(...)`，自身不实例化任何 ChatAdapter（非智能体决策入口、不产生
  状态变更，属正当工具性调用）。`adapter.chat(...)` 的 attr 是 `chat`，不在别名集，
  故 history_compact 天然豁免、无需白名单。

用 AST 而非 grep：忽略注释/字符串/import 语句本身/类型注解（`Optional[BaseChatAdapter]`
是 Subscript 非 Call，`from ... import XChatAdapter` 非 Call），只看真实构造调用。
fail-closed：扫不动 ≠ 没问题。SyntaxError → `__syntax_error__:`、OSError →
`__unreadable__:`、声明的扫描目录不存在 → `__missing_scan_dir__:`，一律计入违规
（与 check_layer_imports / check_prompt_literals 同一范式）。PASS 必须建立在
「扫过了且干净」之上，不能建立在「没扫」之上。

WHITELIST 当前为空（web/** 无任何合法直接构造）；若未来出现正当的
web 层工具性构造需求，在此按相对路径登记并附裁决日期。
输出纯 ASCII（N1/N7 乱码误读教训延续）。

用法：python scripts/check_web_chat_bypass.py   （退出码非 0 即失败）
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "src" / "video_agent" / "web"
# 合法直接构造 *ChatAdapter 的 web 文件（相对 ROOT 的 posix 路径）；当前为空——
# 聊天 adapter 唯一合法构造点在 adapters/factory.py（web 之外）。新增须附裁决日期。
WHITELIST = set()

_ADAPTER_SUFFIX = "ChatAdapter"

# fail-closed 标记前缀（扫描面失效一律计违规）
_MARK_SYNTAX = "__syntax_error__:"
_MARK_UNREADABLE = "__unreadable__:"
_MARK_MISSING_DIR = "__missing_scan_dir__:"
_SCAN_SURFACE_MARKS = (_MARK_SYNTAX, _MARK_UNREADABLE, _MARK_MISSING_DIR)

# 赋值别名传递闭包的最大迭代轮数（正常代码 1~2 轮即收敛，上限只是防环保险）
_ALIAS_MAX_ROUNDS = 8


def _ascii_safe(text: str) -> str:
    """ASCII-safe 摘要（Windows GBK 控制台安全，N1/N7 教训）。"""
    return "".join(c if c.isascii() else "?" for c in text)


def _is_module_like(node: ast.AST) -> bool:
    """value 形如模块名（`mod` / `pkg.mod` / `a.b.c` 的 Name-Attribute 链）。"""
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return isinstance(cur, ast.Name)


def _root_name(node: ast.AST) -> str:
    """取 Name/Attribute 链的根名（非链式返回空串）。"""
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else ""


def _is_import_module_call(node: ast.AST) -> bool:
    """识别 `importlib.import_module(...)`（动态模块对象赋值源）。"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "import_module"
    if isinstance(func, ast.Attribute):
        return func.attr == "import_module"
    return False


def _collect_module_names(tree: ast.AST) -> set:
    """收集本文件中绑定到模块/包对象的本地名（import 绑定 + import_module 赋值）。"""
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # `import a.b.c` 绑定的是首段名 a；`... as m` 绑定 m
                modules.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.Assign):
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and _is_import_module_call(node.value)):
                modules.add(node.targets[0].id)
    return modules


def _collect_adapter_names(tree: ast.AST) -> set:
    """收集本文件中「指向 *ChatAdapter 类」的本地名（含 as 别名与赋值别名）。"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name.endswith(_ADAPTER_SUFFIX):
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                last = alias.name.rsplit(".", 1)[-1]
                if last.endswith(_ADAPTER_SUFFIX):
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ClassDef):
            if node.name.endswith(_ADAPTER_SUFFIX):
                names.add(node.name)

    # 赋值别名传递闭包：A = XChatAdapter / A = mod.XChatAdapter / A = B
    for _ in range(_ALIAS_MAX_ROUNDS):
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            target = node.targets[0].id
            if target in names:
                continue
            value = node.value
            if isinstance(value, ast.Name) and value.id in names:
                names.add(target)
                grew = True
            elif (isinstance(value, ast.Attribute) and value.attr in names
                  and _is_module_like(value)):
                names.add(target)
                grew = True
        if not grew:
            break
    return names


def _getattr_construction(node: ast.Call, names: set):
    """识别 `getattr(mod, "<...ChatAdapter>")(...)` 动态构造；不命中返回 None。"""
    func = node.func
    if not (isinstance(func, ast.Call) and isinstance(func.func, ast.Name)
            and func.func.id == "getattr"):
        return None
    if len(func.args) < 2:
        return None
    arg = func.args[1]
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        return None
    symbol = arg.value
    if symbol.endswith(_ADAPTER_SUFFIX) or symbol in names:
        return 'getattr(<module>, "%s")(...)' % _ascii_safe(symbol)
    return None


def _is_class_shaped(attr: str) -> bool:
    """attr 形如类名：首字母大写 + 以 ChatAdapter 结尾（PEP8 CapWords）。

    用于把 `mod.OpenAICompatChatAdapter(...)`（类引用→构造）与
    `factory.buildChatAdapter()` / `getChatAdapter()`（动词前缀工厂方法→非构造）分开。
    """
    return attr.endswith(_ADAPTER_SUFFIX) and attr[:1].isupper()


def _scan_tree(tree: ast.AST, names: set, modules: set) -> list:
    """返回 [(lineno, desc)]：符号表命中的构造调用 + getattr 动态构造。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in names:
                out.append((getattr(node, "lineno", 0),
                            "%s(...)" % _ascii_safe(func.id)))
            continue
        if isinstance(func, ast.Attribute):
            # 仅 attr 命中别名集，或 attr 形如类名且链根是本文件的模块名 → 构造。
            # factory.buildChatAdapter() / getChatAdapter() 两条都不满足 → 不命中。
            module_like = _is_module_like(func)
            if module_like and func.attr in names:
                out.append((getattr(node, "lineno", 0),
                            "<module>.%s(...)" % _ascii_safe(func.attr)))
            elif (module_like and _is_class_shaped(func.attr)
                  and _root_name(func.value) in modules):
                out.append((getattr(node, "lineno", 0),
                            "%s.%s(...)" % (_ascii_safe(_root_name(func.value)),
                                            _ascii_safe(func.attr))))
            continue
        dynamic = _getattr_construction(node, names)
        if dynamic:
            out.append((getattr(node, "lineno", 0), dynamic))
    return out


def _rel_of(path: pathlib.Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return _ascii_safe(str(path))


def main() -> int:
    violations = []  # (rel, lineno, desc)

    if not WEB_DIR.is_dir():
        violations.append((_rel_of(WEB_DIR), 0,
                           _MARK_MISSING_DIR + " declared scan dir missing "
                                               "(scan surface broken, not a pass)"))

    for p in sorted(WEB_DIR.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = _rel_of(p)
        if rel in WHITELIST:
            continue
        try:
            source = p.read_text(encoding="utf-8-sig")
        except OSError as exc:
            violations.append((rel, 0,
                               _ascii_safe(_MARK_UNREADABLE + str(exc))[:160]))
            continue
        try:
            tree = ast.parse(source, filename=str(p))
        except SyntaxError as exc:
            violations.append((rel, getattr(exc, "lineno", 1) or 1,
                               _ascii_safe(_MARK_SYNTAX + str(exc))[:160]))
            continue
        names = _collect_adapter_names(tree)
        modules = _collect_module_names(tree)
        for lineno, desc in _scan_tree(tree, names, modules):
            violations.append((rel, lineno, desc))

    if violations:
        surface = [v for v in violations if v[2].startswith(_SCAN_SURFACE_MARKS)]
        bypass = [v for v in violations if not v[2].startswith(_SCAN_SURFACE_MARKS)]
        print("[check_web_chat_bypass] FAIL - %d hit(s): %d direct *ChatAdapter "
              "construction in web/**, %d scan-surface failure(s)."
              % (len(violations), len(bypass), len(surface)))
        for rel, lineno, desc in bypass[:20]:
            print("  BYPASS  %s:%d: %s" % (rel, lineno, desc))
        for rel, lineno, desc in surface[:20]:
            print("  SURFACE %s:%d: %s" % (rel, lineno, desc))
        if bypass:
            print("payoff: chat adapters must be built only in adapters/factory.py; the "
                  "web layer reaches LLM via the Planner loop or an injected adapter "
                  "instance, never a self-constructed bypass (Rule 1: Planner is the "
                  "sole entry).")
        if surface:
            print("fail-closed: an unreadable file / syntax error / missing scan dir is "
                  "a broken scan surface, NOT a clean result; fix the surface before "
                  "trusting this gate.")
        return 1
    print("[check_web_chat_bypass] PASS - no direct *ChatAdapter construction in web/**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
