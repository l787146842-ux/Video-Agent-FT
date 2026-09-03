# -*- coding: utf-8 -*-
"""第 5 批（Q6 裁决 2026-09-01）上下文治理：状态指针化三档 + 分阶段注入 + read_state_group。

钉死语义：
- A 档（默认/小状态）：全量注入，零行为变化；
- B 档（超 state_context_budget_chars）：组级正文截断 + compacted 客观标志位，句柄保留
 （P3 载体改造：截断引导语不再嵌状态 JSON 的 note 字段，改由 prompt_builder
  状态尾部按标志位从 shared/degradation.md::STATE_COMPACTED 独立成段注入）；
- 预算 0 = 永远 A 档（回滚开关）；
- 分阶段注入：非焦点类别降为组级摘要（stageNote 指针），未知/空阶段不裁剪；
- 同状态两次构建字节一致（前缀纪律）；
- read_state_group：返回组全文（剥离草稿 prompt 换 prompt_chars），未找到结构化报错。
"""
import json

import pytest

from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.state.context_builder import build_agent_context
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS
from src.video_agent.tools.storyboard_tools import (
    ReadStateGroupInput,
    StoryboardReadStateGroupTool,
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _seed_big_state(svc, groups=20, desc_len=1500):
    """造一个超默认预算（20000 字符）的状态：20 个分镜组 × 长描述。"""
    svc.state_dict[CAT_KEY_ELEMENTS] = [{
        "id": "ke1", "title": "主角", "desc": "角" * desc_len,
        "drafts": [{"id": "kd1", "prompt": "提示词", "label": "卡1"}],
    }]
    svc.state_dict[CAT_SHOTS] = [
        {
            "id": f"sh{i}", "title": f"分镜{i}", "roughDesc": "镜" * desc_len,
            "sceneRefs": ["主角"], "duration": "5s", "shotType": "中景",
            "drafts": [{"id": f"sd{i}", "prompt": "x" * 100, "label": f"卡{i}"}],
        }
        for i in range(groups)
    ]
    svc.state_dict[CAT_AUDIO_ITEMS] = []


def test_a_tier_small_state_full(svc):
    """小状态 = A 档全量：desc 原样、无截断 note。"""
    svc.state_dict[CAT_KEY_ELEMENTS] = [{
        "id": "ke1", "title": "主角", "desc": "赛博朋克侦探，黑色风衣",
        "drafts": [{"id": "kd1", "prompt": "p", "label": "卡1"}],
    }]
    parsed = json.loads(build_agent_context(svc.state_dict, "bound"))
    assert parsed[CAT_KEY_ELEMENTS][0]["desc"] == "赛博朋克侦探，黑色风衣"
    assert "note" not in parsed
    assert "stageNote" not in parsed


def test_b_tier_over_budget_truncates_with_pointer(svc):
    """超预算 = B 档：正文截断 + compacted 客观标志位，句柄（id/编号/标题）保留。"""
    _seed_big_state(svc)
    parsed = json.loads(build_agent_context(svc.state_dict, "bound"))
    shot = parsed[CAT_SHOTS][0]
    assert shot["roughDesc"].endswith("…")
    assert len(shot["roughDesc"]) <= settings.state_group_body_chars + 1
    # P3 状态即数据：数据体只留客观标志位，引导 prose 不嵌 note 字段
    assert parsed["compacted"] is True
    assert "note" not in parsed
    # 句柄保留
    assert shot["id"] == "sh0" and shot["index"] == 1 and shot["title"] == "分镜0"
    # 体积确实小于 A 档
    full_len = len(json.dumps(
        {k: v for k, v in json.loads(
            build_agent_context(svc.state_dict, "bound", degraded=False)).items()},
        ensure_ascii=False))
    object.__setattr__(settings, "state_context_budget_chars", 0)
    try:
        a_parsed = json.loads(build_agent_context(svc.state_dict, "bound"))
        assert "compacted" not in a_parsed
        assert len(json.dumps(a_parsed, ensure_ascii=False)) > full_len
    finally:
        object.__setattr__(settings, "state_context_budget_chars", 20000)


def test_budget_zero_always_a(svc):
    """预算 0 = 永远 A 档（回滚开关）。"""
    _seed_big_state(svc)
    object.__setattr__(settings, "state_context_budget_chars", 0)
    try:
        parsed = json.loads(build_agent_context(svc.state_dict, "bound"))
        assert "compacted" not in parsed
        assert not parsed[CAT_SHOTS][0]["roughDesc"].endswith("…")
    finally:
        object.__setattr__(settings, "state_context_budget_chars", 20000)


def test_stage_profile_trims_non_focus(svc):
    """ke_media 阶段：shots/audio 降组级摘要，keyElements 全量（预算关隔离 B 档）。"""
    _seed_big_state(svc)
    object.__setattr__(settings, "state_context_budget_chars", 0)
    try:
        parsed = json.loads(build_agent_context(svc.state_dict, "bound", stage="ke_media"))
        shot = parsed[CAT_SHOTS][0]
        assert "drafts" not in shot and "roughDesc" not in shot
        assert shot["draft_count"] == 1 and shot["title"] == "分镜0"
        assert "stageNote" in parsed
        # 焦点类别全量
        assert parsed[CAT_KEY_ELEMENTS][0]["desc"] == "角" * 1500
    finally:
        object.__setattr__(settings, "state_context_budget_chars", 20000)


def test_stage_unknown_no_trim(svc):
    """未知/空阶段不裁剪（保守全量）。"""
    _seed_big_state(svc)
    object.__setattr__(settings, "state_context_budget_chars", 0)
    try:
        for stage in ("", "no_such_stage"):
            parsed = json.loads(build_agent_context(svc.state_dict, "bound", stage=stage))
            assert "stageNote" not in parsed
            assert "drafts" in parsed[CAT_SHOTS][0]
    finally:
        object.__setattr__(settings, "state_context_budget_chars", 20000)


def test_no_timestamp_in_model_view(svc):
    """前缀纪律：documents 的 updated_at 不进模型可见面（P2-1 钉死）。"""
    svc.state_dict["documents"] = [{
        "name": "Spec.md", "content": "硬核科幻", "updated_at": "2026-09-01T00:00:00Z",
    }]
    parsed = json.loads(build_agent_context(svc.state_dict, "bound"))
    assert "updated_at" not in json.dumps(parsed["documents"], ensure_ascii=False)
    assert parsed["documents"][0]["name"] == "Spec.md"


def test_build_deterministic(svc):
    """同状态两次构建字节一致（前缀纪律：无时间戳进模型可见面）。"""
    _seed_big_state(svc)
    a = build_agent_context(svc.state_dict, "bound", stage="shot_media")
    b = build_agent_context(svc.state_dict, "bound", stage="shot_media")
    assert a == b


@pytest.mark.asyncio
async def test_read_state_group_full_and_prompt_stripped(svc):
    """read_state_group 返回组全文：desc 完整、草稿 prompt 剥离换 prompt_chars。"""
    _seed_big_state(svc)
    tool = StoryboardReadStateGroupTool()
    res = await tool.aexecute(ReadStateGroupInput(category="shot", group_id="1"))
    assert res.success
    data = json.loads(res.data["content"])
    assert data["roughDesc"] == "镜" * 1500
    assert data["drafts"][0]["prompt_chars"] == 100
    assert "prompt" not in data["drafts"][0]


@pytest.mark.asyncio
async def test_read_state_group_listing_and_missing(svc):
    """空 group_id 返回目录；未找到结构化报错带可用清单。"""
    _seed_big_state(svc)
    tool = StoryboardReadStateGroupTool()
    res = await tool.aexecute(ReadStateGroupInput(category="shot", group_id=""))
    assert res.success
    listing = json.loads(res.data["content"])
    assert len(listing) == 20 and listing[0]["index"] == 1

    miss = await tool.aexecute(ReadStateGroupInput(category="shot", group_id="99"))
    assert not miss.success
    assert "分镜0" in miss.error
