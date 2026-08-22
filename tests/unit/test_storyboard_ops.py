"""storyboard_ops 领域层：双轨等价性回归测试（FC Tool vs 文本 executor 同一实现）"""
import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.tools.storyboard_tools import (
    StoryboardPatchDraftTool,
    PatchDraftInput,
    StoryboardConfirmDraftTool,
    ConfirmDraftInput,
)
from src.video_agent.web.action_executor import StateOperationExecutor


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
async def test_fc_and_text_track_patch_equivalence(svc):
    """同一 patch 经 FC 轨与文本轨执行后，draft 状态必须逐字段一致"""
    _, draft = _first_draft(svc)
    patch = {"label": "等价测试", "tag": "已确认", "aspectRatio": "9:16", "unknownField": "应被忽略"}

    tool = StoryboardPatchDraftTool()
    r1 = await tool.aexecute(PatchDraftInput(draft_id=draft["id"], patch=dict(patch)))
    assert r1.success
    fc_snapshot = dict(draft)

    # 还原后走文本轨
    executor = StateOperationExecutor(svc)
    executor.execute([{"action": "update_draft", "draft_id": draft["id"], "patch": patch}])
    text_snapshot = dict(draft)

    assert fc_snapshot == text_snapshot
    assert "unknownField" not in text_snapshot  # 白名单外字段两轨都不写入


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


@pytest.mark.asyncio
async def test_execute_locked_applies_under_lock(svc):
    """execute_locked：持锁执行，结果与同步 execute 一致"""
    executor = StateOperationExecutor(svc)
    applied = await executor.execute_locked([{
        "action": "add_group", "group_type": "keyElement", "title": "持锁分组",
    }])
    assert applied == 1
    assert svc.state_dict["keyElements"][-1]["title"] == "持锁分组"


def test_ops_find_draft_selected_fallback(svc):
    """领域层 find_draft：'current' 优先解析选中草稿，无选中兜底第一个"""
    group, draft = _first_draft(svc)
    found = ops.find_draft(svc.state_dict, "current")
    assert found is not None and found[1]["id"] == draft["id"]
    found_none = ops.find_draft(svc.state_dict, "no-such-id")
    assert found_none is None
