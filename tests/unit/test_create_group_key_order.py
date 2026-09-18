# -*- coding: utf-8 -*-
"""批 E（2026-09-18）：storyboard_create_group 的 desc/summary 键序写闸回归钉。

只查 shot 组原始入参 JSON 的字段顺序（desc 先于 summary），不看内容、
不碰格式红线。倒序 → ValidationError → 整单拒收重填（retryable=False）。
键序来源：model_validator(mode="before") 收到 json.loads 保序 dict。
"""
import pytest
from pydantic import ValidationError

from src.video_agent.tools.storyboard_tools import CreateGroupInput


def test_desc_before_summary_passes():
    """正序（desc 先于 summary）→ 校验通过。"""
    m = CreateGroupInput.model_validate({
        "group_type": "shot", "title": "镜头A",
        "desc": "完整镜头设计……", "summary": "含3个内切镜头（约18s）",
    })
    assert m.group_type == "shot"
    assert m.desc and m.summary


def test_summary_before_desc_rejected():
    """倒序（summary 先于 desc）→ ValidationError（整单拒收，含明确拒因）。"""
    with pytest.raises(ValidationError) as ei:
        CreateGroupInput.model_validate({
            "group_type": "shot", "title": "镜头A",
            "summary": "含3个内切镜头（约18s）", "desc": "完整镜头设计……",
        })
    assert "desc 必须先于 summary" in str(ei.value)


def test_non_shot_group_no_order_check():
    """非 shot 组（keyElement）即使 summary 在 desc 前也不拦（只 shot 组验键序）。"""
    m = CreateGroupInput.model_validate({
        "group_type": "keyElement", "title": "角色A",
        "summary": "x", "desc": "y",
    })
    assert m.group_type == "keyElement"


def test_shot_missing_summary_key_no_order_error():
    """shot 组缺 summary 键 → 不触发键序校验（缺 summary 由工具层 aexecute 另有写闸）。"""
    m = CreateGroupInput.model_validate({
        "group_type": "shot", "title": "镜头A", "desc": "完整镜头设计……",
    })
    assert m.desc
    assert m.summary == ""  # 默认空（aexecute 会因 summary 空整单拒收，非本 validator 职责）
