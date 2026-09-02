"""
画布交互路由 — 对话栏生成的图片拖放进画布、画布图片回读、选中态读取。

背景：本项目与画布跨域（iframe 嵌入），浏览器原生 HTML5 拖拽事件
不会投递进跨域 iframe（实证：同源 iframe 可投递，跨域完全不投递），
因此前端在拖拽时显示自有放置层捕获落点，再调本接口经 CanvasBackend
协议写入图片节点（Rule 4: 只走 Adapter；Rule 7: 不改画布）。
路由层不判后端类型，响应契约前端零感知。
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel, Field

from src.video_agent.adapters.canvas_adapter import get_canvas_adapter
from src.video_agent.adapters.canvas_schema import INFINITE_CANVAS_IMAGE_MEDIA_FIELD
from src.video_agent.config import settings
from src.video_agent.state.models import CAT_SHOTS
from src.video_agent.exceptions import AdapterError
from src.video_agent.utils.paths import ASSETS_DIR

router = APIRouter()

_ASSETS_URL_PREFIX = "/workspace/assets/"

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class DropPoint(BaseModel):
    x: float
    y: float


class ViewSize(BaseModel):
    width: float
    height: float


class CanvasDropImageRequest(BaseModel):
    url: str = Field(..., description="图片 URL（/workspace/assets/... 或绝对 URL）")
    name: str = Field("", description="文件名")
    canvas_id: str = Field("", description="目标画布 ID（空则自动推断最近活跃画布）")
    drop: Optional[DropPoint] = Field(None, description="落点相对画布 iframe 的屏幕坐标")
    view: Optional[ViewSize] = Field(None, description="画布 iframe 可视尺寸")


# ---------- 响应模型（契约 phase1） ----------

class CanvasDropImageResponse(BaseModel):
    """拖放图片入画布响应"""
    node_id: str
    canvas_id: str
    canvas_title: str
    image_url: str


class CanvasNodeImageItem(BaseModel):
    """画布节点图片条目（@ 菜单用）"""
    id: str
    name: str
    url: str
    thumb: str
    category: str


class CanvasNodeImagesResponse(BaseModel):
    """当前活跃画布节点图片响应"""
    items: List[CanvasNodeImageItem]
    canvas_online: bool
    canvas_title: str = ""


class AllCanvasImageItem(BaseModel):
    """所有画布节点图片条目（含画布归属信息）"""
    id: str
    name: str
    url: str
    thumb: str
    canvas_title: str
    canvas_kind: str


class AllCanvasImagesResponse(BaseModel):
    """指定画布节点图片响应"""
    items: List[AllCanvasImageItem]
    canvas_online: bool
    canvas_title: str = ""
    canvas_kind: str = ""


class CanvasListItem(BaseModel):
    """画布列表条目"""
    id: str
    title: str
    kind: str
    updated_at: int


class CanvasListResponse(BaseModel):
    """画布列表响应"""
    canvases: List[CanvasListItem]
    canvas_online: bool


class CanvasSelectNodesResponse(BaseModel):
    """反向联动选中节点响应"""
    supported: bool
    selected: int


def _local_asset_path(url: str) -> Optional[Path]:
    """把 /workspace/assets/xxx 形式的 URL 映射到本地素材文件（防目录穿越）。"""
    path = urlparse(url).path if "://" in url else url
    if not path.startswith(_ASSETS_URL_PREFIX):
        return None
    fname = path[len(_ASSETS_URL_PREFIX):].strip("/")
    if not fname:
        return None
    try:
        full = (ASSETS_DIR / fname).resolve()
        full.relative_to(ASSETS_DIR.resolve())
    except (ValueError, OSError):
        return None
    return full if full.exists() else None


def _node_image_refs(node: Dict[str, Any]) -> List[Tuple[str, str]]:
    """提取节点内图片引用 (url, name)：infinite-canvas image 节点读 metadata.content；
    防御性兜底读 node.url/src/data.url。"""
    refs: List[Tuple[str, str]] = []
    meta = node.get("metadata")
    if isinstance(meta, dict) and str(node.get("type") or "") == "image":
        url = str(meta.get(INFINITE_CANVAS_IMAGE_MEDIA_FIELD) or "").strip()
        if url:
            refs.append((url, str(node.get("title") or "")))
            return refs
    direct_url = node.get("url") or node.get("src") or ""
    if not direct_url and isinstance(node.get("data"), dict):
        direct_url = node["data"].get("url") or node["data"].get("src") or ""
    if direct_url:
        refs.append((str(direct_url), str(node.get("name") or node.get("title") or "")))
    return refs


def _absolutize_canvas_url(url: str) -> str:
    """相对地址补全为画布站点绝对地址（防御性兜底；写入时已绝对化）。
    兜底基址用画布站点（settings.infinite_canvas_url）：adapter.base_url
    现为 canvas-agent，无静态服务。"""
    if url.startswith(("http://", "https://", "data:", "blob:")):
        return url
    base = (settings.infinite_canvas_url or "").rstrip("/")
    return f"{base}{url if url.startswith('/') else '/' + url}"


def _parse_updated_at(value: Any) -> int:
    """updatedAt 兼容数值毫秒与 ISO 字符串（夹具/契约口径为 ISO 时间戳）"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            return int(raw)
        except ValueError:
            try:
                return int(datetime.fromisoformat(raw).timestamp() * 1000)
            except ValueError:
                return 0
    return 0


@router.get("/canvas/node-images", response_model=CanvasNodeImagesResponse)
async def list_canvas_node_images():
    """返回当前活跃智能画布中所有节点内的图片（供 @ 菜单使用）。

    只读操作，不修改画布任何内容（Rule 7）。
    画布离线或无智能画布时返回空列表 + canvas_online 标志。
    """
    adapter = get_canvas_adapter()
    try:
        online = await adapter.is_online()
    except Exception:
        online = False
    if not online:
        return {"items": [], "canvas_online": False}

    try:
        target = await adapter.find_active_smart_canvas()
    except AdapterError:
        return {"items": [], "canvas_online": True}
    if not target:
        return {"items": [], "canvas_online": True}

    try:
        canvas = await adapter.get_canvas(target["id"])
    except AdapterError:
        return {"items": [], "canvas_online": True}

    items = []
    seen_urls: set = set()
    for node in canvas.get("nodes") or []:
        for ref_url, ref_name in _node_image_refs(node):
            url = ref_url.strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            url = _absolutize_canvas_url(url)
            items.append({
                "id": f"node-{node.get('id', '')}-{len(items)}",
                "name": ref_name or f"image-{len(items) + 1}",
                "url": url,
                "thumb": url,
                "category": "画布节点",
            })
    return {"items": items, "canvas_online": True, "canvas_title": canvas.get("title", "")}


@router.get("/canvas/list", response_model=CanvasListResponse)
async def list_canvases_for_picker():
    """返回所有未删除画布列表（供前端手动画布选择器使用）。"""
    adapter = get_canvas_adapter()
    try:
        online = await adapter.is_online()
    except Exception:
        online = False
    if not online:
        return {"canvases": [], "canvas_online": False}
    try:
        canvases = await adapter.list_canvases()
    except AdapterError:
        return {"canvases": [], "canvas_online": True}
    result = [
        {
            "id": c.get("id", ""),
            "title": c.get("title", "未命名画布"),
            "kind": str(c.get("kind") or "normal").strip().lower(),
            "updated_at": _parse_updated_at(c.get("updatedAt", c.get("updated_at"))),
        }
        for c in canvases
        if not c.get("deleted_at")
    ]
    # 按更新时间降序
    result.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"canvases": result, "canvas_online": True}


@router.get("/canvas/all-node-images", response_model=AllCanvasImagesResponse)
async def list_all_canvas_node_images(canvas_id: str = ""):
    """返回指定画布（或当前活跃画布）中节点内的图片。

    canvas_id 参数：指定画布 ID（手动画布选择器）；空则自动推断最近活跃画布。
    供中间预览框右键"导入画布内的图片"弹窗使用（只读，Rule 7）。
    """
    adapter = get_canvas_adapter()
    try:
        online = await adapter.is_online()
    except Exception:
        online = False
    if not online:
        return {"items": [], "canvas_online": False}

    # 定位目标画布：优先用前端指定的 canvas_id，否则推断最近活跃画布
    target = None
    if canvas_id:
        try:
            target = {"id": canvas_id}
            # 获取画布元信息（title/kind）
            canvases = await adapter.list_canvases()
            meta = next((c for c in canvases if c.get("id") == canvas_id), None)
            if meta:
                target = meta
        except AdapterError as _e:
            logger.debug("[canvas] 忽略异常: {}", _e)
    if not target:
        try:
            target = await adapter.find_active_canvas()
        except AdapterError:
            return {"items": [], "canvas_online": True}
    if not target:
        return {"items": [], "canvas_online": True}

    cv_id = target.get("id", "")
    cv_title = target.get("title", "未命名画布")
    cv_kind = str(target.get("kind") or "normal").strip().lower()

    try:
        canvas = await adapter.get_canvas(cv_id)
    except AdapterError:
        return {"items": [], "canvas_online": True}

    items = []
    seen_urls: set = set()

    def _add_url(url: str, name: str):
        url = url.strip()
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        url = _absolutize_canvas_url(url)
        items.append({
            "id": f"{cv_id}-{len(items)}",
            "name": name or f"image-{len(items) + 1}",
            "url": url,
            "thumb": url,
            "canvas_title": cv_title,
            "canvas_kind": cv_kind,
        })

    for node in canvas.get("nodes") or []:
        for ref_url, ref_name in _node_image_refs(node):
            _add_url(ref_url, ref_name)

    return {"items": items, "canvas_online": True, "canvas_title": cv_title, "canvas_kind": cv_kind}


@router.post("/canvas/drop-image", response_model=CanvasDropImageResponse)
async def drop_image_to_canvas(body: CanvasDropImageRequest, request: Request):
    """把一张图片写入指定画布（或当前活跃画布），创建图片节点。

    图片引用物化经协议 prepare_drop_image 落地：无二次上传，
    节点直接引用素材绝对 URL。"""
    adapter = get_canvas_adapter()

    name = body.name or Path(urlparse(body.url).path).name or "image.png"

    # 1) 物化图片引用（后端差异在协议实现内吸收）
    local = _local_asset_path(body.url)
    mime = _MIME_BY_SUFFIX.get(local.suffix.lower(), "image/png") if local else "image/png"
    prepared = await adapter.prepare_drop_image(
        url=body.url, name=name, local_path=local, mime=mime,
        public_base=str(request.base_url),
    )
    image_url = str(prepared.get("url") or "")
    name = str(prepared.get("name") or name)

    # 2) 定位目标画布：优先用前端指定的 canvas_id
    target = None
    if body.canvas_id:
        try:
            canvases = await adapter.list_canvases()
            target = next((c for c in canvases if c.get("id") == body.canvas_id and not c.get("deleted_at")), None)
        except AdapterError as _e:
            logger.debug("[canvas] 忽略异常: {}", _e)
    if not target:
        target = await adapter.find_active_canvas()
    if not target:
        raise AdapterError(
            "未找到可用的画布，请先在画布中创建一个画布",
            status_code=404,
            error_code="CANVAS_NOT_FOUND",
        )

    # 3) 根据画布类型创建对应节点格式
    canvas_kind = str(target.get("kind") or "normal").strip().lower()
    drop_point: Optional[Tuple[float, float]] = (body.drop.x, body.drop.y) if body.drop else None
    view_size: Optional[Tuple[float, float]] = (body.view.width, body.view.height) if body.view else None
    result = await adapter.add_image_node(
        target["id"],
        image={"url": image_url, "name": name, "kind": "image"},
        drop_point=drop_point,
        view_size=view_size,
        canvas_kind=canvas_kind,
    )
    return {**result, "image_url": image_url}


@router.get("/canvas/selection")
async def get_canvas_selection():
    """读取当前画布选中节点（转发适配器选中态读取）。

    响应契约：{"supported": bool, "nodes": [...], "canvas_online": bool}。
    经 canvas_get_selection 读取；离线/读取失败不抛错，回空选中。"""
    adapter = get_canvas_adapter()
    try:
        online = await adapter.is_online()
    except Exception:
        online = False
    if not online:
        return {"supported": False, "nodes": [], "canvas_online": False}
    try:
        selection = await adapter.get_selection()
    except AdapterError as exc:
        logger.debug("[canvas] 选中态读取失败: {}", exc)
        return {"supported": False, "nodes": [], "canvas_online": True}
    return {**selection, "canvas_online": True}


class CanvasSelectNodesRequest(BaseModel):
    node_ids: List[str] = Field(..., description="要设为选中的画布节点 id 列表")


@router.post("/canvas/select-nodes", response_model=CanvasSelectNodesResponse)
async def select_canvas_nodes(body: CanvasSelectNodesRequest):
    """反向联动：把指定节点设为画布当前选中（经适配器 canvas_select_nodes op）。"""
    adapter = get_canvas_adapter()
    return await adapter.select_nodes(body.node_ids)


class TimelinePushRequest(BaseModel):
    """B9b：时间线回画布——把分镜组的媒体/提示词批量建为 smart-image 节点（网格排列）。"""
    shot_group_id: str = ""
    canvas_id: str = ""


@router.post("/canvas/push-timeline")
async def push_timeline_to_canvas(body: TimelinePushRequest):
    """把指定分镜组（或全部分镜）的时间线批量推送到画布。

    只走画布既有公开接口（Rule 7）：批量建 smart-image 节点（x 递增 400 / y 递增 300，
    与 prompts/shared/canvas_tools.md 画布操作规则同口径，经 system_fc.md {{include}} 注入）。
    画布离线/未启用时诚实报错（不降级假装成功）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.tools.canvas_tools import CanvasBatchUpdateTool
    from src.video_agent.tools.base import ToolResult

    if not settings.canvas_enabled:
        raise AdapterError("画布功能未启用（CANVAS_ENABLED=false）", status_code=503, error_code="CANVAS_DISABLED")
    state = StateManager.get_instance().state_dict
    nodes = []
    idx = 0
    for group in state.get(CAT_SHOTS) or []:
        if not isinstance(group, dict):
            continue
        if body.shot_group_id and str(group.get("id") or "") != body.shot_group_id:
            continue
        for draft in (group.get("drafts") or []):
            if not isinstance(draft, dict):
                continue
            nodes.append({
                "node_type": "smart-image",
                "title": str(draft.get("label") or group.get("title") or ""),
                "x": 100 + (idx % 4) * 400,
                "y": 100 + (idx // 4) * 300,
                "prompt": str(draft.get("prompt") or "")[:2000],
                "image_url": str(draft.get("imgUrl") or ""),
                "content": "",
            })
            idx += 1
    if not nodes:
        raise AdapterError("故事板没有可推送的分镜（先拆解分镜）", status_code=400, error_code="NO_SHOTS")

    canvas_id = body.canvas_id
    if not canvas_id:
        target = await get_canvas_adapter().find_active_canvas()
        if not target:
            raise AdapterError("未找到可用的画布，请先在画布中创建一个画布", status_code=404, error_code="CANVAS_NOT_FOUND")
        canvas_id = str(target.get("id") or "")

    result: ToolResult = await CanvasBatchUpdateTool().aexecute(
        type("Params", (), {
            "canvas_id": canvas_id,
            "nodes": [type("Node", (), n)() for n in nodes],
        })()
    )
    if not result.success:
        raise AdapterError(str(result.error or "推送画布失败"), status_code=502, error_code="CANVAS_PUSH_FAILED")
    return {"ok": True, "canvas_id": canvas_id, "pushed": idx, "detail": result.data or {}}
