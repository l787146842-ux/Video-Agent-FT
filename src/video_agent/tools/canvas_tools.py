"""
画布操作 Tool 集 — 通过 CanvasAdapter 操作画布画布（Rule5: 统一注册）。

每个 Tool 继承 BaseTool，内部只调 CanvasAdapter（不碰 httpx）。
写操作遵循：读取最新画布 → 修改 nodes → save_canvas 写回。
"""
import time
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field
from loguru import logger

from src.video_agent.tools.base import BaseTool, StrictToolInput, ToolResult
from src.video_agent.adapters.canvas_adapter import get_canvas_adapter
from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError
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


async def _load_and_save(canvas_id: str, mutate_fn, max_retries: int = 3):
    """
    通用画布读写流程（带 409 冲突自动重试）：
    1. 读取最新画布
    2. 执行 mutate_fn(canvas) 修改
    3. 写回画布（带乐观锁）
    4. 若 409 冲突，重新读取 + 重新应用（最多 max_retries 次）
    返回 (修改后的画布, mutate_fn 的返回值)
    """
    adapter = get_canvas_adapter()

    for attempt in range(1, max_retries + 1):
        canvas = await adapter.get_canvas(canvas_id)
        result = mutate_fn(canvas)
        try:
            await adapter.save_canvas(
                canvas_id,
                title=canvas.get("title", "未命名画布"),
                icon=canvas.get("icon", "🧩"),
                nodes=canvas.get("nodes", []),
                connections=canvas.get("connections", []),
                viewport=canvas.get("viewport", {}),
                logs=canvas.get("logs", []),
                settings_dict=canvas.get("settings", {}),
                base_updated_at=int(canvas.get("updated_at") or 0),
            )
            return canvas, result
        except AdapterError as e:
            if e.status_code == 409 and attempt < max_retries:
                logger.warning(f"[CanvasTools] 画布写入冲突，第 {attempt} 次重试: {canvas_id}")
                continue
            raise

    # 不应到达此处，但作为安全兆底
    raise AdapterError(f"画布写入失败：超过 {max_retries} 次重试仍冲突")


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
        summary = [
            {"id": c.get("id"), "title": c.get("title"), "node_count": c.get("node_count", 0)}
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
        summary = []
        for n in nodes:
            item = {
                "id": n.get("id"),
                "type": n.get("type", "smart-image"),
                "title": n.get("title", ""),
                "x": n.get("x", 0),
                "y": n.get("y", 0),
            }
            if n.get("prompt"):
                raw = n["prompt"]
                cap = settings.canvas_read_prompt_max_chars
                if len(raw) > cap:
                    item["prompt"] = raw[:cap]
                    item["prompt_truncated"] = True
                else:
                    item["prompt"] = raw
            if n.get("images"):
                item["images_count"] = len(n["images"])
                item["first_image"] = n["images"][0].get("url", "") if n["images"] else ""
            if n.get("content"):
                item["content"] = n["content"][:200]
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

        def mutate(canvas):
            canvas.setdefault("nodes", []).append(new_node)
            return node_id

        _, result_id = await _load_and_save(params.canvas_id, mutate)
        return ToolResult(success=True, data={"node_id": result_id, "canvas_id": params.canvas_id})


class CanvasUpdateNodeTool(BaseTool):
    name = "canvas_update_node"
    risk = "high"  # §2.7：画布写入（外部副作用），需用户确认
    detail_tier = "expand"  # 产出类
    description = "修改画布中指定节点的属性（标题/坐标/提示词/图片/文本内容）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasUpdateNodeInput

    async def aexecute(self, params: CanvasUpdateNodeInput) -> ToolResult:
        found = False

        def mutate(canvas):
            nonlocal found
            for node in canvas.get("nodes", []):
                if node.get("id") == params.node_id:
                    found = True
                    if params.title is not None:
                        node["title"] = params.title
                    if params.x is not None:
                        node["x"] = params.x
                    if params.y is not None:
                        node["y"] = params.y
                    if params.prompt is not None:
                        node["prompt"] = params.prompt
                    if params.content is not None:
                        node["content"] = params.content
                    if params.image_url is not None:
                        node["images"] = [{"url": params.image_url, "name": node.get("title", "image")}]
                    return True
            return False

        _, _ = await _load_and_save(params.canvas_id, mutate)

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
        found = False

        def mutate(canvas):
            nonlocal found
            nodes = canvas.get("nodes", [])
            new_nodes = [n for n in nodes if n.get("id") != params.node_id]
            if len(new_nodes) < len(nodes):
                found = True
            canvas["nodes"] = new_nodes
            # 同时清理相关连线
            canvas["connections"] = [
                c for c in canvas.get("connections", [])
                if c.get("from") != params.node_id and c.get("to") != params.node_id
            ]
            return found

        _, _ = await _load_and_save(params.canvas_id, mutate)

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
    description = "列出画布素材库中的所有素材（图片/工作流等）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasListAssetsInput

    async def aexecute(self, params: CanvasListAssetsInput) -> ToolResult:
        adapter = get_canvas_adapter()
        assets = await adapter.list_assets()
        page = params.limit if params.limit and params.limit > 0 else settings.canvas_asset_page_size
        if isinstance(assets, dict) and isinstance(assets.get("items"), list):
            items = assets["items"]
            if len(items) > page:
                paged = dict(assets, items=items[:page])
                return ToolResult(success=True, data={
                    "assets": paged, "has_more": True,
                    "count": page, "total": len(items),
                })
        return ToolResult(success=True, data={"assets": assets, "has_more": False})


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
        new_ids: List[str] = []

        def mutate(canvas):
            nodes_list = canvas.setdefault("nodes", [])
            for n in params.nodes:
                node_id = _gen_node_id()
                new_ids.append(node_id)
                node = _build_node_dict(
                    node_id, n.node_type, n.title, n.x, n.y,
                    prompt=n.prompt, image_url=n.image_url, content=n.content,
                )
                nodes_list.append(node)
            return len(new_ids)

        _, count = await _load_and_save(params.canvas_id, mutate)
        return ToolResult(success=True, data={
            "canvas_id": params.canvas_id,
            "added_count": count,
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
