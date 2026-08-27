"""
Storyboard Tools 单元测试 — 闭集枚举进 Schema（批 2 T3）。

聚焦 CreateGroupInput.group_type 闭集拒收轴：闭集外值经
ToolManager.invoke_tool 返回 success=False 且 error_code=="validation"
（校验轴由批 3 在 tools/manager.py 铺好，此处为生产端落点）。
"""
import pytest
from pydantic import ValidationError

from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.storyboard_tools import (
    CreateGroupInput,
    MediaToChatInput,
    StoryboardMediaToChatTool,
    register_storyboard_tools,
)


@pytest.fixture(autouse=True)
def _reset_tools():
    ToolManager.reset()
    register_storyboard_tools()
    yield
    ToolManager.reset()


class TestCreateGroupTypeEnumClosedSet:
    """group_type 闭集枚举：keyElement | shot | audio，集外值拒收"""

    async def test_invalid_group_type_rejected_via_invoke(self):
        result = await ToolManager.invoke_tool(
            "storyboard_create_group", {"group_type": "bogus", "title": "测试分组"}
        )
        assert result.success is False
        assert result.error_code == "validation"
        assert result.retryable is False

    def test_invalid_group_type_schema_rejected(self):
        with pytest.raises(ValidationError):
            CreateGroupInput.model_validate({"group_type": "scene", "title": "x"})

    def test_valid_group_types_accepted(self):
        for gt in ("keyElement", "shot", "audio"):
            params = CreateGroupInput.model_validate({"group_type": gt, "title": "x"})
            assert params.group_type == gt


class TestMediaToChatTargetValidation:
    """storyboard_media_to_chat 的 target 结构化校验（对齐同族 view_storyboard_media）：
    draft_ids/target 均未命中合法取值 → error_code=validation 结构化报错（附合法取值），
    不再误报成「没有找到带媒体的目标草稿」（如传 current 等不支持值）。"""

    @pytest.fixture
    def svc(self, tmp_path):
        StateManager.reset_instance()
        instance = StateManager(str(tmp_path))
        StateManager._instance = instance
        yield instance
        StateManager.reset_instance()

    @pytest.mark.parametrize("target", ["current", "bogus", ""])
    async def test_invalid_target_structured_validation_error(self, svc, target):
        tool = StoryboardMediaToChatTool()
        result = await tool.aexecute(MediaToChatInput(target=target))
        assert result.success is False
        assert result.error_code == "validation"
        assert result.retryable is False
        # 报错附合法取值清单，与描述口径一致（不含 current）
        for valid in ("all", "all_keyElements", "all_shots", "all_audio"):
            assert valid in result.error
        assert "没有找到带媒体的目标草稿" not in str(result.error)

    async def test_valid_target_not_blocked_by_validation(self, svc):
        """合法 target 不进校验报错分支（空故事板回落既有「没找到」语义）。"""
        tool = StoryboardMediaToChatTool()
        result = await tool.aexecute(MediaToChatInput(target="all"))
        assert result.success is False
        assert result.error_code != "validation"
