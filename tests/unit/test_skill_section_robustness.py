"""五轮 S6：Skill 健壮性回归（#6 标题式解析静默沿用 / #7 resolve_entry 模糊匹配）。"""
import json
from pathlib import Path

import pytest

from src.video_agent.web.skill_docs import split_skill_sections
from src.video_agent.skill_runtime import registry

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/fixtures/skill_sections_golden.json"
SKILLS_DIR = ROOT / "data/skills"


def _skill_doc_path(stem: str) -> Path:
    """单一包形态（批3）：只认 <stem>/SKILL.md。"""
    return SKILLS_DIR / stem / "SKILL.md"


# ---------- #6 章节解析黄金快照（R6 模式：劣化即红） ----------

def test_s6_skill_sections_golden_pinned():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(golden) >= 15, "快照覆盖的存量 Skill 数量不得缩水"
    for stem, expected in golden.items():
        doc = _skill_doc_path(stem)
        assert doc.exists(), f"存量 Skill 缺失: {stem}"
        got = split_skill_sections(doc.read_text(encoding="utf-8"))
        got_fingerprint = {k: {"chars": len(v), "head": v.strip()[:40]} for k, v in got.items()}
        assert got_fingerprint == expected, (
            f"Skill「{stem}」章节解析漂移：阶段映射或章节内容变化"
            f"（got stages={sorted(got_fingerprint)}, expected={sorted(expected)}）"
        )


@pytest.mark.allow_degradation
def test_s6_heading_fallback_warns_on_silent_inherit():
    """连续 ≥3 节未命中关键字而沿用上一阶段 → 记降级遥测（静默沿用不再无声）。
    （A1/M4 两级制：切点只认 ##，用例同步从 # 级改为 ## 级。）"""
    from src.video_agent.utils import live_metrics

    content = (
        "## 分镜设计\n正文甲\n"
        "## 完全不认识的标题一\n正文乙\n"
        "## 完全不认识的标题二\n正文丙\n"
        "## 完全不认识的标题三\n正文丁\n"
    )
    key = "skill_docs.heading_fallback@_global"

    def _count() -> int:
        rec = live_metrics._DEGRADATIONS.get(key)
        return rec["count"] if rec else 0

    before = _count()
    split_skill_sections(content)
    assert _count() > before, "静默沿用未触发降级遥测"


# ---------- #7 resolve_entry 唯一命中 ----------

@pytest.fixture()
def two_similar_skills(monkeypatch):
    """注册两个近似名 Skill（古风短剧 / 古风甜宠短剧）"""
    registry.reset_registry()
    from src.video_agent.skill_runtime.registry import SkillEntry, _registry
    _registry["gu-feng"] = SkillEntry(slug="gu-feng", name="古风短剧", content="# x")
    _registry["gu-feng-tian"] = SkillEntry(slug="gu-feng-tian", name="古风甜宠短剧", content="# x")
    monkeypatch.setattr(registry, "_synced", True)
    yield
    registry.reset_registry()


def test_s6_resolve_entry_exact_and_unique(two_similar_skills):
    # 精确命中不受影响
    assert registry.resolve_entry("古风短剧").name == "古风短剧"
    # 唯一包含命中仍可解析
    assert registry.resolve_entry("甜宠").name == "古风甜宠短剧"


def test_s6_resolve_entry_multi_hit_returns_none(two_similar_skills):
    # 「古风」同时包含匹配两个 Skill → 拒绝错配返回 None（宁可要求选准）
    assert registry.resolve_entry("古风") is None
