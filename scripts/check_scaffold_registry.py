"""脚手架注册表门禁（正向设计改造 2-1）。

三项检查：
1. 棘轮：scaffold 类计数只降不升（> SCAFFOLD_COUNT_BASELINE 即 FAIL；
   拆除后随降基线，禁止上调——上调须书面裁决并同批修改本文件）；
2. 每条 component 符号可导入（module 或 module:attr 形态），防登记僵尸条目；
3. scaffold 类条目必须带可证伪 assumption 与 retest_policy（折旧前提）。

用法：python scripts/check_scaffold_registry.py（退出码 0 = PASS）。

退役条件：脚手架类全部退役、注册计数归零时裁决下账，
本门禁连同注册表一并清退。
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.video_agent.core.scaffold_registry import (  # noqa: E402
    SCAFFOLD_COUNT_BASELINE,
    scaffold_entries,
    SCAFFOLDS,
)


def _importable(component: str) -> bool:
    mod_path, _, attr = component.partition(":")
    try:
        mod = importlib.import_module(mod_path)
    except Exception:
        return False
    if not attr:
        return True
    obj = mod
    for part in attr.split("."):
        if not hasattr(obj, part):
            return False
        obj = getattr(obj, part)
    return True


def main() -> int:
    failures = []

    n_scaffold = len(scaffold_entries())
    if n_scaffold > SCAFFOLD_COUNT_BASELINE:
        failures.append(
            f"scaffold count {n_scaffold} > baseline {SCAFFOLD_COUNT_BASELINE} "
            "(ratchet only-down; raise baseline only with written ruling)"
        )

    for e in SCAFFOLDS:
        if not _importable(e.component):
            failures.append(f"{e.sid}: component not importable: {e.component}")
        if e.classification == "scaffold":
            if not e.assumption.strip():
                failures.append(f"{e.sid}: scaffold missing falsifiable assumption")
            if not e.retest_policy.strip():
                failures.append(f"{e.sid}: scaffold missing retest_policy")

    if failures:
        print("[check_scaffold_registry] FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        f"[check_scaffold_registry] PASS - {len(SCAFFOLDS)} entries "
        f"(scaffold {n_scaffold} <= baseline {SCAFFOLD_COUNT_BASELINE}); "
        "all components importable"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
