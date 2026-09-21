# -*- coding: utf-8 -*-
"""阶段展示标签口径统一单测（2026-09-21 批I，事故 4444/Q6①）。

**背景**：用户指出「`storyboard_key_elements`，标签是这个，名字直接给中文翻译
就行了啊。『关键元素拆解』只是我平常跟 ai 沟通的术语，结果就写上去了」。

取证（本文件钉死的事实）：
- Skill 文档用 `<tag>` 字段分章节，**全部 Skill 同一字段名完全一致**
  （实测 `tool_sections(skill, "storyboard_key_elements")` 16/16 命中）；
- 注入本身没问题（按 `<tag>…</tag>` 正则取，`web/skill_docs.py`）；
- 但平台另有一套 `STAGE_LABELS` 自造术语（「关键元素拆解」「媒体提示词编写」），
  与模型手里的章节字段**对不上号** —— 这正是 Q6① 的诱导源；
- 前端 `skill-structure.ts::SECTION_META` **早就是直译口径**（关键元素/音频层/
  组装导出），只有后端是异类。

**本批口径**：`STAGE_LABELS` / `NODE_TITLES` / `CANONICAL_STAGES` 的标签
= **英文 tag 的直译**，与前端 `SECTION_META` 同口径。

**防回潮**：下方三条钉分别锁「不得回潮自造术语」「不得与前端漂移」
「同名节点两条展示链必须一致」。改标签值本身是允许的（纯文案），
但回潮旧术语或与前端分叉会立即失败。
"""
from pathlib import Path

import pytest

from src.video_agent.core import stage_probes as po
from src.video_agent.core import workflow_contract as wc
from src.video_agent.skill_runtime.registry import STAGE_LABELS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SKILL_STRUCTURE = PROJECT_ROOT / "src" / "web" / "lib" / "skill-structure.ts"

# 批I 之前的自造术语（回潮即失败）——「关键元素拆解」是用户口头术语被误写进代码
_RETIRED_LABELS = ("关键元素拆解", "媒体提示词编写")

# STAGE_LABELS 键 → 前端 SECTION_META 的对应键（两侧同源 tag，值必须一致）
_STAGE_TO_FRONTEND_KEY = {
    "storyboard_key_elements": "storyboard_key_elements",
    "storyboard_shots": "storyboard_shots",
    "storyboard_audio": "storyboard_audio",
    "video_assembler": "video_assembler",
}


def _frontend_section_labels() -> dict:
    """从 skill-structure.ts 抽 SECTION_META 的 tag → label（源码级读取）。

    不 import TS（跨语言）：按行正则抓 `tag: { label: '...'` 形态。
    """
    import re

    text = FRONTEND_SKILL_STRUCTURE.read_text(encoding="utf-8")
    start = text.index("const SECTION_META")
    end = text.index("};", start)
    body = text[start:end]
    pairs = re.findall(r"^\s*([a-z_]+):\s*\{\s*label:\s*'([^']+)'", body, re.M)
    return {k: v for k, v in pairs}


# ---------- ① 不得回潮自造术语 ----------

def test_stage_labels_do_not_use_retired_terms():
    """`STAGE_LABELS` 不得回潮「关键元素拆解」「媒体提示词编写」等自造术语。

    4444/Q6① 病根：这套术语是**平台自造**的（grep Skill 文档零命中），
    与模型手里的 `<tag>` 字段对不上，逼模型自行推断"这俩是不是一回事"。
    """
    for key, label in STAGE_LABELS.items():
        for retired in _RETIRED_LABELS:
            assert retired not in label, (
                f"STAGE_LABELS[{key!r}] 回潮自造术语「{retired}」（4444/Q6①）——"
                f"标签口径应为英文 tag 直译")


def test_workflow_node_titles_do_not_use_retired_terms():
    """`NODE_TITLES` 中与 Skill 阶段同名的节点，同样不得回潮自造术语。"""
    for key in ("storyboard_key_elements", "storyboard_shots", "storyboard_audio"):
        label = wc.NODE_TITLES[key]
        for retired in _RETIRED_LABELS:
            assert retired not in label, (
                f"NODE_TITLES[{key!r}] 回潮「{retired}」（批I 已对齐直译口径）")


# ---------- ② 前后端不得漂移（同一 tag 一个名字） ----------

def test_stage_labels_match_frontend_section_meta():
    """后端 `STAGE_LABELS` 与前端 `SECTION_META` 对同源 tag 必须同名。

    批I 前的实况：前端叫「关键元素」「音频层」「组装导出」，后端叫
    「关键元素拆解」「音频层设计」「时间线组装」——**同一阶段两个名字**，
    用户看到的卡片标题与章节名分叉。
    """
    fe = _frontend_section_labels()
    assert fe, "前端 SECTION_META 解析失败（结构变了，请同步本测试的抽取逻辑）"
    for stage_key, fe_key in _STAGE_TO_FRONTEND_KEY.items():
        assert fe_key in fe, f"前端 SECTION_META 缺 {fe_key!r}"
        assert STAGE_LABELS[stage_key] == fe[fe_key], (
            f"前后端标签漂移：STAGE_LABELS[{stage_key!r}]="
            f"{STAGE_LABELS[stage_key]!r} vs SECTION_META={fe[fe_key]!r}"
            f"（同一 Skill 章节 tag，两侧必须同名）")


# ---------- ③ 同名节点在两条展示链上必须一致 ----------

def test_same_named_nodes_agree_across_tables():
    """与 Skill 阶段同名的 workflow 节点，标题须与 `STAGE_LABELS` 一致。

    `NODE_TITLES`（机械停卡/账本回放）与 `STAGE_LABELS`（卡片/下发）是两条
    独立展示链；同名键各叫一个名字会让同一阶段在历史回放与实时卡片上对不上。
    """
    for key in ("storyboard_key_elements", "storyboard_shots", "storyboard_audio"):
        assert wc.NODE_TITLES[key] == STAGE_LABELS[key], (
            f"同名键两条展示链不一致：NODE_TITLES[{key!r}]="
            f"{wc.NODE_TITLES[key]!r} vs STAGE_LABELS={STAGE_LABELS[key]!r}")


def test_assembly_stage_agrees_between_tables():
    """组装阶段在 `STAGE_LABELS`（video_assembler）与 `CANONICAL_STAGES`
    （assembly）上的标题一致（批I 由「时间线组装」统一为「组装导出」）。"""
    assert STAGE_LABELS["video_assembler"] == "组装导出"
    titles = {s.key: s.title for s in po.CANONICAL_STAGES}
    assert titles["assembly"] == "组装导出", (
        "CANONICAL_STAGES 的 assembly 标题与 STAGE_LABELS 分叉")


# ---------- ④ 直译口径的事实基座 ----------

def test_labels_are_direct_translations_of_tags():
    """核心三键确为英文 tag 直译（本批口径的基座，防被"改得好听"带偏）。"""
    assert STAGE_LABELS["storyboard_key_elements"] == "关键元素"
    assert STAGE_LABELS["storyboard_shots"] == "分镜"
    assert STAGE_LABELS["storyboard_audio"] == "音频层"
    # 平台自有动作（非 Skill 章节）保持描述性措辞，不强行直译
    assert STAGE_LABELS["image_generate"] == "生图"
    assert STAGE_LABELS["generate_video"] == "视频生成"


def test_platform_only_nodes_keep_descriptive_titles():
    """**没有对应 Skill 章节字段**的平台节点保持原措辞（不强行改直译）。

    `write_spec` / `review_*` / `ke_media` / `shot_media` 是平台动作
    （规格撰写/审核/出图），Skill 里没有同名 tag，直译无从谈起——
    批I 只统一**有对应 tag 的键**，不扩大打击面。
    """
    assert wc.NODE_TITLES["write_spec"] == "制片规格撰写"
    assert wc.NODE_TITLES["review_key_elements"] == "关键元素审核"
    assert wc.NODE_TITLES["ke_media"] == "关键元素出图"
    assert wc.NODE_TITLES["shot_media"] == "逐镜视频生成"
