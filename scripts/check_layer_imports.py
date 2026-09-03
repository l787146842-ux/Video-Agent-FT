# -*- coding: utf-8 -*-
"""层间导入方向门禁（R-8 裁决校正）。

规则（ARCHITECTURE_RULES §六/§十一 + R-8 业界分层定义）：
- core/** 与 tools/** 禁止 import web/**（含延迟导入/TYPE_CHECKING）。
- core/** 禁止 import adapters/**（基线内的存量边豁免，新增即拦）。
- adapters/** 禁止 import core/** 具体实现模块（端口/接口模块放行）。
- adapters/** → utils/** 放行（跨切面基础设施合法方向）。

AST 扫描 Import / ImportFrom 节点；字符串拼接等动态导入不在本门禁拦截面。
修复指引与文档指针见各规则 FIX_HINT。
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------- 规则数据 ----------

# R1: core/tools → web 禁止
R1_SCAN_DIRS = ("src/video_agent/core", "src/video_agent/tools")
R1_FORBIDDEN_PREFIX = "src.video_agent.web"
R1_FIX_HINT = "web 层能力请走 core/ports 端口或 storage 公开 API（ARCHITECTURE_RULES §六）"

# R2: core → adapters 禁止（基线豁免存量边）
R2_SCAN_DIRS = ("src/video_agent/core",)
R2_FORBIDDEN_PREFIX = "src.video_agent.adapters"
R2_FIX_HINT = "core 不得依赖 adapters；跨切面原语下沉 utils/ 或经 ports 端口倒置（ARCHITECTURE_RULES §六）"
# 存量基线：已全部清偿——cancel_token 下沉 utils/、Chat 契约（ChatResponse/
# StreamChunk/BaseChatAdapter）倒置到 core/chat_port.py、canvas 健康探测经
# core/ports.py 端口倒置。core→adapters 残留环边归零，基线收缩为空集（只减不增）。
R2_BASELINE = frozenset()

# R3: adapters → core 具体实现禁止（端口/接口模块放行）
R3_SCAN_DIRS = ("src/video_agent/adapters",)
R3_FORBIDDEN_PREFIX = "src.video_agent.core"
R3_FIX_HINT = "adapters 不得依赖 core 具体实现；跨切面原语下沉 utils/（ARCHITECTURE_RULES §六）"
# 放行：adapters 可引用的 core 端口/接口模块（业务常量与纯过滤函数）
R3_ALLOWED_CORE_MODULES = frozenset({
    "src.video_agent.core.provider_config",
    "src.video_agent.core.chat_port",
})


def _iter_py_files(scan_dirs):
    for d in scan_dirs:
        dirpath = ROOT / d
        if dirpath.exists():
            yield from sorted(dirpath.rglob("*.py"))


def _missing_scan_dirs() -> list:
    """声明的扫描目录不存在 = 扫描面失效（fail-closed：不得当作合规）。"""
    out = []
    seen = set()
    for d in R1_SCAN_DIRS + R2_SCAN_DIRS + R3_SCAN_DIRS:
        if d in seen:
            continue
        seen.add(d)
        if not (ROOT / d).is_dir():
            out.append((d, 0, "声明的扫描目录不存在（扫描面失效，不得当作合规）"))
    return out


def _package_parts(path: pathlib.Path) -> list:
    """文件所在包的点号部件（相对导入还原基准）。"""
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = path
    return list(rel.parent.parts)


def _resolve_relative(path: pathlib.Path, level: int, module: str) -> str:
    """按文件所在包上溯 level-1 层，把相对导入还原为绝对模块名。"""
    parts = _package_parts(path)
    up = level - 1
    if up > 0:
        parts = parts[:len(parts) - up] if up < len(parts) else []
    if module:
        parts = parts + module.split(".")
    return ".".join(parts)


# fail-closed 标记 → 人话标签（「扫不动」不得当作「没问题」）
_FAIL_CLOSED_MARKERS = (
    ("__syntax_error__", "语法解析失败"),
    ("__unreadable__", "文件读取失败"),
)


def _fail_closed_desc(mod: str):
    """mod 为 fail-closed 标记时返回违规描述，否则 None。"""
    for marker, label in _FAIL_CLOSED_MARKERS:
        if mod.startswith(marker):
            return f"{label}: {mod.split(':', 1)[1]}"
    return None


def _extract_imports(path: pathlib.Path):
    """提取文件全部 import 目标模块名 [(lineno, module_name)]。

    相对导入（level>=1）还原为绝对模块名后入结果集——否则
    `from ..adapters.x import y` 对 R1/R2/R3 全盲，已收缩为空的
    R2_BASELINE 可被相对导入静默接回环边。
    读不动 / 解析不动一律 fail-closed 为标记违规，不计作合规。
    """
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        return [(0, f"__unreadable__:{e}")]
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [(getattr(e, "lineno", 1) or 1, f"__syntax_error__:{e}")]
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            level = node.level or 0
            if level == 0:
                if mod:
                    results.append((node.lineno, mod))
            else:
                resolved = _resolve_relative(path, level, mod)
                if resolved:
                    results.append((node.lineno, resolved))
    return results


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _is_baseline_allowed(rel_path: str, module: str) -> bool:
    """检查 core→adapters 边是否在存量基线内。"""
    for base_file, base_mod in R2_BASELINE:
        if rel_path == base_file and _matches_prefix(module, base_mod):
            return True
    return False


def _is_core_module_allowed(module: str) -> bool:
    """检查 adapters→core 边是否引用放行的端口/接口模块。"""
    for allowed in R3_ALLOWED_CORE_MODULES:
        if _matches_prefix(module, allowed):
            return True
    return False


def violations() -> list:
    """扫描全部规则，返回违规清单 [(rel_path, lineno, desc)]。"""
    out = _missing_scan_dirs()

    for f in _iter_py_files(R1_SCAN_DIRS):
        rel = f.relative_to(ROOT).as_posix()
        for lineno, mod in _extract_imports(f):
            desc = _fail_closed_desc(mod)
            if desc:
                out.append((rel, lineno, desc))
            elif _matches_prefix(mod, R1_FORBIDDEN_PREFIX):
                out.append((rel, lineno,
                            f"import {mod}（禁止依赖 web 层）→ {R1_FIX_HINT}"))

    for f in _iter_py_files(R2_SCAN_DIRS):
        rel = f.relative_to(ROOT).as_posix()
        for lineno, mod in _extract_imports(f):
            if _fail_closed_desc(mod):
                continue  # R1 已报
            if _matches_prefix(mod, R2_FORBIDDEN_PREFIX):
                if not _is_baseline_allowed(rel, mod):
                    out.append((rel, lineno,
                                f"import {mod}（core 禁止新增 adapters 依赖）→ {R2_FIX_HINT}"))

    for f in _iter_py_files(R3_SCAN_DIRS):
        rel = f.relative_to(ROOT).as_posix()
        for lineno, mod in _extract_imports(f):
            desc = _fail_closed_desc(mod)
            if desc:
                out.append((rel, lineno, desc))
            elif _matches_prefix(mod, R3_FORBIDDEN_PREFIX):
                if not _is_core_module_allowed(mod):
                    out.append((rel, lineno,
                                f"import {mod}（adapters 禁止依赖 core 具体实现）→ {R3_FIX_HINT}"))

    return out


def main() -> int:
    failed = violations()
    total = sum(1 for _ in _iter_py_files(R1_SCAN_DIRS))
    total += sum(1 for _ in _iter_py_files(R3_SCAN_DIRS))
    print(f"[check_layer_imports] 扫描文件数: {total}"
          f"（{', '.join(R1_SCAN_DIRS + R3_SCAN_DIRS)}）")
    if failed:
        for rel, lineno, desc in failed:
            print(f"  - {rel}:{lineno}: {desc}")
        print(f"[check_layer_imports] FAIL: {len(failed)} 处违规依赖")
        return 1
    print("[check_layer_imports] OK: 层间导入方向合规")
    return 0


if __name__ == "__main__":
    sys.exit(main())
