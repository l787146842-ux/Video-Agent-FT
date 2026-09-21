# -*- coding: utf-8 -*-
"""Workflow node declarations — 16 节点 DAG 已随 2026-09-10 改造退役，
仅保留：① 用户梳理的 6 个关键步骤暂停点清单；② 平铺节点标题表
（机械停卡文案与账本回放展示用；节点词表与 workflow_runtime._FLAT_NODES
断言对齐，DAG 拓扑/前置关系不再存在）。"""
from typing import Dict, Tuple


# 用户梳理的 6 个关键步骤（key_steps_confirm 档机械停判据）
DEFAULT_V2_REVIEW_NODES: Tuple[str, ...] = (
    "review_spec", "review_key_elements", "review_storyboard",
    "review_shot_media", "review_audio", "review_assembly",
)

# 平铺节点 → 人类可读标题（机械停卡文案 + 账本回放展示；无 DAG 语义）。
#
# 2026-09-21 批I（事故 4444/Q6①）：与 `registry.STAGE_LABELS` **同名的节点**一律
# 对齐到「英文 tag 直译」口径（关键元素/分镜/音频层/组装导出），避免同一个阶段
# 在两条展示链上各叫一个名字。`review_*` / `write_spec` / `ke_media` 等**没有
# 对应 Skill 章节字段**的平台节点保持原措辞（它们是平台动作，不是 Skill 阶段）。
NODE_TITLES: Dict[str, str] = {
    "analyze_script": "剧本分析",
    "write_spec": "制片规格撰写",
    "review_spec": "规格审核",
    "storyboard_key_elements": "关键元素",
    "storyboard_shots": "分镜",
    "storyboard_audio": "音频层",
    "review_key_elements": "关键元素审核",
    "review_storyboard": "故事板审核",
    "ke_media": "关键元素出图",
    "shot_media": "逐镜视频生成",
    "review_shot_media": "镜头视频审核",
    "audio_assets": "音频资产",
    "review_audio": "音频审核",
    "assembly": "组装导出",
    "review_assembly": "成片审核",
}


# 6 个关键步骤的人类可读标题（DEFAULT_V2_REVIEW_NODES 子集视图）
DEFAULT_V2_REVIEW_NODE_TITLES: Dict[str, str] = {
    k: NODE_TITLES[k] for k in DEFAULT_V2_REVIEW_NODES
}


__all__ = [
    "DEFAULT_V2_REVIEW_NODES", "DEFAULT_V2_REVIEW_NODE_TITLES", "NODE_TITLES",
]