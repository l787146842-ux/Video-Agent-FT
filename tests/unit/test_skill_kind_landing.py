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


def _kind_of(stem: str) -> str:
    text = (SKILLS_DIR / f"{stem}.md").read_text(encoding="utf-8")
    m = _KIND_LINE.search(text)
    return m.group(1) if m else ""


def test_aesthetic_skills_declare_style_kind():
    """四个美学型 Skill 的 kind 声明 = style（批 2.3 落地钉死）。"""
    for stem in sorted(STYLE_KIND_SKILLS):
        assert (SKILLS_DIR / f"{stem}.md").exists(), f"存量 Skill 缺失: {stem}"
        assert _kind_of(stem) == "style", f"{stem} kind 应回 style"


def test_no_skill_declares_unknown_or_reference_kind_yet():
    """全量口径：现存声明只允许 pipeline/style；
    reference 已下架（任务#8 ②），出现即回 WARN 降级，数据侧不允许再现。"""
    for f in sorted(SKILLS_DIR.glob("*.md")):
        kind = _kind_of(f.stem)
        assert kind in ("pipeline", "style"), (
            f"{f.name} kind={kind!r} 未登记于批 2.3 裁决口径")


def test_style_injection_note_wired_for_real_skill_name():
    """代码侧消费链在场：style kind → 风格层声明注入（与桩测试互补，
    这里钉 prompt_builder 差异化文案本身不丢失）。"""
    from src.video_agent.core.prompt_builder import (
        _KIND_STYLE_LAYER_NOTE,
        _kind_baseline_statement,
        _kind_block_suffix,
    )

    assert "风格层" in _kind_baseline_statement("style")
    assert "风格层" in _kind_block_suffix("style")
    # reference 已下架（任务#8 ②）：声明入口关闭后该分支不可达，
    # 不再钉死其文案（残留实现归 prompt_builder，待后续批次清理）。
    assert _KIND_STYLE_LAYER_NOTE in _kind_baseline_statement("style")
