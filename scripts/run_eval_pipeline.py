"""持续评测流水线（814E5）：黄金语料回归 + Skill 管线可解析性 + 指标报告。

用法：
    python scripts/run_eval_pipeline.py            # 报告输出到 stdout
    python scripts/run_eval_pipeline.py -o eval.json

退出码：黄金语料出现误杀/漏放 → 1（CI 可据此失败）；否则 0。
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.video_agent.core import fc_gates, guard_pipeline, prompt_gates  # noqa: E402
from src.video_agent.skill_runtime import frontmatter  # noqa: E402
from src.video_agent.skill_runtime.manifest_schema import (  # noqa: E402
    split_issue_warnings,
)
from src.video_agent.web import skill_docs  # noqa: E402
from src.video_agent.web.port_wiring import install_core_ports  # noqa: E402

# D-01：core 端口装配（评测管线装配点；黄金语料回归直驱执行器需 web 实现注入）
install_core_ports()

CORPUS = PROJECT_ROOT / "tests" / "fixtures" / "gate_corpus" / "corpus.json"

# 规则级断言映射（批 10：expect_rule 从仅记录升级为硬断言）：
# 拦截样本的 hard 文案必须来自声明的规则维度（防拦截归因漂移）
_RULE_HARD_MARKERS = {
    "skill.shot_min_chars": "过短",
    "skill.element_min_chars": "过短",
    "skill.cjk_min_ratio": prompt_gates.LANG_EN_HARD_PREFIX,
    "skill.require_duration": "缺少镜头时长",
    "skill.require_subtitle": "缺少字幕负面约束",
    "skill.require_audio_layer": "缺少音频层",
    "skill.require_camera_language": "缺少镜头语言",
    # 复合签发点（P6）：结构总闸的硬伤按维度签发、归因统一为
    # skill.prompt_structure，标记取组合拦截文案稳定前缀（format_gate_errors），
    # 断言时对 guard_pipeline 的 reject_message 而非单维度 hard 明细
    "skill.prompt_structure": "提示词结构校验未通过",
    "platform.gen_confirm": "生成确认闸拦截",
}


def _eval_entry(e: dict, rules: dict) -> tuple:
    """按 kind 分派到真实判定实现，返回 (blocked, 拦截文案池)。

    shot/keyElement 走 validate_prompt_write（结构闸）；gen_confirm /
    spec_gate 为活跃流程闸边界样本，直驱 guard_pipeline / fc_gates 的
    唯一组合实现（语料与真实判定同源，不在评测侧重写判定）。
    新增 kind 的可选扩展键（drafts/override/skill）只服务于对应分派。
    """
    kind = e["kind"]
    if kind == "gen_confirm":
        err, _warns = guard_pipeline.evaluate_gen_confirm(
            e.get("drafts") or [],
            active=True,
            override=e.get("override", False),
            action="eval",
        )
        return err is not None, [err or ""]
    if kind == "spec_gate":
        ctx = fc_gates.GateContext(
            injected_skill=str(e.get("skill") or ""), state=lambda: {},
        )
        err = fc_gates.flow_gate(ctx, "storyboard_create_group")
        return err is not None, [err or ""]
    ok, hard, _soft = prompt_gates.validate_prompt_write(
        e["prompt"], kind, {}, rules=rules,
    )
    return (not ok), list(hard)


def eval_gate_corpus() -> dict:
    entries = json.loads(CORPUS.read_text(encoding="utf-8"))
    mismatches = []
    for e in entries:
        rules = prompt_gates.parse_gate_rules("")
        # manifest 声明 → 合成到 rules（与 parse_gate_rules 的 manifest 覆盖同语义）
        manifest = e.get("manifest") or None
        if manifest:
            for key, val in (manifest.get("gates") or {}).items():
                if key in rules:
                    rules[key] = val
        blocked, texts = _eval_entry(e, rules)
        expect = bool(e.get("expect_blocked"))
        if blocked != expect:
            mismatches.append({
                "id": e["id"], "expected_blocked": expect, "actual_blocked": blocked,
            })
        elif expect and e.get("expect_rule"):
            # 规则级断言（批 10）：hard 文案必须命中声明规则维度的标记
            rule = e["expect_rule"]
            if rule == "skill.prompt_structure":
                # 复合闸归因（P6）：经 guard_pipeline 复合签发点核验——
                # verdict rule_id 归一为 skill.prompt_structure，且组合拦截
                # 文案含稳定前缀（strict 下拒收形态）
                out = guard_pipeline.evaluate_prompt_write(
                    e["prompt"], e["kind"], {}, gate_rules=rules, mode="strict",
                )
                if out.ok or not any(v.rule_id == rule for v in out.verdicts):
                    mismatches.append({
                        "id": e["id"], "expected_rule": rule,
                        "actual_verdicts": [
                            {"rule_id": v.rule_id, "ok": v.ok}
                            for v in out.verdicts
                        ],
                    })
                    continue
                texts = [out.reject_message]
            marker = _RULE_HARD_MARKERS.get(rule)
            if marker and not any(marker in t for t in texts):
                mismatches.append({
                    "id": e["id"], "expected_rule": rule,
                    "actual_hard": texts,
                })
    total = len(entries)
    return {
        "corpus_total": total,
        "corpus_mismatches": mismatches,
        "corpus_accuracy": round((total - len(mismatches)) / total, 4) if total else 1.0,
    }


def eval_skill_pipelines() -> dict:
    """管线可解析性按 frontmatter 声明通道评估（任务#5：flow.steps 抄本废除，
    正文 planner 是唯一流程源；此处评估 frontmatter 声明体检与阶段覆盖声明）。

    P6 增补 frontmatter 边界例：真实 Skill 轨道只含绿样本，声明 schema 的
    fail-hard / WARN 分级边界行为用合成声明直驱 validate_manifest 钉死。
    """
    report = []
    for doc in skill_docs.list_skill_docs():
        slug = doc.get("slug") or doc.get("name")
        manifest = frontmatter.load_manifest(slug)
        if manifest is None:
            continue
        flow = manifest.get("flow") or {}
        issues = frontmatter.validate_manifest(manifest)
        report.append({
            "skill": doc.get("name") or slug,
            "stage_executors": len(flow.get("stage_executors") or {}),
            "stages": len(flow.get("stages") or {}),
            "issues": issues,
        })
    boundaries, bm = _eval_frontmatter_boundaries()
    return {
        "pipeline_skills": report,
        "pipeline_skill_count": len(report),
        "frontmatter_boundaries": boundaries,
        "frontmatter_mismatches": bm,
    }


# frontmatter 声明边界例（P6）：合成声明 → 期望的问题分级，直驱
# manifest_schema 单一实现（不在评测侧重写校验逻辑）。
_FRONTMATTER_BOUNDARY_CASES = (
    {
        "id": "fm_failhard_deprecated",
        "manifest": {"flow": {"steps": ["开场"]}, "gates": {"unknown_gate": True}},
        "expect_error": True,
        "expect_warn": False,
        "note": "已废除 flow.steps 键 + 未知 gate 键 → 错误级 fail-hard（拒注册）",
    },
    {
        "id": "fm_zombie_warn",
        "manifest": {"flow": {"stage_executors": {"1": ["skill_section_run"]}}},
        "expect_error": False,
        "expect_warn": True,
        "note": "僵尸键 stage_executors → WARN 级过渡告警（不拒注册）",
    },
)


def _eval_frontmatter_boundaries() -> tuple:
    """逐例跑 validate_manifest，按错误级/告警级与期望对账。
    返回 (report, mismatches)。"""
    results, mismatches = [], []
    for c in _FRONTMATTER_BOUNDARY_CASES:
        issues = frontmatter.validate_manifest(c["manifest"])
        errs, warns = split_issue_warnings(issues)
        got_error, got_warn = bool(errs), bool(warns)
        results.append({"id": c["id"], "errors": errs, "warnings": warns})
        if got_error != c["expect_error"] or got_warn != c["expect_warn"]:
            mismatches.append({
                "id": c["id"],
                "expected": {"error": c["expect_error"], "warn": c["expect_warn"]},
                "actual": {"error": got_error, "warn": got_warn},
            })
    return results, mismatches


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="", help="报告输出文件（JSON）")
    args = ap.parse_args()

    report = {"gate_corpus": eval_gate_corpus(), "skill_pipelines": eval_skill_pipelines()}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    mm = report["gate_corpus"]["corpus_mismatches"]
    fm = report["skill_pipelines"]["frontmatter_mismatches"]
    if mm or fm:
        if mm:
            print(f"[eval] 黄金语料回归：{len(mm)} 条不一致 → 失败", file=sys.stderr)
        if fm:
            print(f"[eval] frontmatter 边界例：{len(fm)} 条不一致 → 失败", file=sys.stderr)
        return 1
    print("[eval] 黄金语料回归：全部一致；frontmatter 边界例：分级符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
