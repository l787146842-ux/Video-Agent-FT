# -*- coding: utf-8 -*-
"""层间导入方向门禁（整改批 3.3 设立）。

规则（ARCHITECTURE_RULES §六/§十一 + D-01 端口先例的机械化）：
- core/** 与 tools/** 一律禁止 import src.video_agent.web.*（含延迟导入/
  TYPE_CHECKING）；跨层需要 web 能力时走 core/ports 端口（D-01）或
  core/storage 公开 API（批 3.3 下沉先例）。
- AST 扫描 Import / ImportFrom 节点，字符串拼接等动态导入不在本门禁
  拦截面（动态导入本身受 check_legacy_orchestration 等其他治理约束）。

退役条件：core/tools 对 web 的反向依赖连续两季
零检出、端口与公开 API 模式内化为开发惯例时裁决下账。
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = ("src/video_agent/core", "src/video_agent/tools")
FORBIDDEN_MODULE_PREFIX = "src.video_agent.web"


def _iter_py_files():
    for d in SCAN_DIRS:
        yield from sorted((ROOT / d).rglob("*.py"))


def violations_in_file(path: pathlib.Path) -> list:
    """返回该文件的违规清单 [(lineno, 描述)]；语法错误按违规计（防绕过）。"""
    out = []
    try:
        # utf-8-sig：容忍历史文件头的 UTF-8 BOM（U+FEFF）
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except SyntaxError as e:
        return [(getattr(e, "lineno", 1) or 1, f"语法解析失败: {e}")]
    for node in ast.walk(tree):
        rel = path.relative_to(ROOT).as_posix()
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(FORBIDDEN_MODULE_PREFIX):
                    out.append((node.lineno,
                                f"import {alias.name}（{rel} 禁止依赖 web 层）"))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            level = node.level or 0
            # 相对导入不指向本包顶层之下的 web 子树，当前包内不存在相对进入
            # web 的路径形态；仅绝对模块名参与判定
            if level == 0 and (
                    mod == FORBIDDEN_MODULE_PREFIX
                    or mod.startswith(FORBIDDEN_MODULE_PREFIX + ".")):
                names = ", ".join(a.name for a in node.names)
                out.append((node.lineno,
                            f"from {mod} import {names}（{rel} 禁止依赖 web 层）"))
    return out


def main() -> int:
    failed = []
    total = 0
    for f in _iter_py_files():
        total += 1
        for lineno, desc in violations_in_file(f):
            failed.append(f"{f.relative_to(ROOT).as_posix()}:{lineno}: {desc}")
    print(f"[check_layer_imports] 扫描文件数: {total}（{', '.join(SCAN_DIRS)}）")
    if failed:
        for v in failed:
            print("  -", v)
        print(f"[check_layer_imports] FAIL: {len(failed)} 处反向依赖"
              "（web 层能力请走 core/ports 端口或 storage 公开 API）")
        return 1
    print("[check_layer_imports] OK: core/tools 零 web 层反向依赖")
    return 0


if __name__ == "__main__":
    sys.exit(main())
