# -*- coding: utf-8 -*-
"""interaction 全域 reducer 收敛护栏（R-13=A 裁决落地）。

机械断言：src/ 下除 workflow_runtime.py 外，不存在对 interaction 字典的
直接写入（subscript 赋值 / setdefault / state_dict["interaction"] 赋值）。
所有 interaction 写入必须经 workflow_runtime reducer 族。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "video_agent"

# 唯一豁免文件（reducer 族定义处）
_EXEMPT = SRC / "core" / "workflow_runtime.py"

# 违规模式（正则）
_PATTERNS = [
    # interaction["key"] = ... / interaction['key'] = ...
    re.compile(r"""interaction\s*\[.+?\]\s*=""", re.DOTALL),
    # interaction.setdefault(
    re.compile(r"""interaction\.setdefault\("""),
    # state_dict["interaction"] = ...
    re.compile(r"""state_dict\s*\[\s*["']interaction["']\s*\]\s*="""),
]


def _iter_py_files(root: Path):
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_no_direct_interaction_writes_outside_reducer():
    """src/ 下除 workflow_runtime.py 外禁止 interaction 直写。"""
    hits: list[str] = []
    for path in _iter_py_files(SRC):
        if path.resolve() == _EXEMPT.resolve():
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            # 跳过纯注释行
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pat in _PATTERNS:
                if pat.search(line):
                    rel = path.relative_to(ROOT)
                    hits.append(f"{rel}:{lineno}: {stripped.rstrip()}")
                    break
    assert not hits, (
        "interaction 直写违规（应走 workflow_runtime reducer 族）:\n"
        + "\n".join(hits)
    )
