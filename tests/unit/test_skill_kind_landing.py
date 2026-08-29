# -*- coding: utf-8 -*-
"""整改批 2.3：kind 落地——美学型 Skill 声明 style 注入策略（真实数据钉死）。

历史问题（C-kind 空转）：manifest_schema/registry/prompt_builder 的
style/reference 差异化注入分支齐备，但全部 16 个存量 Skill 一律声明
pipeline，差异化注入对真实数据永不生效。本批按用户裁决把四个美学型
Skill 落地为 kind: style；本文件钉死数据侧声明与代码侧消费的对应关系，
防止回潮成「分支在、数据空」的空转态。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"

# 用户裁决（三波整改计划批次 2.3）：美学型 → style；其余保持 pipeline。
# 任务#8 ②：reference kind 已裁决下架（声明入口关闭，存量无数据承载；
# prompt_builder 内残留分支随声明入口关闭变为死路径，待后续批次清理）。
STYLE_KIND_SKILLS = {
    "李安美学风格短片",
    "水墨风格武侠短片",
    "叙事驱动的美学视频",
    "宣言式概念短片",
}

_KIND_LINE = re.compile(r"^kind:\s*(\S+)\s*$", re.M)


def _skill_doc(stem: str) -> Path:
    """单一包形态（批3）：只认 <stem>/SKILL.md。"""
    return SKILLS_DIR / stem / "SKILL.md"


def _iter_skill_docs():
    for p in sorted(SKILLS_DIR.iterdir(), key=lambda x: x.name):
        if p.is_dir() and not p.name.startswith("."):
            main = p / "SKILL.md"
            if main.exists():
                yield p.name, main


def _kind_of(stem: str) -> str:
    text = _skill_doc(stem).read_text(encoding="utf-8")
    m = _KIND_LINE.search(text)
    return m.group(1) if m else ""


def test_aesthetic_skills_declare_style_kind():
    """四个美学型 Skill 的 kind 声明 = style（批 2.3 落地钉死）。"""
    for stem in sorted(STYLE_KIND_SKILLS):
        assert _skill_doc(stem).exists(), f"存量 Skill 缺失: {stem}"
        assert _kind_of(stem) == "style", f"{stem} kind 应回 style"


def test_no_skill_declares_unknown_or_reference_kind_yet():
    """全量口径：现存声明只允许 pipeline/style；
    reference 已下架（任务#8 ②），出现即回 WARN 降级，数据侧不允许再现。"""
    for stem, _f in _iter_skill_docs():
        kind = _kind_of(stem)
        assert kind in ("pipeline", "style"), (
            f"{stem} kind={kind!r} 未登记于批 2.3 裁决口径")


def test_style_kind_display_note_wired_for_real_skill_name():
    """代码侧消费链在场：style kind → 元数据头「类型」展示行（目录展示口径）。
    任务#12 批次B：差异化正文注入分支退役，kind 语义保留在注册表解析与
    元数据头展示；_KIND_LABELS 文案不丢失。"""
    from src.video_agent.core.prompt_builder import _KIND_LABELS

    assert "风格型" in _KIND_LABELS["style"]
    assert "流程型" in _KIND_LABELS["pipeline"]
    # 展示口径钉死：真实美学型 Skill 的元数据头携带风格型类型行；
    # 该存量 Skill 超预算，选中段附 read_skill 续读指引（批4/ADR-0007）。
    from src.video_agent.core.prompt_builder import PromptBuilder
    from src.video_agent.web import skill_docs

    pb = PromptBuilder(
        lambda: skill_docs,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )
    block = pb.build_selected_skill_block("李安美学风格短片")
    assert "类型：风格型（美学指导）" in block
    assert "read_skill" in block
