"""
Storyboard Tools 单元测试 — 闭集枚举进 Schema（批 2 T3）。

聚焦 CreateGroupInput.group_type 闭集拒收轴：闭集外值经
ToolManager.invoke_tool 返回 success=False 且 error_code=="validation"
（校验轴由批 3 在 tools/manager.py 铺好，此处为生产端落点）。
"""
import pytest
from pydantic import ValidationError

from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.storyboard_tools import (
    CreateGroupInput,
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
