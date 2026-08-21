"""执行器常量 × Skill 章节双写漂移棘轮门禁（audit-0819d 改造 4）。

背景（四维对齐评估）：执行器 _TASK/_BOUNDARY 常量含规则表述（如「title 不超过
20 字」），Skill 章节也有产出规范——同一约束主体两处数字若不一致即「漂移对」。
业界姿势 = 约束单一事实源；清偿完成前的过渡机制为棘轮：

- 按「约束主体词 + 数字」两侧配对，主体相同而数字集合不同 = 漂移对；
- 漂移对计数只降不升：> DRIFT_BASELINE 即 FAIL；清偿一对即同批下调基线
  （与脚手架棘轮同一惯例）；
- 人工比对的并排输出保留（--verbose）。

审核整改批 2 新增：执行器 capability 登记断言（deny-by-default）——
每个已注册 Skill 执行器必须在 skill_runtime/capability.py 的
EXECUTOR_CAPABILITY 有登记，未登记即 FAIL（防新增隐形空壳执行器）。

用法：
    python scripts/check_executor_skill_drift.py            # 门禁（退出码判定）
    python scripts/check_executor_skill_drift.py --verbose  # 附两侧明细
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 棘轮基线：漂移对计数上限（只降不升；清偿一对同批下调，禁止上调）
DRIFT_BASELINE = 0

_CONST_RE = re.compile(r"(_[A-Z_]+(?:TASK|BOUNDARY)[A-Z_]*)\s*=\s*\((.*?)\)", re.S)
# 数字约束 + 前置上下文（用于提取约束主体词）
_CONSTRAINT_FULL_RE = re.compile(
    r"(.{0,14}?)(不超过|≤|至少)\s*(\d+(?:\.\d+)?)\s*(字|秒|s)?", re.S
)
# 主体词 = 上下文末尾的英文标识符或 ≥2 字中文词
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|[\u4e00-\u9fff]{2,}")


def _constraints_of(text: str) -> dict:
    """提取 主体词 → 数字集合（同主体多个约束合并）。"""
    out: dict = {}
    for ctx, _op, num, _unit in _CONSTRAINT_FULL_RE.findall(text or ""):
        tokens = _TOKEN_RE.findall(ctx)
        if not tokens:
            continue
        subject = tokens[-1].strip().lower()
        if not subject:
            continue
        out.setdefault(subject, set()).add(float(num))
    return out


def scan_executors() -> list:
    """执行器侧：(文件名, 常量名, 主体→数字集合)"""
    out = []
    for p in sorted((ROOT / "src" / "video_agent" / "skill_runtime").glob("exec_*.py")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for name, body in _CONST_RE.findall(text):
            cons = _constraints_of(body)
            if cons:
                out.append((p.name, name, cons))
    return out


def scan_skills() -> list:
    """Skill 侧：(文件名, 主体→数字集合)"""
    out = []
    for p in sorted((ROOT / "data" / "skills").glob("*.md")):
        cons = _constraints_of(p.read_text(encoding="utf-8", errors="ignore"))
        if cons:
            out.append((p.name, cons))
    return out


def detect_drift(executors: list, skills: list) -> list:
    """主体词两侧都有而数字集合不同 = 漂移对。"""
    skill_side: dict = {}
    for _fname, cons in skills:
        for subject, nums in cons.items():
            skill_side.setdefault(subject, set()).update(nums)
    pairs = []
    for fname, name, cons in executors:
        for subject, nums in cons.items():
            if subject in skill_side and skill_side[subject] != nums:
                pairs.append(
                    f"{fname}:{name} 主体「{subject}」执行器={sorted(nums)} "
                    f"vs Skill 侧={sorted(skill_side[subject])}"
                )
    return pairs


def _executor_tool_names() -> set:
    """registry.SKILL_EXECUTOR_TOOLS 展平后的执行器工具名（AST 解析，含 splat）。"""
    src = (ROOT / "src" / "video_agent" / "skill_runtime" / "registry.py").read_text(encoding="utf-8")
    tuples: dict = {}
    for node in ast.parse(src).body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Tuple)):
            continue
        name = node.targets[0].id
        if name not in ("STORYBOARD_STRUCTURE_TOOLS", "SKILL_EXECUTOR_TOOLS"):
            continue
        vals = []
        for el in node.value.elts:
            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                vals.append(el.value)
            elif isinstance(el, ast.Starred) and isinstance(el.value, ast.Name):
                vals.extend(tuples.get(el.value.id, []))
        tuples[name] = vals
    return set(tuples.get("SKILL_EXECUTOR_TOOLS", []))


def _capability_registered() -> set:
    """capability.EXECUTOR_CAPABILITY 已登记的执行器名（AST 解析，兼容带注解赋值）。"""
    path = ROOT / "src" / "video_agent" / "skill_runtime" / "capability.py"
    if not path.exists():
        return set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None)
        if not (isinstance(target, ast.Name) and target.id == "EXECUTOR_CAPABILITY"
                and isinstance(node.value, ast.Dict)):
            continue
        return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


def check_capability_registration() -> list:
    """未登记 capability 的已注册执行器名单（空 = 合规）。"""
    return sorted(_executor_tool_names() - _capability_registered())


def main() -> int:
    verbose = "--verbose" in sys.argv[1:]
    executors = scan_executors()
    skills = scan_skills()
    if verbose:
        print("== executor constants (subject -> numbers) ==")
        for fname, name, cons in executors:
            print(f"  {fname}:{name} -> "
                  + ", ".join(f"{k}={sorted(v)}" for k, v in sorted(cons.items())))
        print("== skill docs (subject -> numbers) ==")
        for fname, cons in skills:
            print(f"  {fname} -> "
                  + ", ".join(f"{k}={sorted(v)}" for k, v in sorted(cons.items())))
    pairs = detect_drift(executors, skills)
    if pairs:
        print(f"[check_executor_skill_drift] 漂移对 {len(pairs)} 条：")
        for line in pairs:
            print("  - " + line)
    else:
        print("[check_executor_skill_drift] 无漂移对")
    if len(pairs) > DRIFT_BASELINE:
        print(f"[check_executor_skill_drift] FAIL：漂移对 {len(pairs)} > 基线 "
              f"{DRIFT_BASELINE}（棘轮只降不升；清偿一对同批下调基线）")
        return 1
    missing = check_capability_registration()
    if missing:
        print(f"[check_executor_skill_drift] FAIL：执行器未登记 capability 注册表 "
              f"(deny-by-default)：{', '.join(missing)}"
              f"——新增执行器必须在 skill_runtime/capability.py 登记能力级别")
        return 1
    print(f"[check_executor_skill_drift] PASS（{len(pairs)} <= 基线 {DRIFT_BASELINE}，"
          f"capability 登记全覆盖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
