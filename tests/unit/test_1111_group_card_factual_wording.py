# -*- coding: utf-8 -*-
"""2026-10-22 建组/建卡文案事实化批（1111 复测取证，用户裁决两轮收紧）— 回归钉。

现场：1111（proj-1792573140）故事板设计子代理给 23 个分镜组各建一张空壳
「分镜视频」卡。Skill 故事板章节对「要不要建卡」零要求，模型是被工具文案
引导的：`create_group.draft` 参数旧句「建组同时在该组内建一张卡（可选）」
是邀请式表述，配合「分镜视频卡 mediaType=video」hint 与「cards are needed
for generation」自行推理 ⇒ 23 张壳卡。

用户裁决（2026-10-22，两轮）：
① 「就修改正面，改为事实。建组（列表）是建组。建卡是建卡。不补『故事板
   设计阶段不带卡』这类的描述。」
② 「不要把建卡与建组是两个独立动作放进去。就说建组的事就行了。不要带建卡」
⇒ 建组工具描述只说建组、完全不提卡；draft 参数只说自己建卡、不提建组；
  不放「两个独立动作」之类关系句。阶段归属归闸机（card_media_gate）文案。
"""
from src.video_agent.tools.storyboard_tools import (
    CreateGroupInput, StoryboardCreateGroupTool, _DRAFT_FIELDS_HINT,
)


def test_create_group_tool_description_only_speaks_of_groups():
    """class 级描述只说建组的事：零提卡、零关系句。"""
    desc = StoryboardCreateGroupTool.description
    assert "创建新的故事板分组" in desc
    # 不提卡（建卡是 draft 参数自己的事）
    assert "草稿" not in desc and "建卡" not in desc, \
        "建组描述带出了建卡（用户裁决：就说建组的事）"
    # 不放关系句
    assert "两个独立动作" not in desc
    # 邀请式旧句不得回归
    assert "可附带草稿" not in desc


def test_create_group_draft_param_only_speaks_of_card():
    """draft 参数描述只说自己建卡：零提建组、零关系句、邀请式旧句不得回归。"""
    desc = CreateGroupInput.model_fields["draft"].description or ""
    assert "在该组内建一张草稿卡" in desc
    # 不提建组、不放关系句
    assert "建组" not in desc.split(_DRAFT_FIELDS_HINT)[0], \
        "draft 参数开头句带出了建组（用户裁决：建卡是建卡）"
    assert "两个独立动作" not in desc
    # 邀请式旧句不得回归
    assert "建组同时在该组内建一张卡" not in desc
    # 本参数自身的开头句（hint 之前）不得出现阶段归属表述
    # （阶段归闸机文案；hint 内的音频「两步落账」句是既有已裁决契约，不在此限）
    head = desc.split(_DRAFT_FIELDS_HINT)[0]
    assert "故事板设计" not in head, (
        "参数开头句复述阶段归属（用户裁决不补『故事板设计阶段不带卡』类描述）")
