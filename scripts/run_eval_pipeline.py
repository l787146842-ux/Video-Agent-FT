"""持续评测流水线：Skill 管线可解析性 + 指标报告。

用法：
    python scripts/run_eval_pipeline.py            # 报告输出到 stdout
    python scripts/run_eval_pipeline.py -o eval.json

退出码：
  - frontmatter 边界例分级不符 → 1
  - 存量 Skill 的 error 级 issues → 1（FAIL）
  - WARN 级仅进报告不 FAIL
  - 全绿 → 0
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
from src.video_agent.web.skill_docs import split_skill_sections  # noqa: E402

# D-01：core 端口装配（评测管线装配点）
install_core_ports()


def eval_skill_pipelines() -> dict:
    """管线可解析性评估：frontmatter 声明体检 + 活指标报告。

    存量 Skill error 级 issues 参与退出码（非零即 FAIL），
    WARN 级仅进报告不 FAIL。
    活指标：章节数、resource 引用可达性、frontmatter 键集。
    """
    report = []
    skill_errors_total = 0
    for doc in skill_docs.list_skill_docs():
        slug = doc.get("slug") or doc.get("name")
        manifest = frontmatter.load_manifest(slug)
        if manifest is None:
            continue
        issues = frontmatter.validate_manifest(manifest)
        errors, warnings = split_issue_warnings(issues)
        skill_errors_total += len(errors)
        # 活指标：章节数
        doc_path = skill_docs.skill_doc_path(slug)
        sections_count = 0
        resource_ok = True
        fm_keys = sorted(manifest.keys()) if isinstance(manifest, dict) else []
        if doc_path and doc_path.exists():
            content = doc_path.read_text(encoding="utf-8", errors="replace")
            _mf, body, _err = frontmatter.split_frontmatter(content)
            sections = split_skill_sections(body)
            sections_count = len([k for k, v in sections.items() if v.strip()])
            # resource 引用可达性：resources 声明的文件均存在
            resources = (manifest or {}).get("resources")
            if isinstance(resources, dict):
                for rel in resources:
                    if not (doc_path.parent / str(rel).replace("\\", "/")).is_file():
                        resource_ok = False
                        break
        report.append({
            "skill": doc.get("name") or slug,
            "sections_count": sections_count,
            "resource_reachable": resource_ok,
            "frontmatter_keys": fm_keys,
            "errors": errors,
            "warnings": warnings,
        })
    boundaries, bm = _eval_frontmatter_boundaries()
    return {
        "pipeline_skills": report,
        "pipeline_skill_count": len(report),
        "skill_errors_total": skill_errors_total,
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

    failed = False
    # 存量 Skill error 级 issues 参与退出码
    skill_errors = report["skill_pipelines"]["skill_errors_total"]
    if skill_errors:
        print(f"[eval] 存量 Skill error 级问题：{skill_errors} 条 → 失败",
              file=sys.stderr)
        failed = True
    else:
        print("[eval] 存量 Skill：无 error 级问题")

    # frontmatter 边界例分级
    fm = report["skill_pipelines"]["frontmatter_mismatches"]
    if fm:
        print(f"[eval] frontmatter 边界例：{len(fm)} 条不一致 → 失败",
              file=sys.stderr)
        failed = True
    else:
        print("[eval] frontmatter 边界例：分级符合预期")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
