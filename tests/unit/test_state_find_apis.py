# -*- coding: utf-8 -*-
"""D1 状态写入收拢钉死测试：分组/草稿查找唯一入口。

收拢口径：调用方不再各自三层循环抄写（web/routes/storyboard.py、
web/task_manager.py、tools/storyboard_tools.py 已改经本入口）；
返回引用即状态事实源，修改经引用生效，落盘归调用方。
"""
import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    s = StateManager(str(tmp_path / "ws"))
    s.state_dict[CAT_KEY_ELEMENTS] = [{
        "id": "g1", "title": "角色",
        "drafts": [{"id": "d1", "prompt": "甲"}, {"id": "d2", "prompt": "乙"}],
    }]
    s.state_dict[CAT_SHOTS] = [{
        "id": "g2", "title": "分镜",
        "drafts": [{"id": "d3", "prompt": "丙"}],
    }]
    yield s
    StateManager.reset_instance()


def test_find_group_hit_and_miss(svc):
    cat, group = svc.find_group("g2")
    assert cat == CAT_SHOTS and group["title"] == "分镜"
    assert svc.find_group("不存在") is None
    assert svc.find_group("") is None


def test_find_draft_hit_returns_same_reference(svc):
    cat, group, draft = svc.find_draft("d3")
    assert cat == CAT_SHOTS and group["id"] == "g2"
    # 返回引用即事实源：修改经引用直接生效（无副本）
    draft["prompt"] = "改后"
    assert svc.state_dict[CAT_SHOTS][0]["drafts"][0]["prompt"] == "改后"


def test_find_draft_miss(svc):
    assert svc.find_draft("不存在") is None
    assert svc.find_draft("") is None
    assert svc.find_draft(None) is None


def test_find_draft_all_categories(svc):
    """三类别统一遍历：任意类别的草稿均可命中。"""
    assert svc.find_draft("d1")[0] == CAT_KEY_ELEMENTS
    assert svc.find_draft("d2")[1]["id"] == "g1"
    assert svc.find_draft("d3")[0] == CAT_SHOTS
