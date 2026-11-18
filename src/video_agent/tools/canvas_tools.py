"""
画布操作 Tool 集 — 通过 CanvasBackend 协议操作画布（Rule5: 统一注册）。

每个 Tool 继承 BaseTool，内部只调协议方法（不碰 httpx、不判后端类型）：
写操作经端口落地为增量 ops 直发（见 adapters/canvas_port.py 节点级写方法组）。
canvas_list_assets 读本地素材库（经 core/ports assets 端口）。
"""
import time
from typing import Any, Dict, List, Literal, Optional, Tuple, Type

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


class CanvasCreateContainerInput(StrictToolInput):
    """大类容器（原生组）：一个容器 = 一个类别，组内直接放 Skill 流程产出的节点。"""
    canvas_id: str = Field(..., description="画布 ID")
    title: str = Field(..., description="容器标题（类别名，如 关键元素/合成关键元素/分镜/音频）")
    note: str = Field("", description="常驻说明节点的正文（留空用标题兜底）")
    x: Optional[int] = Field(None, description="容器左上角 X（留空：自动排到已有容器右侧）")
    y: Optional[int] = Field(None, description="容器左上角 Y（留空：与已有容器同高）")


# 写类 Input 统一继承 StrictToolInput（extra="forbid"，批 4b 单一事实源）；
# 只读 Input 保持 BaseModel 原样，不扩大拒收面。

class CanvasAddNodeInput(StrictToolInput):
    canvas_id: str = Field(..., description="画布 ID")
    node_type: Literal["smart-image", "smart-prompt", "text", "image"] = Field("smart-image", description="节点类型（闭集枚举）: smart-image | smart-prompt | text | image")
    title: str = Field("", description="节点标题")
    x: Optional[int] = Field(None, description="节点 X 坐标（留空：容器内自动排布；无容器时 100）")
    y: Optional[int] = Field(None, description="节点 Y 坐标（留空：容器内自动排布；无容器时 100）")
    prompt: str = Field("", description="提示词（smart-prompt 类型用）")
    image_url: str = Field("", description="图片 URL（smart-image/image 类型用）")
    content: str = Field("", description="文本内容（text 类型用）")
    group_id: str = Field("", description="所属大类容器组 ID（留空 = 不归属任何容器）")
    width: int = Field(0, description="节点宽（0 = 用类型默认）")
    height: int = Field(0, description="节点高（0 = 用类型默认）")
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
                     prompt: str = "", image_url: str = "", content: str = "",
                     group_id: str = "", width: int = 0, height: int = 0,
                     container: bool = False) -> Dict[str, Any]:
    """构建画布节点字典（消除 AddNode/BatchUpdate 重复）"""
    node: Dict[str, Any] = {
        "id": node_id, "type": node_type,
        "title": title or node_type, "x": x, "y": y,
        "created_at": int(time.time() * 1000),
    }
    if width:
        node["width"] = width
    if height:
        node["height"] = height
    if group_id:
        node["group_id"] = group_id
    if container:
        node["container"] = True
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


# ---------- 大类容器布局（2026-11-11） ----------
# 容器 = 原生 group 节点 + 常驻说明节点；成员靠 metadata.groupId 归属。
# 这里只负责「放哪儿」；边界由后端 refit_container 按成员包围盒实时重算。

_CONTAINER_PAD = 24
_CONTAINER_TOP = 52
_CONTAINER_GAP = 120
_CONTAINER_CELL_W = 360
_CONTAINER_CELL_H = 300
_CONTAINER_COLS = 4


def _next_container_origin(state: Dict[str, Any]) -> Tuple[int, int]:
    """新容器放在已有容器右侧；没有容器时从 (100,100) 起。"""
    nodes = [n for n in ((state or {}).get("nodes") or []) if isinstance(n, dict)]
    containers = [
        n for n in nodes
        if n.get("type") == "group" and (n.get("metadata") or {}).get("container")
    ]
    if not containers:
        return 100, 100
    right = max(
        float((n.get("position") or {}).get("x") or 0) + float(n.get("width") or 0)
        for n in containers
    )
    top = min(float((n.get("position") or {}).get("y") or 0) for n in containers)
    return int(right + _CONTAINER_GAP), int(top)


def _next_slot_in_container(state: Dict[str, Any], group_id: str,
                            extra_index: int = 0) -> Tuple[int, int]:
    """容器内下一个网格槽位（说明节点占第 0 格，资产从第 1 格起）。"""
    nodes = [n for n in ((state or {}).get("nodes") or []) if isinstance(n, dict)]
    group = next((n for n in nodes if n.get("id") == group_id and n.get("type") == "group"), None)
    if group is None:
        return 100, 100
    pos = group.get("position") or {}
    members = [
        n for n in nodes
        if n.get("type") != "group"
        and str((n.get("metadata") or {}).get("groupId") or "") == group_id
    ]
    index = len(members) + max(0, int(extra_index))
    return (
        int(float(pos.get("x") or 0) + _CONTAINER_PAD
            + (index % _CONTAINER_COLS) * _CONTAINER_CELL_W),
        int(float(pos.get("y") or 0) + _CONTAINER_TOP
            + (index // _CONTAINER_COLS) * _CONTAINER_CELL_H),
    )


# ---------- Tool 实现 ----------

class CanvasListTool(BaseTool):
    name = "canvas_list"
    risk = "low"  # §2.7：只读
    parallel_safe = True  # 小步提速批 3：只读，可进有界并行池
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "列出所有画布（ID、标题、节点数），用于确认目标画布 ID。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasListInput

    def model_view(self, data: Dict[str, Any]) -> str:
        """模型可见渲染：画布 id/标题/节点数（后续写画布的唯一入口）。"""
        items = [c for c in ((data or {}).get("canvases") or []) if isinstance(c, dict)]
        if not items:
            return "画布列表为空（当前没有可用画布）"
        shown = items[:20]
        parts = [
            f"{c.get('id')}《{c.get('title') or '未命名'}》"
            f"{c.get('node_count', c.get('nodeCount', 0))} 节点"
            for c in shown
        ]
        suffix = f"；另有 {len(items) - len(shown)} 块未列出" if len(items) > len(shown) else ""
        return f"可用画布 {len(items)} 块：" + "；".join(parts) + suffix

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
    parallel_safe = True  # 小步提速批 3：只读，可进有界并行池
    detail_tier = "output"  # 读取类：仅输出留痕
    description = "读取指定画布的全部节点信息（ID、类型、标题、坐标、图片、提示词）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasReadNodesInput

    def model_view(self, data: Dict[str, Any]) -> str:
        """模型可见渲染：节点 id/类型/标题/坐标（打组与定位都要用 id）。"""
        data = data or {}
        nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
        canvas_id = str(data.get("canvas_id") or "")
        title = str(data.get("canvas_title") or "未命名")
        count = int(data.get("node_count", len(nodes)) or 0)
        head = f"画布 {canvas_id}《{title}》共 {count} 个节点"
        if not nodes:
            return head + "（空画布）"
        shown = nodes[:30]
        parts = [
            f"{n.get('id')}｜{n.get('type') or ''}｜{n.get('title') or ''}｜"
            f"({n.get('x', 0)},{n.get('y', 0)})"
            for n in shown
        ]
        suffix = f"；另有 {len(nodes) - len(shown)} 个未列出" if len(nodes) > len(shown) else ""
        return head + "：" + "；".join(parts) + suffix

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
            metadata = n.get("metadata") or {}
            content = str(metadata.get(INFINITE_CANVAS_IMAGE_MEDIA_FIELD) or "")
            group_id = str(metadata.get("groupId") or "")
            if group_id:
                item["group_id"] = group_id
            if metadata.get("container"):
                item["container"] = True
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
    risk = "medium"  # §2.7（2026-09-07 外部标杆对齐）：写状态但可撤销（画布节点可删除/撤销）
    detail_tier = "expand"  # 产出类
    description = (
        "在画布中新增一个节点（支持 smart-image/smart-prompt/text/image 类型）。"
        "新增图片节点时，若有参考图 URL 则填入 image_url。"
        "传入 group_id 即成为该大类容器的成员；此时 x/y 可留空，由系统在容器内自动排布，"
        "容器边界随内容自动收缩/扩展。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasAddNodeInput

    def model_view(self, data: Dict[str, Any]) -> str:
        data = data or {}
        tail = f"，已归入容器 {data['group_id']}" if data.get("group_id") else ""
        return (f"画布 {data.get('canvas_id') or ''} 已新增节点 "
                f"{data.get('node_id') or ''}{tail}")

    async def aexecute(self, params: CanvasAddNodeInput) -> ToolResult:
        adapter = get_canvas_adapter()
        x, y = params.x, params.y
        state: Optional[Dict[str, Any]] = None
        if params.group_id and (x is None or y is None):
            state = await adapter.get_canvas(params.canvas_id)
            ax, ay = _next_slot_in_container(state, params.group_id)
            x = ax if x is None else x
            y = ay if y is None else y
        node_id = _gen_node_id()
        new_node = _build_node_dict(
            node_id, params.node_type, params.title,
            100 if x is None else x, 100 if y is None else y,
            prompt=params.prompt, image_url=params.image_url, content=params.content,
            group_id=params.group_id, width=params.width, height=params.height,
        )
        result = await adapter.add_node(params.canvas_id, node=new_node)
        # 入组后按成员包围盒实时调整容器（位置 + 宽高）
        if params.group_id and params.node_type != "group":
            await adapter.refit_container(params.canvas_id, params.group_id)
        return ToolResult(success=True, data={
            "node_id": result.get("node_id") or node_id,
            "canvas_id": params.canvas_id,
            "group_id": params.group_id,
        })


class CanvasCreateContainerTool(BaseTool):
    """大类容器：一个类别一个原生组，组内直接放 Skill 流程产出的节点。"""

    name = "canvas_create_container"
    risk = "medium"  # 写状态但可撤销（删容器/解散组即可还原）
    detail_tier = "expand"  # 产出类
    description = (
        "创建一个画布大类容器（原生组，标题即类别名）。容器自动带一个常驻说明节点，"
        "因此不会是空组；组内节点用 group_id 归属，容器边界随内容自动收缩/扩展。"
        "四大类（关键元素/合成关键元素/分镜/音频）各建一个；容器内只放叶子节点"
        "（画布组为单层包裹）。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasCreateContainerInput

    def model_view(self, data: Dict[str, Any]) -> str:
        data = data or {}
        return (
            f"已创建容器《{data.get('title') or ''}》（组 id={data.get('group_id') or ''}，"
            f"位置 {data.get('x', 0)},{data.get('y', 0)}，"
            f"尺寸 {data.get('width', 0)}×{data.get('height', 0)}）"
        )

    async def aexecute(self, params: CanvasCreateContainerInput) -> ToolResult:
        adapter = get_canvas_adapter()
        state = await adapter.get_canvas(params.canvas_id)
        x, y = params.x, params.y
        if x is None or y is None:
            ax, ay = _next_container_origin(state)
            x = ax if x is None else x
            y = ay if y is None else y
        group_id = _gen_node_id()
        note_id = _gen_node_id()
        note_text = params.note.strip() or f"{params.title}（本区容器）"
        nodes = [
            _build_node_dict(
                group_id, "group", params.title, x, y,
                width=360, height=220, container=True),
            _build_node_dict(
                note_id, "text", "说明", x + _CONTAINER_PAD, y + _CONTAINER_TOP,
                content=note_text, group_id=group_id, width=320, height=120),
        ]
        await adapter.add_nodes_batch(params.canvas_id, nodes=nodes)
        fit = await adapter.refit_container(params.canvas_id, group_id) or {}
        data = {
            "canvas_id": params.canvas_id,
            "title": params.title,
            "group_id": group_id,
            "note_id": note_id,
            "x": fit.get("x", x),
            "y": fit.get("y", y),
            "width": fit.get("width", 0),
            "height": fit.get("height", 0),
            "members": fit.get("members", 1),
        }
        return ToolResult(success=True, data=data)


class CanvasUpdateNodeTool(BaseTool):
    name = "canvas_update_node"
    risk = "medium"  # §2.7（2026-09-07 外部标杆对齐）：写状态但可撤销（画布节点可删除/撤销）
    detail_tier = "expand"  # 产出类
    description = (
        "修改画布中指定节点的属性（标题/坐标/提示词/图片/文本内容）。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasUpdateNodeInput

    def model_view(self, data: Dict[str, Any]) -> str:
        data = data or {}
        return f"画布 {data.get('canvas_id') or ''} 节点 {data.get('node_id') or ''} 已更新"

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
        group_id = ""
        if params.x is not None or params.y is not None:
            try:
                state = await adapter.get_canvas(params.canvas_id)
                node = next(
                    (n for n in (state.get("nodes") or [])
                     if isinstance(n, dict) and n.get("id") == params.node_id),
                    None,
                )
                group_id = str(((node or {}).get("metadata") or {}).get("groupId") or "")
            except Exception:
                group_id = ""
        found = await adapter.update_node(
            params.canvas_id, node_id=params.node_id, patch=patch
        )

        if not found:
            # T5：画布节点不存在属画布侧定位失败，原参重试无效（换 node_id 才有意义）
            return ToolResult(
                success=False, error=f"节点 '{params.node_id}' 不存在",
                error_code="canvas", retryable=False,
            )
        if group_id:
            await adapter.refit_container(params.canvas_id, group_id)
        return ToolResult(success=True, data={
            "canvas_id": params.canvas_id, "node_id": params.node_id, "updated": True})


class CanvasDeleteNodeTool(BaseTool):
    name = "canvas_delete_node"
    risk = "medium"  # §2.7（2026-09-07 外部标杆对齐）：写状态但可撤销（节点可重建；撤销栈覆盖）
    detail_tier = "output"  # 删除类：仅输出留痕
    description = "删除画布中指定的节点"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasDeleteNodeInput

    def model_view(self, data: Dict[str, Any]) -> str:
        data = data or {}
        return f"画布 {data.get('canvas_id') or ''} 节点 {data.get('node_id') or ''} 已删除"

    async def aexecute(self, params: CanvasDeleteNodeInput) -> ToolResult:
        adapter = get_canvas_adapter()
        group_id = ""
        try:
            state = await adapter.get_canvas(params.canvas_id)
            node = next(
                (n for n in (state.get("nodes") or [])
                 if isinstance(n, dict) and n.get("id") == params.node_id),
                None,
            )
            group_id = str(((node or {}).get("metadata") or {}).get("groupId") or "")
        except Exception:
            group_id = ""
        found = await adapter.delete_node(params.canvas_id, node_id=params.node_id)

        if not found:
            # T5：画布节点不存在属画布侧定位失败，原参重试无效（换 node_id 才有意义）
            return ToolResult(
                success=False, error=f"节点 '{params.node_id}' 不存在",
                error_code="canvas", retryable=False,
            )
        # 删掉成员后按剩余成员收缩容器（含说明节点被删光 → refit 不动，交给空组回收）
        if group_id:
            await adapter.refit_container(params.canvas_id, group_id)
        return ToolResult(success=True, data={
            "canvas_id": params.canvas_id, "node_id": params.node_id, "deleted": True})


class CanvasListAssetsTool(BaseTool):
    name = "canvas_list_assets"
    risk = "low"  # §2.7：只读
    parallel_safe = True  # 小步提速批 3：只读，可进有界并行池
    detail_tier = "output"  # 读取类：仅输出留痕
    description = "列出本地素材库中的所有素材（图片/视频/音频）"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasListAssetsInput

    def model_view(self, data: Dict[str, Any]) -> str:
        """模型可见渲染：素材名/类型清单（图片节点引用要按名字选）。"""
        data = data or {}
        assets = data.get("assets") or {}
        items = [i for i in (assets.get("items") or []) if isinstance(i, dict)]
        total = int(assets.get("total", data.get("total", len(items))) or 0)
        if not items:
            return f"素材库共 {total} 项（当前页为空）"
        shown = items[:20]
        parts = [
            f"{i.get('name') or '未命名'}（{i.get('kind') or ''}）"
            for i in shown
        ]
        suffix = "；另有更多未列出" if data.get("has_more") or len(items) < total else ""
        return f"素材库共 {total} 项：" + "；".join(parts) + suffix

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
    x: Optional[int] = Field(None, description="X 坐标（留空：容器内自动排布）")
    y: Optional[int] = Field(None, description="Y 坐标（留空：容器内自动排布）")
    prompt: str = Field("", description="提示词")
    image_url: str = Field("", description="图片 URL")
    content: str = Field("", description="文本内容")
    group_id: str = Field("", description="所属大类容器组 ID")
    width: int = Field(0, description="节点宽（0 = 默认）")
    height: int = Field(0, description="节点高（0 = 默认）")


class CanvasBatchUpdateInput(StrictToolInput):
    canvas_id: str = Field(..., description="画布 ID")
    nodes: List[CanvasBatchNodeInput] = Field(..., description="要批量添加的节点数组")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class CanvasBatchUpdateTool(BaseTool):
    name = "canvas_batch_add_nodes"
    risk = "medium"  # §2.7（2026-09-07 外部标杆对齐）：写状态但可撤销（画布节点可删除/撤销）
    detail_tier = "expand"  # 产出类
    description = (
        "批量添加多个节点到画布（一次 HTTP 完成，避免多次读写）。"
        "节点带 group_id 即归入对应大类容器；x/y 可留空，由系统在容器内自动排布。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasBatchUpdateInput

    def model_view(self, data: Dict[str, Any]) -> str:
        """模型可见渲染：新增节点的 id 列表（紧接着的打组要按 id 传参）。"""
        data = data or {}
        node_ids = [str(n) for n in (data.get("node_ids") or []) if str(n)]
        groups = [str(g) for g in (data.get("group_ids") or []) if str(g)]
        tail = f"；已归入容器 {'、'.join(groups)}" if groups else ""
        return (f"画布 {data.get('canvas_id') or ''} 已新增 "
                f"{int(data.get('added_count', len(node_ids)) or 0)} 个节点："
                + "、".join(node_ids) + tail)

    async def aexecute(self, params: CanvasBatchUpdateInput) -> ToolResult:
        adapter = get_canvas_adapter()
        state: Optional[Dict[str, Any]] = None
        if any(n.group_id for n in params.nodes):
            state = await adapter.get_canvas(params.canvas_id)
        nodes: List[Dict[str, Any]] = []
        new_ids: List[str] = []
        slots: Dict[str, int] = {}
        for n in params.nodes:
            node_id = _gen_node_id()
            new_ids.append(node_id)
            x, y = n.x, n.y
            if n.group_id:
                if x is None or y is None:
                    ax, ay = _next_slot_in_container(
                        state or {}, n.group_id, slots.get(n.group_id, 0))
                    x = ax if x is None else x
                    y = ay if y is None else y
                slots[n.group_id] = slots.get(n.group_id, 0) + 1
            nodes.append(_build_node_dict(
                node_id, n.node_type, n.title,
                100 if x is None else x, 100 if y is None else y,
                prompt=n.prompt, image_url=n.image_url, content=n.content,
                group_id=n.group_id, width=n.width, height=n.height,
            ))
        # 一次批量提交（一次批量 ops）
        await adapter.add_nodes_batch(params.canvas_id, nodes=nodes)
        group_ids = sorted({n.group_id for n in params.nodes if n.group_id})
        for gid in group_ids:
            await adapter.refit_container(params.canvas_id, gid)
        return ToolResult(success=True, data={
            "canvas_id": params.canvas_id,
            "added_count": len(new_ids),
            "node_ids": new_ids,
            "group_ids": group_ids,
        })


class CanvasGroupNodesInput(StrictToolInput):
    canvas_id: str = Field(..., description="画布 ID")
    node_ids: List[str] = Field(
        ..., min_length=2, description="要打组的节点 ID（至少 2 个）")


class CanvasUngroupNodesInput(StrictToolInput):
    canvas_id: str = Field(..., description="画布 ID")
    node_ids: List[str] = Field(
        ..., min_length=1, description="组节点 ID 或组内成员 ID")


class CanvasGroupNodesTool(BaseTool):
    name = "canvas_group_nodes"
    risk = "medium"  # §2.7：写状态但可撤销（解散组即可还原）
    detail_tier = "expand"  # 产出类
    description = (
        "把画布上已存在的多个节点打成一个组框（至少 2 个节点，组可整体移动/整体引用）。"
        "只用于「把已有节点包起来」；大类容器用 canvas_create_container 创建"
        "（画布组为单层包裹，不能嵌套）。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasGroupNodesInput

    def model_view(self, data: Dict[str, Any]) -> str:
        data = data or {}
        return (f"画布 {data.get('canvas_id') or ''} 已把 "
                f"{int(data.get('grouped', 0) or 0)} 个节点打成 1 组")

    async def aexecute(self, params: CanvasGroupNodesInput) -> ToolResult:
        adapter = get_canvas_adapter()
        result = await adapter.group_nodes(params.canvas_id, node_ids=params.node_ids)
        return ToolResult(success=True, data=result)


class CanvasUngroupNodesTool(BaseTool):
    name = "canvas_ungroup_nodes"
    risk = "medium"  # §2.7：写状态但可撤销（重新打组即可还原）
    detail_tier = "output"  # 解散类：仅输出留痕
    description = "解散画布上的组（传组节点 ID 或组内成员 ID），移除组框并解除这些节点与组的归属。"

    def get_input_schema(self) -> Type[BaseModel]:
        return CanvasUngroupNodesInput

    def model_view(self, data: Dict[str, Any]) -> str:
        data = data or {}
        return (f"画布 {data.get('canvas_id') or ''} 已解散 "
                f"{int(data.get('ungrouped', 0) or 0)} 个节点所在的组")

    async def aexecute(self, params: CanvasUngroupNodesInput) -> ToolResult:
        adapter = get_canvas_adapter()
        result = await adapter.ungroup_nodes(params.canvas_id, node_ids=params.node_ids)
        return ToolResult(success=True, data=result)


# ---------- 注册函数 ----------

def register_canvas_tools():
    """注册所有画布 Tool 到 ToolManager（启动时调用）"""
    from src.video_agent.tools.manager import ToolManager

    ToolManager.register(CanvasListTool())
    ToolManager.register(CanvasReadNodesTool())
    ToolManager.register(CanvasAddNodeTool())
    ToolManager.register(CanvasCreateContainerTool())
    ToolManager.register(CanvasUpdateNodeTool())
    ToolManager.register(CanvasDeleteNodeTool())
    ToolManager.register(CanvasListAssetsTool())
    ToolManager.register(CanvasBatchUpdateTool())
    ToolManager.register(CanvasGroupNodesTool())
    ToolManager.register(CanvasUngroupNodesTool())
    logger.info("[CanvasTools] 已注册 10 个画布操作 Tool")
