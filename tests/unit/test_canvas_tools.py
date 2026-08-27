"""
Canvas Tools 单元测试 — mock CanvasAdapter。
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from types import SimpleNamespace

from src.video_agent.tools.canvas_tools import (
    CanvasListTool,
    CanvasReadNodesTool,
    CanvasAddNodeTool,
    CanvasUpdateNodeTool,
    CanvasDeleteNodeTool,
    CanvasListAssetsTool,
    CanvasListInput,
    CanvasReadNodesInput,
    CanvasAddNodeInput,
    CanvasUpdateNodeInput,
    CanvasDeleteNodeInput,
    CanvasListAssetsInput,
    register_canvas_tools,
)
from src.video_agent.tools.manager import ToolManager


@pytest.fixture(autouse=True)
def _reset_tools():
    ToolManager.reset()
    yield
    ToolManager.reset()


MOCK_CANVAS = {
    "id": "c1",
    "title": "测试画布",
    "icon": "🧩",
    "updated_at": 1000,
    "nodes": [
        {"id": "n1", "type": "smart-image", "title": "图片1", "x": 0, "y": 0, "images": [{"url": "/output/a.png"}]},
        {"id": "n2", "type": "smart-prompt", "title": "提示词", "x": 200, "y": 0, "prompt": "赛博朋克"},
    ],
    "connections": [{"from": "n2", "to": "n1"}],
    "viewport": {"x": 0, "y": 0, "scale": 1},
    "logs": [],
    "settings": {},
}


def _mock_adapter():
    adapter = MagicMock()
    adapter.list_canvases = AsyncMock(return_value=[
        {"id": "c1", "title": "测试画布", "node_count": 2},
    ])
    adapter.get_canvas = AsyncMock(return_value=dict(MOCK_CANVAS, nodes=list(MOCK_CANVAS["nodes"])))
    adapter.save_canvas = AsyncMock(return_value={"id": "c1", "updated_at": 1001})
    adapter.list_assets = AsyncMock(return_value={"items": [{"url": "/output/a.png"}]})
    return adapter


class TestCanvasListTool:
    @pytest.mark.asyncio
    async def test_list(self):
        tool = CanvasListTool()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=_mock_adapter()):
            result = await tool.aexecute(CanvasListInput())
        assert result.success
        assert result.data["count"] == 1
        assert result.data["canvases"][0]["id"] == "c1"


class TestCanvasReadNodesTool:
    @pytest.mark.asyncio
    async def test_read(self):
        tool = CanvasReadNodesTool()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=_mock_adapter()):
            result = await tool.aexecute(CanvasReadNodesInput(canvas_id="c1"))
        assert result.success
        assert result.data["node_count"] == 2
        assert result.data["nodes"][0]["id"] == "n1"

    @pytest.mark.asyncio
    async def test_prompt_truncated_over_budget(self):
        """T8：prompt 超阈值截断 + 截断标记（阈值走 config settings）"""
        tool = CanvasReadNodesTool()
        long_prompt = "赛博朋克" * 100  # 400 字符，配合下方阈值 10 模拟超限
        canvas = dict(MOCK_CANVAS, nodes=[
            {"id": "n2", "type": "smart-prompt", "title": "提示词", "x": 0, "y": 0, "prompt": long_prompt},
        ])
        adapter = _mock_adapter()
        adapter.get_canvas = AsyncMock(return_value=canvas)
        fake_settings = SimpleNamespace(canvas_read_prompt_max_chars=10, canvas_asset_page_size=50)
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=adapter), \
             patch("src.video_agent.tools.canvas_tools.settings", fake_settings):
            result = await tool.aexecute(CanvasReadNodesInput(canvas_id="c1"))
        node = result.data["nodes"][0]
        assert result.success
        assert node["prompt"] == long_prompt[:10]
        assert node["prompt_truncated"] is True

    @pytest.mark.asyncio
    async def test_prompt_within_budget_not_truncated(self):
        """未超阈值的 prompt 原样返回，无截断标记"""
        tool = CanvasReadNodesTool()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=_mock_adapter()):
            result = await tool.aexecute(CanvasReadNodesInput(canvas_id="c1"))
        node = result.data["nodes"][1]
        assert node["prompt"] == "赛博朋克"
        assert "prompt_truncated" not in node


class TestCanvasAddNodeTool:
    @pytest.mark.asyncio
    async def test_add_text_node(self):
        tool = CanvasAddNodeTool()
        mock = _mock_adapter()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=mock):
            result = await tool.aexecute(CanvasAddNodeInput(
                canvas_id="c1", node_type="text", title="测试文本", x=300, y=200, content="你好"
            ))
        assert result.success
        assert result.data["canvas_id"] == "c1"
        assert "node_id" in result.data
        # 验证 save_canvas 被调用
        mock.save_canvas.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_image_node(self):
        tool = CanvasAddNodeTool()
        mock = _mock_adapter()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=mock):
            result = await tool.aexecute(CanvasAddNodeInput(
                canvas_id="c1", node_type="smart-image", title="新图",
                image_url="/output/new.png", prompt="风景"
            ))
        assert result.success
        # 检查传入 save 的 nodes 包含新节点
        call_kwargs = mock.save_canvas.call_args
        saved_nodes = call_kwargs.kwargs.get("nodes") or call_kwargs[1].get("nodes", [])
        assert len(saved_nodes) == 3  # 原2 + 新1


class TestCanvasUpdateNodeTool:
    @pytest.mark.asyncio
    async def test_update_existing(self):
        tool = CanvasUpdateNodeTool()
        mock = _mock_adapter()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=mock):
            result = await tool.aexecute(CanvasUpdateNodeInput(
                canvas_id="c1", node_id="n1", title="新标题", x=500
            ))
        assert result.success
        assert result.data["updated"] is True

    @pytest.mark.asyncio
    async def test_update_nonexistent(self):
        tool = CanvasUpdateNodeTool()
        mock = _mock_adapter()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=mock):
            result = await tool.aexecute(CanvasUpdateNodeInput(
                canvas_id="c1", node_id="nonexist", title="x"
            ))
        assert not result.success
        assert "不存在" in result.error


class TestCanvasDeleteNodeTool:
    @pytest.mark.asyncio
    async def test_delete_existing(self):
        tool = CanvasDeleteNodeTool()
        mock = _mock_adapter()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=mock):
            result = await tool.aexecute(CanvasDeleteNodeInput(canvas_id="c1", node_id="n1"))
        assert result.success
        assert result.data["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        tool = CanvasDeleteNodeTool()
        mock = _mock_adapter()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=mock):
            result = await tool.aexecute(CanvasDeleteNodeInput(canvas_id="c1", node_id="ghost"))
        assert not result.success


class TestCanvasListAssetsTool:
    @pytest.mark.asyncio
    async def test_list_assets(self):
        tool = CanvasListAssetsTool()
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=_mock_adapter()):
            result = await tool.aexecute(CanvasListAssetsInput())
        assert result.success
        assert "assets" in result.data
        assert result.data["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_assets_paginated_has_more(self):
        """T8：超限返回截断页 + has_more=True（页大小走 config settings）"""
        tool = CanvasListAssetsTool()
        adapter = _mock_adapter()
        adapter.list_assets = AsyncMock(return_value={
            "items": [{"url": f"/output/{i}.png"} for i in range(5)],
        })
        fake_settings = SimpleNamespace(canvas_read_prompt_max_chars=2000, canvas_asset_page_size=2)
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=adapter), \
             patch("src.video_agent.tools.canvas_tools.settings", fake_settings):
            result = await tool.aexecute(CanvasListAssetsInput())
        assert result.success
        assert len(result.data["assets"]["items"]) == 2
        assert result.data["has_more"] is True
        assert result.data["count"] == 2
        assert result.data["total"] == 5

    @pytest.mark.asyncio
    async def test_list_assets_explicit_limit(self):
        """显式 limit 入参覆盖默认页大小"""
        tool = CanvasListAssetsTool()
        adapter = _mock_adapter()
        adapter.list_assets = AsyncMock(return_value={
            "items": [{"url": f"/output/{i}.png"} for i in range(5)],
        })
        with patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=adapter):
            result = await tool.aexecute(CanvasListAssetsInput(limit=3))
        assert result.success
        assert len(result.data["assets"]["items"]) == 3
        assert result.data["has_more"] is True


class TestRegistration:
    def test_register_canvas_tools(self):
        register_canvas_tools()
        schemas = ToolManager.get_all_tool_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert "canvas_list" in names
        assert "canvas_read_nodes" in names
        assert "canvas_add_node" in names
        assert "canvas_update_node" in names
        assert "canvas_delete_node" in names
        assert "canvas_list_assets" in names
