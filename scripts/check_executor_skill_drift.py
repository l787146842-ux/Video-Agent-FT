"""执行器常量 × Skill 章节双写漂移扫描（阶段 5，半自动审计）。

执行器 _TASK/_BOUNDARY 常量含规则表述（如「title 不超过 20 字」），
Skill 章节也有产出规范——两处数字约束可能漂移。本脚本提取两侧
「数字+字/秒」约束并并排输出，供季度审计人工比对；退出码恒 0
（审计输出，不进 acceptance 门禁）。

用法：python scripts/check_executor_skill_drift.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_CONST_RE = re.compile(r"(_[A-Z_]+(?:TASK|BOUNDARY)[A-Z_]*)\s*=\s*\((.*?)\)", re.S)
_NUM_CONSTRAINT_RE = re.compile(r"不超过\s*\d+\s*(?:字|秒|s)|≤\s*\d+\s*(?:字|秒|s)|至少\s*\d+")


def scan_executors() -> list:
    out = []
    for p in sorted((ROOT / "src" / "video_agent" / "skill_runtime").glob("exec_*.py")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for name, body in _CONST_RE.findall(text):
            hits = _NUM_CONSTRAINT_RE.findall(body)
            if hits:
                out.append((p.name, name, hits))
    return out


def scan_skills() -> list:
    out = []
    for p in sorted((ROOT / "data" / "skills").glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        hits = _NUM_CONSTRAINT_RE.findall(text)
        if hits:
            out.append((p.name, hits[:12]))
    return out


def main() -> int:
    print("== executor constants (numeric constraints) ==")
    for fname, name, hits in scan_executors():
        print(f"  {fname}:{name} -> {hits}")
    print("== skill docs (numeric constraints, first 12) ==")
    for fname, hits in scan_skills():
        print(f"  {fname} -> {hits}")
    print("[check_executor_skill_drift] INFO: compare the two sides manually "
          "(quarterly audit; not a gate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
