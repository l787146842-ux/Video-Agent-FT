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

from src.video_agent.core import prompt_gates  # noqa: E402
from src.video_agent.skill_runtime import sidecar  # noqa: E402
from src.video_agent.web import skill_docs  # noqa: E402

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
}


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
        ok, hard, _soft = prompt_gates.validate_prompt_write(
            e["prompt"], e["kind"], {}, rules=rules,
        )
        blocked = not ok
        expect = bool(e.get("expect_blocked"))
        if blocked != expect:
            mismatches.append({
                "id": e["id"], "expected_blocked": expect, "actual_blocked": blocked,
            })
        elif expect and e.get("expect_rule"):
            # 规则级断言（批 10）：hard 文案必须命中声明规则维度的标记
            marker = _RULE_HARD_MARKERS.get(e["expect_rule"])
            if marker and not any(marker in h for h in hard):
                mismatches.append({
                    "id": e["id"], "expected_rule": e["expect_rule"],
                    "actual_hard": hard,
                })
    total = len(entries)
    return {
        "corpus_total": total,
        "corpus_mismatches": mismatches,
        "corpus_accuracy": round((total - len(mismatches)) / total, 4) if total else 1.0,
    }


def eval_skill_pipelines() -> dict:
    """0818 B4：管线可解析性改按 sidecar 声明通道评估（正文正则通道退役）。"""
    report = []
    for doc in skill_docs.list_skill_docs():
        slug = doc.get("slug") or doc.get("name")
        manifest = sidecar.load_sidecar(slug)
        flow = ((manifest or {}).get("flow") or {})
        steps = flow.get("steps") or {}
        deps = flow.get("dependencies") or {}
        if not steps:
            continue
        issues = sidecar.validate_sidecar(manifest)
        report.append({
            "skill": doc.get("name") or slug,
            "steps": len(steps),
            "deps": len(deps),
            "issues": issues,
        })
    return {"pipeline_skills": report, "pipeline_skill_count": len(report)}


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
    if mm:
        print(f"[eval] 黄金语料回归：{len(mm)} 条不一致 → 失败", file=sys.stderr)
        return 1
    print("[eval] 黄金语料回归：全部一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
