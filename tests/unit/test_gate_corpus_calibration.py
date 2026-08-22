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


def test_corpus_rule_coverage():
    """批 10 扩编钉死：每个活跃结构闸至少 1 合法 + 1 应拦样本，总量 ≥30
    （评测驱动：规则级断言防拦截归因漂移，样本量防校准空心化）"""
    entries = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert len(entries) >= 30, f"语料规模劣化：{len(entries)} < 30"
    active_rules = (
        "skill.shot_min_chars", "skill.element_min_chars", "skill.cjk_min_ratio",
        "skill.require_duration", "skill.require_subtitle",
        "skill.require_camera_language", "skill.require_audio_layer",
    )
    for rule in active_rules:
        blocked = [
            e for e in entries
            if e.get("expect_blocked") and e.get("expect_rule") == rule
        ]
        assert blocked, f"规则 {rule} 缺应拦样本"
    # 合法样本覆盖：放行样本总量（无 expect_blocked）
    legal = [e for e in entries if not e.get("expect_blocked")]
    assert len(legal) >= 8, f"合法样本不足：{len(legal)}"


def test_corpus_manifest_bidirectional():
    """同一提示词：声明闸的 Skill 拦 / 关闭闸的 Skill 放（manifest 双向验证存在）"""
    entries = {e["id"]: e for e in json.loads(CORPUS.read_text(encoding="utf-8"))}
    assert entries["documentary_relaxed"]["expect_blocked"] is False
    assert entries["documentary_relaxed"]["manifest"]["gates"]["require_duration"] is False
    assert entries["shot_missing_duration"]["expect_blocked"] is True


def test_skill_pipelines_parseable():
    """任务#5：flow.steps/dependencies 抄本通道废除，deps 口径随退；
    可解析性钉 frontmatter 体检零问题 + 阶段调度声明（stage_executors/stages）存在。"""
    report = eval_skill_pipelines()
    assert report["pipeline_skill_count"] >= 5, "存量 Skill 管线应可解析"
    for s in report["pipeline_skills"]:
        assert s["issues"] == [], f"{s['skill']} frontmatter 体检异常: {s['issues']}"
    with_sched = [
        s for s in report["pipeline_skills"]
        if s["stage_executors"] or s["stages"]]
    assert with_sched, "至少一个 Skill 声明了阶段调度（stage_executors/stages）"
