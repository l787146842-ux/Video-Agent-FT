"""持续评测流水线（814E5）：Skill 管线可解析性 + 指标报告。

用法：
    python scripts/run_eval_pipeline.py            # 报告输出到 stdout
    python scripts/run_eval_pipeline.py -o eval.json

退出码：frontmatter 边界例分级不符 → 1（CI 可据此失败）；否则 0。
（C1a 裁决 2026-08-31：黄金语料闸机校准退役——gate_corpus 评测删除；
skill manifest 可解析性评估保留，属加载底线。）
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.video_agent.skill_runtime import frontmatter  # noqa: E402
from src.video_agent.skill_runtime.manifest_schema import (  # noqa: E402
    split_issue_warnings,
)
from src.video_agent.web import skill_docs  # noqa: E402
from src.video_agent.web.port_wiring import install_core_ports  # noqa: E402

# D-01：core 端口装配（评测管线装配点）
install_core_ports()


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
        "manifest": {"flow": {"steps": ["开场"]}},
        "expect_error": True,
        "expect_warn": False,
        "note": "已废除 flow.steps 键 → 错误级 fail-hard（拒注册）",
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

    report = {"skill_pipelines": eval_skill_pipelines()}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    fm = report["skill_pipelines"]["frontmatter_mismatches"]
    if fm:
        print(f"[eval] frontmatter 边界例：{len(fm)} 条不一致 → 失败", file=sys.stderr)
        return 1
    print("[eval] frontmatter 边界例：分级符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
