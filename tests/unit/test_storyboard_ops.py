"""storyboard_ops 领域层：FC 工具与唯一实现同口径回归（Q2 裁决 2026-09-01：
文本轨随执行器家族退役，动作通道唯一 = FC）"""
import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.tools.storyboard_tools import (
    StoryboardPatchDraftTool,
    PatchDraftInput,
    StoryboardConfirmDraftTool,
    ConfirmDraftInput,
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _first_draft(svc):
    group = svc.state_dict["keyElements"][0]
    return group, group["drafts"][0]


@pytest.mark.asyncio
async def test_fc_patch_covers_image_resolution_and_gen_type(svc):
    """漂移回归：FC 轨 allowed 字段曾缺 imageResolution/genType，统一后必须可写"""
    _, draft = _first_draft(svc)
    tool = StoryboardPatchDraftTool()
    result = await tool.aexecute(PatchDraftInput(
        draft_id=draft["id"],
        patch={"imageResolution": "2K", "genType": "image", "prompt": "新提示词"},
    ))
    assert result.success
    assert draft["imageResolution"] == "2K"
    assert draft["genType"] == "image"
    assert draft["prompt"] == "新提示词"


@pytest.mark.asyncio
async def test_fc_patch_matches_ops_single_implementation(svc):
    """同一合法 patch：FC 工具落点与领域层唯一实现（ops.patch_draft）逐字段一致。"""
    _, draft = _first_draft(svc)
    patch = {"label": "等价测试", "tag": "已确认", "aspectRatio": "9:16"}

    tool = StoryboardPatchDraftTool()
    r1 = await tool.aexecute(PatchDraftInput(draft_id=draft["id"], patch=dict(patch)))
    assert r1.success
    fc_snapshot = dict(draft)

    # 另一草稿经唯一实现直写，同口径逐字段一致（标签已确认 → 重写同值不作废）
    peer = dict(draft)
    peer["label"], peer["tag"], peer["aspectRatio"] = "旧", "Agent", "16:9"
    ops.patch_draft(peer, dict(patch))
    assert fc_snapshot["label"] == peer["label"]
    assert fc_snapshot["tag"] == peer["tag"]
    assert fc_snapshot["aspectRatio"] == peer["aspectRatio"]


@pytest.mark.asyncio
async def test_unknown_field_fc_atomic_reject(svc):
    """批 4a 口径：白名单外字段——FC 轨原子拒收（报错不写入；
    Q2 裁决后文本轨容忍分支随执行器家族退役）。"""
    _, draft = _first_draft(svc)
    patch = {"label": "应拒收", "unknownField": "x"}

    tool = StoryboardPatchDraftTool()
    r1 = await tool.aexecute(PatchDraftInput(draft_id=draft["id"], patch=dict(patch)))
    assert r1.success is False
    assert r1.error_code == "validation" and r1.retryable is False
    assert "unknownField" in str(r1.error)
    assert draft.get("label") != "应拒收"  # 原子拒收：合法字段也不部分写入


@pytest.mark.asyncio
async def test_fc_patch_supports_index_ref(svc):
    """统一后 FC 轨也支持「1-2」编号定位（此前仅文本轨支持）"""
    group, _ = _first_draft(svc)
    tool = StoryboardPatchDraftTool()
    result = await tool.aexecute(PatchDraftInput(draft_id="1-1", patch={"tag": "编号命中"}))
    assert result.success
    assert group["drafts"][0]["tag"] == "编号命中"


@pytest.mark.asyncio
async def test_fc_confirm_uses_unified_patch(svc):
    _, draft = _first_draft(svc)
    tool = StoryboardConfirmDraftTool()
    result = await tool.aexecute(ConfirmDraftInput(draft_id=draft["id"]))
    assert result.success
    assert draft["tag"] == "已确认"


# test_execute_locked_applies_under_lock 已随 Q2 裁决 2026-09-01 退役删除：
# execute_locked/文本轨动作分派随执行器家族退役；并发契约归 svc.lock（FC 工具
# 与路由层持锁口径另有钉死）。


def test_ops_find_draft_selected_fallback(svc):
    """领域层 find_draft：'current' 优先解析选中草稿，无选中兜底第一个"""
    group, draft = _first_draft(svc)
    found = ops.find_draft(svc.state_dict, "current")
    assert found is not None and found[1]["id"] == draft["id"]
    found_none = ops.find_draft(svc.state_dict, "no-such-id")
    assert found_none is None
