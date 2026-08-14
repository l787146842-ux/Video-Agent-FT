"""黄金语料校准钉死（宪法 §2.6 / 814E5）：误杀/漏放计数劣化即测试失败。

语料期望按 S1 语义校准：技能闸须 manifest 声明后生效；require_at_ref 走
客观补印不拦截；平台地板（最短字数/中文占比）无条件生效。
"""
import json
from pathlib import Path

from scripts.run_eval_pipeline import eval_gate_corpus, eval_skill_pipelines

CORPUS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "gate_corpus" / "corpus.json"


def test_corpus_no_mismatch():
    report = eval_gate_corpus()
    assert report["corpus_mismatches"] == [], (
        f"黄金语料回归劣化：{report['corpus_mismatches']}"
    )
    assert report["corpus_accuracy"] == 1.0


def test_corpus_manifest_bidirectional():
    """同一提示词：声明闸的 Skill 拦 / 关闭闸的 Skill 放（manifest 双向验证存在）"""
    entries = {e["id"]: e for e in json.loads(CORPUS.read_text(encoding="utf-8"))}
    assert entries["documentary_relaxed"]["expect_blocked"] is False
    assert entries["documentary_relaxed"]["manifest"]["gates"]["require_duration"] is False
    assert entries["shot_missing_duration"]["expect_blocked"] is True


def test_skill_pipelines_parseable():
    report = eval_skill_pipelines()
    assert report["pipeline_skill_count"] >= 5, "存量 Skill 管线应可解析"
    with_deps = [s for s in report["pipeline_skills"] if s["deps"]]
    assert with_deps, "至少一个 Skill 声明了依赖关系（E2 调度可用）"
