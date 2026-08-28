"""
画布操作 Tool 集 — 通过 CanvasBackend 协议操作画布（Rule5: 统一注册）。

每个 Tool 继承 BaseTool，内部只调协议方法（不碰 httpx、不判后端类型）：
写操作经端口落地为增量 ops 直发（见 adapters/canvas_port.py 节点级写方法组）。
canvas_list_assets 读本地素材库（经 core/ports assets 端口）。
"""
import time
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field
from loguru import logger

from src.video_agent.tools.base import BaseTool, StrictToolInput, ToolResult
from src.video_agent.adapters.canvas_adapter import get_canvas_adapter
from src.video_agent.adapters.canvas_schema import INFINITE_CANVAS_IMAGE_MEDIA_FIELD
from src.video_agent.config import settings
from src.video_agent.core.ports import assets_port
from src.video_agent.utils import gen_id


# ---------- Input Schemas ----------

class CanvasListInput(BaseModel):
    """无参数"""
    pass


class CanvasReadNodesInput(BaseModel):
    canvas_id: str = Field(..., description="画布 ID")


# 写类 Input 统一继承 StrictToolInput（extra="forbid"，批 4b 单一事实源）；
# 只读 Input 保持 BaseModel 原样，不扩大拒收面。

class CanvasAddNodeInput(StrictToolInput):
    canvas_id: str = Field(..., description="画布 ID")
    node_type: Literal["smart-image", "smart-prompt", "text", "image"] = Field("smart-image", description="节点类型（闭集枚举）: smart-image | smart-prompt | text | image")
    title: str = Field("", description="节点标题")
    x: int = Field(100, description="节点 X 坐标")
    y: int = Field(100, description="节点 Y 坐标")
    prompt: str = Field("", description="提示词（smart-prompt 类型用）")
    image_url: str = Field("", description="图片 URL（smart-image/image 类型用）")
    content: str = Field("", description="文本内容（text 类型用）")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class CanvasUpdateNodeInput(StrictToolInput):
    canvas_id: str = Field(..., description="画布 ID")
    node_id: str = Field(..., description="要修改的节点 ID")
    title: Optional[str] = Field(None, description="新标题")
    x: Optional[int] = Field(None, description="新 X 坐标")
    y: Optional[int] = Field(None, description="新 Y 坐标")
    prompt: Optional[str] = Field(None, description="新提示词")
    image_url: Optional[str] = Field(None, description="新图片 URL")
    content: Optional[str] = Field(None, description="新文本内容")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class CanvasDeleteNodeInput(StrictToolInput):
    canvas_id: str = Field(..., description="画布 ID")
    node_id: str = Field(..., description="要删除的节点 ID")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class CanvasListAssetsInput(BaseModel):
    limit: int = Field(0, description="返回条数上限（0 = 用默认页大小）")


# ---------- 辅助函数 ----------

def _gen_node_id() -> str:
    """生成唯一节点 ID"""
    return gen_id("agent", wide=True)


def _build_node_dict(node_id: str, node_type: str, title: str, x: int, y: int,
                     prompt: str = "", image_url: str = "", content: str = "") -> Dict[str, Any]:
    """构建画布节点字典（消除 AddNode/BatchUpdate 重复）"""
    node: Dict[str, Any] = {
        "id": node_id, "type": node_type,
        "title": title or node_type, "x": x, "y": y,
        "created_at": int(time.time() * 1000),
    }
    if node_type in ("smart-image", "image"):
        images = [{"url": image_url, "name": title or "image"}] if image_url else []
        node["images"] = images
        if prompt:
            node["prompt"] = prompt
    elif node_type == "smart-prompt":
        node["prompt"] = prompt or content
        node["images"] = []
    elif node_type == "text":
        node["content"] = content or title
    return node


# ---------- Tool 实现 ----------

class CanvasListTool(BaseTool):
    name = "canvas_list"
    risk = "low"  # §2.7：只读
    detail_tier = "output"  # 读取类：仅输出留痕
    description = "列出所有画布（ID、标题、节点数）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasListInput

    async def aexecute(self, params: CanvasListInput) -> ToolResult:
        adapter = get_canvas_adapter()
        canvases = await adapter.list_canvases()
        # canvas_list_projects 实际返回 camelCase（nodeCount）；snake_case 兜底防御形状漂移
        summary = [
            {"id": c.get("id"), "title": c.get("title"),
             "node_count": c.get("nodeCount", c.get("node_count", 0))}
            for c in canvases
        ]
        return ToolResult(success=True, data={"canvases": summary, "count": len(summary)})


class CanvasReadNodesTool(BaseTool):
    name = "canvas_read_nodes"
    risk = "low"  # §2.7：只读
    detail_tier = "output"  # 读取类：仅输出留痕
    description = "读取指定画布的全部节点信息（ID、类型、标题、坐标、图片、提示词）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasReadNodesInput

    async def aexecute(self, params: CanvasReadNodesInput) -> ToolResult:
        adapter = get_canvas_adapter()
        canvas = await adapter.get_canvas(params.canvas_id)
        nodes = canvas.get("nodes", [])
        # get_canvas 透传 canvas_get_state 原始形状：{id, type, title, position:{x,y},
        # metadata}，正文/图片 URL 统一在 metadata.content（与 routes/canvas.py
        # _node_image_refs、generation_dispatch _read_infinite_canvas_generated_url 同口径）
        summary = []
        for n in nodes:
            pos = n.get("position") or {}
            item = {
                "id": n.get("id"),
                "type": n.get("type", ""),
                "title": n.get("title", ""),
                "x": pos.get("x", 0),
                "y": pos.get("y", 0),
            }
            content = str((n.get("metadata") or {}).get(INFINITE_CANVAS_IMAGE_MEDIA_FIELD) or "")
            if str(n.get("type") or "") == "image":
                if content:
                    item["images_count"] = 1
                    item["first_image"] = content
            elif content:
                item["content"] = content[:200]
            summary.append(item)
        return ToolResult(success=True, data={
            "canvas_id": params.canvas_id,
            "canvas_title": canvas.get("title", ""),
            "nodes": summary,
            "node_count": len(summary),
        })


class CanvasAddNodeTool(BaseTool):
    name = "canvas_add_node"
    risk = "high"  # §2.7：画布写入（外部副作用），需用户确认
    detail_tier = "expand"  # 产出类
    description = "在画布中新增一个节点（支持 smart-image/smart-prompt/text/image 类型）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasAddNodeInput

    async def aexecute(self, params: CanvasAddNodeInput) -> ToolResult:
        node_id = _gen_node_id()
        new_node = _build_node_dict(
            node_id, params.node_type, params.title, params.x, params.y,
            prompt=params.prompt, image_url=params.image_url, content=params.content,
        )
        adapter = get_canvas_adapter()
        result = await adapter.add_node(params.canvas_id, node=new_node)
        return ToolResult(success=True, data={
            "node_id": result.get("node_id") or node_id,
            "canvas_id": params.canvas_id,
        })


class CanvasUpdateNodeTool(BaseTool):
    name = "canvas_update_node"
    risk = "high"  # §2.7：画布写入（外部副作用），需用户确认
    detail_tier = "expand"  # 产出类
    description = "修改画布中指定节点的属性（标题/坐标/提示词/图片/文本内容）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasUpdateNodeInput

    async def aexecute(self, params: CanvasUpdateNodeInput) -> ToolResult:
        patch: Dict[str, Any] = {
            "title": params.title,
            "x": params.x,
            "y": params.y,
            "prompt": params.prompt,
            "image_url": params.image_url,
            "content": params.content,
        }
        adapter = get_canvas_adapter()
        found = await adapter.update_node(
            params.canvas_id, node_id=params.node_id, patch=patch
        )

        if not found:
            # T5：画布节点不存在属画布侧定位失败，原参重试无效（换 node_id 才有意义）
            return ToolResult(
                success=False, error=f"节点 '{params.node_id}' 不存在",
                error_code="canvas", retryable=False,
            )
        return ToolResult(success=True, data={"node_id": params.node_id, "updated": True})


class CanvasDeleteNodeTool(BaseTool):
    name = "canvas_delete_node"
    risk = "high"  # §2.7：画布写入（外部副作用），需用户确认
    detail_tier = "output"  # 删除类：仅输出留痕
    description = "删除画布中指定的节点"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasDeleteNodeInput

    async def aexecute(self, params: CanvasDeleteNodeInput) -> ToolResult:
        adapter = get_canvas_adapter()
        found = await adapter.delete_node(params.canvas_id, node_id=params.node_id)

        if not found:
            # T5：画布节点不存在属画布侧定位失败，原参重试无效（换 node_id 才有意义）
            return ToolResult(
                success=False, error=f"节点 '{params.node_id}' 不存在",
                error_code="canvas", retryable=False,
            )
        return ToolResult(success=True, data={"node_id": params.node_id, "deleted": True})


class CanvasListAssetsTool(BaseTool):
    name = "canvas_list_assets"
    risk = "low"  # §2.7：只读
    detail_tier = "output"  # 读取类：仅输出留痕
    description = "列出本地素材库中的所有素材（图片/视频/音频）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasListAssetsInput

    async def aexecute(self, params: CanvasListAssetsInput) -> ToolResult:
        # 素材库事实源在本地（workspace/assets/ + data/asset_library.json），
        # 经 core/ports assets 端口复用 assets_library 扫描，不经画布后端。
        items = assets_port().iter_items("", "")
        total = len(items)
        page = params.limit if params.limit and params.limit > 0 else settings.canvas_asset_page_size
        if total > page:
            return ToolResult(success=True, data={
                "assets": {"items": items[:page], "total": total},
                "has_more": True, "count": page, "total": total,
            })
        return ToolResult(success=True, data={
            "assets": {"items": items, "total": total}, "has_more": False,
        })


class CanvasBatchNodeInput(StrictToolInput):
    # 嵌套子项同属写类路径：纳入后嵌套层未知字段也被 Pydantic 拒
    node_type: Literal["smart-image", "smart-prompt", "text", "image"] = Field("smart-image", description="节点类型（闭集枚举）: smart-image | smart-prompt | text | image")
    title: str = Field("", description="节点标题")
    x: int = Field(100, description="X 坐标")
    y: int = Field(100, description="Y 坐标")
    prompt: str = Field("", description="提示词")
    image_url: str = Field("", description="图片 URL")
    content: str = Field("", description="文本内容")


class CanvasBatchUpdateInput(StrictToolInput):
    canvas_id: str = Field(..., description="画布 ID")
    nodes: List[CanvasBatchNodeInput] = Field(..., description="要批量添加的节点数组")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class CanvasBatchUpdateTool(BaseTool):
    name = "canvas_batch_add_nodes"
    risk = "high"  # §2.7：画布写入（外部副作用），需用户确认
    detail_tier = "expand"  # 产出类
    description = "批量添加多个节点到画布（一次 HTTP 完成，避免多次读写）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasBatchUpdateInput

    async def aexecute(self, params: CanvasBatchUpdateInput) -> ToolResult:
        nodes: List[Dict[str, Any]] = []
        new_ids: List[str] = []
        for n in params.nodes:
            node_id = _gen_node_id()
            new_ids.append(node_id)
            nodes.append(_build_node_dict(
                node_id, n.node_type, n.title, n.x, n.y,
                prompt=n.prompt, image_url=n.image_url, content=n.content,
            ))
        adapter = get_canvas_adapter()
        # 一次批量提交（一次批量 ops）
        await adapter.add_nodes_batch(params.canvas_id, nodes=nodes)
        return ToolResult(success=True, data={
            "canvas_id": params.canvas_id,
            "added_count": len(new_ids),
            "node_ids": new_ids,
        })


# ---------- 注册函数 ----------

def register_canvas_tools():
    """注册所有画布 Tool 到 ToolManager（启动时调用）"""
    from src.video_agent.tools.manager import ToolManager

    ToolManager.register(CanvasListTool())
    ToolManager.register(CanvasReadNodesTool())
    ToolManager.register(CanvasAddNodeTool())
    ToolManager.register(CanvasUpdateNodeTool())
    ToolManager.register(CanvasDeleteNodeTool())
    ToolManager.register(CanvasListAssetsTool())
    ToolManager.register(CanvasBatchUpdateTool())
    logger.info("[CanvasTools] 已注册 7 个画布操作 Tool")
