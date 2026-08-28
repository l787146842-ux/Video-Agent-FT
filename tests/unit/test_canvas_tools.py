"""
Canvas Tools 单元测试 — 打桩点在 CanvasBackend 协议层。

工具层不判后端类型，只依赖协议方法；协议桩同形状，
后端实现差异由 test_canvas_drop.py / test_infinite_canvas_backend.py 覆盖。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from src.video_agent.tools.canvas_tools import (
    CanvasListTool,
    CanvasReadNodesTool,
    CanvasAddNodeTool,
    CanvasUpdateNodeTool,
    CanvasDeleteNodeTool,
    CanvasListAssetsTool,
    CanvasBatchUpdateTool,
    CanvasListInput,
    CanvasReadNodesInput,
    CanvasAddNodeInput,
    CanvasUpdateNodeInput,
    CanvasDeleteNodeInput,
    CanvasListAssetsInput,
    CanvasBatchUpdateInput,
    register_canvas_tools,
)
from src.video_agent.tools.manager import ToolManager


@pytest.fixture(autouse=True)
def _reset_tools():
    ToolManager.reset()
    yield
    ToolManager.reset()


MOCK_CANVAS = {
    # canvas_get_state 透传原始形状（夹具 tests/fixtures/infinite_canvas/tools/
    # canvas_get_state.json 口径）：节点 {id, type, title, position:{x,y}, metadata}，
    # 正文/图片 URL 统一在 metadata.content
    "projectId": "c1",
    "title": "测试画布",
    "nodes": [
        {"id": "n1", "type": "image", "title": "图片1",
         "position": {"x": 10, "y": 20}, "width": 320, "height": 320,
         "metadata": {"content": "http://a/output/a.png"}},
        {"id": "n2", "type": "text", "title": "提示词",
         "position": {"x": 200, "y": 0}, "metadata": {"content": "赛博朋克"}},
    ],
    "connections": [],
    "selectedNodeIds": [],
    "viewport": {"x": 0, "y": 0, "k": 1},
}


def _mock_backend() -> MagicMock:
    """CanvasBackend 协议桩"""
    backend = MagicMock(name="CanvasBackend")
    # canvas_list_projects 夹具口径：camelCase nodeCount
    backend.list_canvases = AsyncMock(return_value=[
        {"id": "c1", "title": "测试画布", "nodeCount": 2},
    ])
    backend.get_canvas = AsyncMock(return_value=dict(MOCK_CANVAS, nodes=list(MOCK_CANVAS["nodes"])))

    async def _add_node(canvas_id, *, node):
        return {"node_id": node.get("id"), "canvas_id": canvas_id}

    async def _update_node(canvas_id, *, node_id, patch):
        return any(n.get("id") == node_id for n in MOCK_CANVAS["nodes"])

    async def _delete_node(canvas_id, *, node_id):
        return any(n.get("id") == node_id for n in MOCK_CANVAS["nodes"])

    async def _add_nodes_batch(canvas_id, *, nodes):
        return [str(n.get("id") or "") for n in nodes]

    backend.add_node = AsyncMock(side_effect=_add_node)
    backend.update_node = AsyncMock(side_effect=_update_node)
    backend.delete_node = AsyncMock(side_effect=_delete_node)
    backend.add_nodes_batch = AsyncMock(side_effect=_add_nodes_batch)
    return backend


@pytest.fixture
def backend():
    """CanvasBackend 协议桩（单后端口径）"""
    return _mock_backend()


def _patch_adapter(backend):
    return patch("src.video_agent.tools.canvas_tools.get_canvas_adapter", return_value=backend)


class TestCanvasListTool:
    @pytest.mark.asyncio
    async def test_list(self, backend):
        tool = CanvasListTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasListInput())
        assert result.success
        assert result.data["count"] == 1
        assert result.data["canvases"][0]["id"] == "c1"
        assert result.data["canvases"][0]["node_count"] == 2  # 读 camelCase nodeCount


class TestCanvasReadNodesTool:
    @pytest.mark.asyncio
    async def test_read_raw_shape(self, backend):
        """原始形状读取：坐标取 position.x/y，图片节点输出首图与计数"""
        tool = CanvasReadNodesTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasReadNodesInput(canvas_id="c1"))
        assert result.success
        assert result.data["node_count"] == 2
        img, txt = result.data["nodes"]
        assert img["id"] == "n1" and img["type"] == "image"
        assert (img["x"], img["y"]) == (10, 20)  # 坐标不再恒 0（旧熊布顶层 x/y 已退役）
        assert img["images_count"] == 1
        assert img["first_image"] == "http://a/output/a.png"
        assert txt["content"] == "赛博朋克"  # 文本正文读 metadata.content，不再丢失
        assert "first_image" not in txt

    @pytest.mark.asyncio
    async def test_text_content_truncated_200(self, backend):
        """文本节点正文截断 200 字符（保持旧口径）"""
        tool = CanvasReadNodesTool()
        long_text = "赛博朋克" * 100  # 400 字符
        canvas = dict(MOCK_CANVAS, nodes=[
            {"id": "n2", "type": "text", "title": "提示词",
             "position": {"x": 0, "y": 0}, "metadata": {"content": long_text}},
        ])
        backend.get_canvas = AsyncMock(return_value=canvas)
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasReadNodesInput(canvas_id="c1"))
        node = result.data["nodes"][0]
        assert result.success
        assert node["content"] == long_text[:200]
        assert len(node["content"]) == 200

    @pytest.mark.asyncio
    async def test_empty_image_node_no_image_fields(self, backend):
        """空 image 节点（无 metadata.content）不输出图片字段"""
        tool = CanvasReadNodesTool()
        canvas = dict(MOCK_CANVAS, nodes=[
            {"id": "n3", "type": "image", "title": "空图",
             "position": {"x": 5, "y": 6}, "metadata": {}},
        ])
        backend.get_canvas = AsyncMock(return_value=canvas)
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasReadNodesInput(canvas_id="c1"))
        node = result.data["nodes"][0]
        assert "images_count" not in node and "first_image" not in node
        assert (node["x"], node["y"]) == (5, 6)


class TestCanvasAddNodeTool:
    @pytest.mark.asyncio
    async def test_add_text_node(self, backend):
        tool = CanvasAddNodeTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasAddNodeInput(
                canvas_id="c1", node_type="text", title="测试文本", x=300, y=200, content="你好"
            ))
        assert result.success
        assert result.data["canvas_id"] == "c1"
        assert "node_id" in result.data
        # 写走协议 add_node（增量/整板差异在后端实现内吸收，不影响工具层断言）
        backend.add_node.assert_called_once()
        _, kwargs = backend.add_node.call_args
        node = kwargs["node"]
        assert node["type"] == "text"
        assert node["content"] == "你好"
        assert node["id"] == result.data["node_id"]

    @pytest.mark.asyncio
    async def test_add_image_node(self, backend):
        tool = CanvasAddNodeTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasAddNodeInput(
                canvas_id="c1", node_type="smart-image", title="新图",
                image_url="/output/new.png", prompt="风景"
            ))
        assert result.success
        _, kwargs = backend.add_node.call_args
        node = kwargs["node"]
        assert node["type"] == "smart-image"
        assert node["images"] == [{"url": "/output/new.png", "name": "新图"}]
        assert node["prompt"] == "风景"


class TestCanvasUpdateNodeTool:
    @pytest.mark.asyncio
    async def test_update_existing(self, backend):
        tool = CanvasUpdateNodeTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasUpdateNodeInput(
                canvas_id="c1", node_id="n1", title="新标题", x=500
            ))
        assert result.success
        assert result.data["updated"] is True
        _, kwargs = backend.update_node.call_args
        assert kwargs["node_id"] == "n1"
        assert kwargs["patch"]["title"] == "新标题"
        assert kwargs["patch"]["x"] == 500
        assert kwargs["patch"]["content"] is None  # 未传字段保持 None 不生效

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, backend):
        tool = CanvasUpdateNodeTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasUpdateNodeInput(
                canvas_id="c1", node_id="nonexist", title="x"
            ))
        assert not result.success
        assert "不存在" in result.error


class TestCanvasDeleteNodeTool:
    @pytest.mark.asyncio
    async def test_delete_existing(self, backend):
        tool = CanvasDeleteNodeTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasDeleteNodeInput(canvas_id="c1", node_id="n1"))
        assert result.success
        assert result.data["deleted"] is True
        backend.delete_node.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, backend):
        tool = CanvasDeleteNodeTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasDeleteNodeInput(canvas_id="c1", node_id="ghost"))
        assert not result.success


class TestCanvasBatchAddNodesTool:
    @pytest.mark.asyncio
    async def test_batch_single_protocol_call(self, backend):
        """批量添加：一次协议调用提交全部节点（网格坐标由调用方预计算）"""
        tool = CanvasBatchUpdateTool()
        with _patch_adapter(backend):
            result = await tool.aexecute(CanvasBatchUpdateInput(
                canvas_id="c1",
                nodes=[
                    {"node_type": "smart-image", "title": f"图{i}", "x": 100 + (i % 4) * 400,
                     "y": 100 + (i // 4) * 300, "image_url": f"/output/{i}.png"}
                    for i in range(5)
                ],
            ))
        assert result.success
        assert result.data["added_count"] == 5
        assert len(result.data["node_ids"]) == 5
        backend.add_nodes_batch.assert_called_once()
        _, kwargs = backend.add_nodes_batch.call_args
        nodes = kwargs["nodes"]
        assert len(nodes) == 5
        # 网格布局预计算口径（沿用 routes/canvas.py push-timeline 算法）
        assert nodes[4]["x"] == 100 + (4 % 4) * 400
        assert nodes[4]["y"] == 100 + (4 // 4) * 300
        assert [n["id"] for n in nodes] == result.data["node_ids"]


def _mock_assets_port(items):
    port = MagicMock()
    port.iter_items = MagicMock(return_value=items)
    return port


class TestCanvasListAssetsTool:
    """canvas_list_assets 读本地素材库（经 assets 端口，与画布后端无关）"""

    @pytest.mark.asyncio
    async def test_list_assets(self, backend):
        tool = CanvasListAssetsTool()
        port = _mock_assets_port([{"id": "a.png", "url": "/workspace/assets/a.png"}])
        with _patch_adapter(backend), \
             patch("src.video_agent.tools.canvas_tools.assets_port", return_value=port):
            result = await tool.aexecute(CanvasListAssetsInput())
        assert result.success
        assert "assets" in result.data
        assert result.data["has_more"] is False
        assert len(result.data["assets"]["items"]) == 1

    @pytest.mark.asyncio
    async def test_list_assets_paginated_has_more(self, backend):
        """T8：超限返回截断页 + has_more=True（页大小走 config settings）"""
        tool = CanvasListAssetsTool()
        port = _mock_assets_port([{"id": f"{i}.png"} for i in range(5)])
        fake_settings = SimpleNamespace(canvas_asset_page_size=2)
        with _patch_adapter(backend), \
             patch("src.video_agent.tools.canvas_tools.assets_port", return_value=port), \
             patch("src.video_agent.tools.canvas_tools.settings", fake_settings):
            result = await tool.aexecute(CanvasListAssetsInput())
        assert result.success
        assert len(result.data["assets"]["items"]) == 2
        assert result.data["has_more"] is True
        assert result.data["count"] == 2
        assert result.data["total"] == 5

    @pytest.mark.asyncio
    async def test_list_assets_explicit_limit(self, backend):
        """显式 limit 入参覆盖默认页大小"""
        tool = CanvasListAssetsTool()
        port = _mock_assets_port([{"id": f"{i}.png"} for i in range(5)])
        with _patch_adapter(backend), \
             patch("src.video_agent.tools.canvas_tools.assets_port", return_value=port):
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


class TestNodeTypeEnumClosedSet:
    """批 2 T3：node_type 闭集枚举，集外值经 invoke_tool 拒收 validation"""

    def setup_method(self):
        register_canvas_tools()

    async def test_add_node_invalid_node_type_rejected(self):
        result = await ToolManager.invoke_tool(
            "canvas_add_node", {"canvas_id": "c1", "node_type": "video"}
        )
        assert result.success is False
        assert result.error_code == "validation"
        assert result.retryable is False

    async def test_batch_node_invalid_node_type_rejected(self):
        result = await ToolManager.invoke_tool(
            "canvas_batch_add_nodes",
            {"canvas_id": "c1", "nodes": [{"node_type": "video"}]},
        )
        assert result.success is False
        assert result.error_code == "validation"
        assert result.retryable is False

    def test_valid_node_types_accepted(self):
        for nt in ("smart-image", "smart-prompt", "text", "image"):
            params = CanvasAddNodeInput.model_validate({"canvas_id": "c1", "node_type": nt})
            assert params.node_type == nt
