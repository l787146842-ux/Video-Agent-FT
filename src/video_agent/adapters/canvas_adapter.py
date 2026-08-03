"""
CanvasAdapter — 熊布画布 HTTP API 封装（Rule4: 外部调用走 Adapter）。

所有对熊布画布服务的 HTTP 请求集中在此，Tool 层不直接出现 httpx 调用。
失败统一抛 AdapterError。
"""
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError
from src.video_agent.utils import gen_id
from src.video_agent.utils.paths import DATA_DIR

# smart-image 节点默认缩放（与熊布 MEDIA_NODE_DEFAULT_SCALE 一致）
SMART_IMAGE_NODE_SCALE = 2
# 单图节点在 scale=2 下的近似半宽/半高，用于让节点中心对准落点
SMART_IMAGE_NODE_HALF = 224
# 落点夹取到可视世界矩形时的边距
DROP_CLAMP_MARGIN = 80

# 节点间最小间距（世界坐标 px）
NODE_GAP = 50

# 画布版本漂移记录文件（P1-5：对接的熊布版本，供更新后比对告警）
_CANVAS_VERSION_FILE = DATA_DIR / "canvas_integration.json"


def _validate_write_payload(
    nodes: List[Dict[str, Any]],
    connections: List[Dict[str, Any]],
    viewport: Dict[str, Any],
) -> None:
    """画布写回前的结构校验（P1-5）。

    adapter 硬编码了熊布内部 schema（smart-image 的 images[]、viewport x/y/scale 等），
    熊布是快速迭代的第三方项目，schema 漂移时宁可抛 AdapterError 也不写坏画布（Rule 7 边界自保）。
    只校验本项目写入路径所依赖的字段，不做全量 schema 校验。
    """
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            raise AdapterError(f"画布写入校验失败: nodes[{i}] 不是对象")
        if not n.get("id") or not isinstance(n.get("id"), str):
            raise AdapterError(f"画布写入校验失败: nodes[{i}] 缺少有效 id")
        if not n.get("type") or not isinstance(n.get("type"), str):
            raise AdapterError(f"画布写入校验失败: nodes[{i}] (id={n.get('id')}) 缺少有效 type")
        if n["type"] == "smart-image":
            images = n.get("images")
            if not isinstance(images, list) or not images:
                raise AdapterError(
                    f"画布写入校验失败: smart-image 节点 {n['id']} 的 images 必须是非空数组"
                )
            for j, img in enumerate(images):
                if not isinstance(img, dict) or not img.get("url"):
                    raise AdapterError(
                        f"画布写入校验失败: smart-image 节点 {n['id']} 的 images[{j}] 缺少 url"
                    )
    for i, c in enumerate(connections):
        if not isinstance(c, dict):
            raise AdapterError(f"画布写入校验失败: connections[{i}] 不是对象")
    if viewport:
        for key in ("x", "y", "scale"):
            v = viewport.get(key)
            if v is not None and not isinstance(v, (int, float)):
                raise AdapterError(f"画布写入校验失败: viewport.{key} 必须是数值，得到 {type(v).__name__}")
        scale = viewport.get("scale")
        if isinstance(scale, (int, float)) and scale <= 0:
            raise AdapterError("画布写入校验失败: viewport.scale 必须为正数")


def _find_free_position(
    existing_nodes: list,
    target_x: float,
    target_y: float,
    node_w: float,
    node_h: float,
) -> Tuple[float, float]:
    """在目标位置附近找到一个不与现有节点重叠的空白位置。

    策略：从目标位置开始，按右→下→左→上的螺旋方向向外搜索，
    直到找到一个与所有现有节点保持 NODE_GAP 间距的位置。
    """
    if not existing_nodes:
        return (target_x, target_y)

    # 收集现有节点的包围盒 (x, y, w, h)
    boxes = []
    for n in existing_nodes:
        nx = float(n.get("x") or 0)
        ny = float(n.get("y") or 0)
        nw = float(n.get("w") or 0) or (SMART_IMAGE_NODE_HALF * 2)
        nh = float(n.get("h") or 0) or (SMART_IMAGE_NODE_HALF * 2)
        boxes.append((nx, ny, nw, nh))

    def overlaps(px: float, py: float) -> bool:
        for (bx, by, bw, bh) in boxes:
            if (px < bx + bw + NODE_GAP and px + node_w + NODE_GAP > bx and
                py < by + bh + NODE_GAP and py + node_h + NODE_GAP > by):
                return True
        return False

    if not overlaps(target_x, target_y):
        return (target_x, target_y)

    step = node_w + NODE_GAP
    directions = [(step, 0), (0, step), (-step, 0), (0, -step)]
    cx, cy = target_x, target_y
    for ring in range(1, 12):
        for dx, dy in directions:
            for _ in range(ring):
                cx += dx
                cy += dy
                if not overlaps(cx, cy):
                    return (cx, cy)
    return (target_x + step * 3, target_y + step * 3)


def _resolve_drop_world_point(
    canvas: Dict[str, Any],
    drop_point: Optional[Tuple[float, float]],
    view_size: Optional[Tuple[float, float]],
) -> Tuple[float, float]:
    """把落点的屏幕坐标换算为画布世界坐标。

    viewport: 画布保存的 {x, y, scale}（世界→屏幕：screen = world * scale + viewport）。
    drop_point 相对画布 iframe 左上角的屏幕坐标，需扣除熊布外壳 UI 偏移（可配置估计值）。
    缺省/越界时回退到当前视口中心，保证节点始终落在用户视野内。
    """
    viewport = canvas.get("viewport") or {}
    vx = float(viewport.get("x") or 0)
    vy = float(viewport.get("y") or 0)
    scale = float(viewport.get("scale") or 1)
    if scale <= 0:
        scale = 1.0
    vw, vh = view_size if view_size and view_size[0] > 0 and view_size[1] > 0 else (1200.0, 800.0)

    center = ((vw / 2 - vx) / scale, (vh / 2 - vy) / scale)
    if not drop_point:
        return center

    ox = float(settings.canvas_shell_offset_x)
    oy = float(settings.canvas_shell_offset_y)
    wx = (drop_point[0] - ox - vx) / scale
    wy = (drop_point[1] - oy - vy) / scale

    # 夹取到当前可视世界矩形（含边距）内，外壳偏移估计失效时节点仍可见
    min_x, max_x = (0 - vx) / scale + DROP_CLAMP_MARGIN, (vw - vx) / scale - DROP_CLAMP_MARGIN
    min_y, max_y = (0 - vy) / scale + DROP_CLAMP_MARGIN, (vh - vy) / scale - DROP_CLAMP_MARGIN
    wx = min(max(wx, min_x), max_x) if min_x <= max_x else center[0]
    wy = min(max(wy, min_y), max_y) if min_y <= max_y else center[1]
    return (wx, wy)


class CanvasAdapter:
    """熊布画布 API 客户端"""

    def __init__(self, base_url: str = "", timeout: int = 0):
        self.base_url = (base_url or settings.canvas_base_url).rstrip("/")
        self.timeout = timeout or settings.canvas_timeout

    def _client(self) -> httpx.AsyncClient:
        # trust_env=False 禁用系统代理，避免本地回环地址被代理拦截
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, trust_env=False)

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        """统一请求入口，失败抛 AdapterError"""
        try:
            async with self._client() as client:
                resp = await client.request(method, path, **kwargs)
                if resp.status_code == 409:
                    # 乐观锁冲突 — 返回 409 让上层重试
                    raise AdapterError(
                        f"画布写入冲突（已被其他客户端更新），请重试: {path}",
                        status_code=409,
                    )
                resp.raise_for_status()
                return resp.json()
        except AdapterError:
            raise
        except httpx.ConnectError as exc:
            raise AdapterError(
                f"无法连接画布服务 ({self.base_url})，请确认熊布已启动: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AdapterError(f"画布服务响应超时 ({self.timeout}s): {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise AdapterError(
                f"画布 API 错误 [{exc.response.status_code}]: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"画布请求失败: {exc}") from exc

    # ---------- 画布 CRUD ----------

    async def list_canvases(self) -> List[Dict[str, Any]]:
        """获取画布列表"""
        data = await self._request("GET", "/api/canvases")
        return data.get("canvases", [])

    async def get_canvas(self, canvas_id: str) -> Dict[str, Any]:
        """获取画布完整数据（含 nodes/connections/viewport）"""
        data = await self._request("GET", f"/api/canvases/{canvas_id}")
        return data.get("canvas", data)

    async def save_canvas(
        self,
        canvas_id: str,
        *,
        title: str = "未命名画布",
        icon: str = "🧩",
        nodes: Optional[List[Dict[str, Any]]] = None,
        connections: Optional[List[Dict[str, Any]]] = None,
        viewport: Optional[Dict[str, Any]] = None,
        logs: Optional[List[Dict[str, Any]]] = None,
        settings_dict: Optional[Dict[str, Any]] = None,
        base_updated_at: int = 0,
        _max_retries: int = 3,
    ) -> Dict[str, Any]:
        """保存画布（PUT 全量写入），409 冲突时自动 re-read + re-apply（最多 _max_retries 次）"""
        # 写前校验：熊布 schema 漂移时在此拦截，避免写坏画布数据
        _validate_write_payload(nodes or [], connections or [], viewport or {})
        payload = {
            "title": title,
            "icon": icon,
            "nodes": nodes or [],
            "connections": connections or [],
            "viewport": viewport or {"x": 0, "y": 0, "scale": 1},
            "logs": logs or [],
            "settings": settings_dict or {},
            "client_id": "ftdyb-agent",
            "base_updated_at": base_updated_at,
        }
        last_error: Optional[AdapterError] = None
        for attempt in range(_max_retries):
            try:
                data = await self._request("PUT", f"/api/canvases/{canvas_id}", json=payload)
                return data.get("canvas", data)
            except AdapterError as e:
                if e.status_code != 409:
                    raise
                last_error = e
                if attempt < _max_retries - 1:
                    # re-read 获取最新 updated_at，然后 re-apply
                    logger.info(f"[CanvasAdapter] 409 冲突，重试 {attempt + 1}/{_max_retries}: re-read canvas {canvas_id}")
                    try:
                        latest = await self.get_canvas(canvas_id)
                        payload["base_updated_at"] = latest.get("updated_at", 0)
                    except Exception:
                        pass  # re-read 失败则用原值重试
        raise last_error  # type: ignore[misc]

    async def create_canvas(
        self, title: str = "未命名画布", kind: str = "smart", icon: str = "sparkles"
    ) -> Dict[str, Any]:
        """新建画布"""
        payload = {"title": title, "kind": kind, "icon": icon}
        data = await self._request("POST", "/api/canvases", json=payload)
        return data.get("canvas", data)

    # ---------- 素材库 ----------

    async def list_assets(self) -> Any:
        """获取画布素材索引"""
        return await self._request("GET", "/api/canvas-assets")

    async def upload_files(self, files: List[Tuple[str, bytes, str]]) -> List[Dict[str, Any]]:
        """上传文件到画布素材库（POST /api/ai/upload，与画布拉拽入图的既有接口一致）。

        files: [(filename, content, mime)]，返回 [{url, name, kind, mime?}]（url 为画布本地路径）。
        """
        if not files:
            return []
        multipart = [("files", (name, content, mime)) for name, content, mime in files]
        try:
            async with self._client() as client:
                resp = await client.post("/api/ai/upload", files=multipart)
                resp.raise_for_status()
                data = resp.json()
        except AdapterError:
            raise
        except httpx.ConnectError as exc:
            raise AdapterError(
                f"无法连接画布服务 ({self.base_url})，请确认熊布已启动: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AdapterError(f"画布服务响应超时 ({self.timeout}s): {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise AdapterError(
                f"画布上传失败 [{exc.response.status_code}]: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"画布上传请求失败: {exc}") from exc
        uploaded = data.get("files", [])
        return [f for f in uploaded if isinstance(f, dict) and f.get("url")]

    # ---------- 拖放图片节点（对话栏图片拖入画布） ----------

    async def find_active_smart_canvas(self) -> Optional[Dict[str, Any]]:
        """推断当前活跃的智能画布：未删除、kind=smart 的画布中 updated_at 最新者。

        画布服务不提供"当前打开"接口（Rule7 只能用既有公开接口），
        单用户场景下最近编辑的智能画布即为用户正在查看的画布。
        """
        canvases = await self.list_canvases()
        smart = [
            c for c in canvases
            if not c.get("deleted_at") and str(c.get("kind") or "").strip().lower() == "smart"
        ]
        if not smart:
            return None
        return max(smart, key=lambda c: int(c.get("updated_at") or 0))

    async def find_active_canvas(self) -> Optional[Dict[str, Any]]:
        """推断当前活跃画布：未删除画布中 updated_at 最新者（不限 kind）。

        用于"导出到当前画布"场景，普通画布和智能画布均可命中。
        """
        canvases = await self.list_canvases()
        active = [c for c in canvases if not c.get("deleted_at")]
        if not active:
            return None
        return max(active, key=lambda c: int(c.get("updated_at") or 0))

    async def add_image_node(
        self,
        canvas_id: str,
        *,
        image: Dict[str, str],
        drop_point: Optional[Tuple[float, float]] = None,
        view_size: Optional[Tuple[float, float]] = None,
        canvas_kind: str = "smart",
    ) -> Dict[str, Any]:
        """读取画布 → 在可视区内追加一个图片节点 → 写回（409 由 save_canvas 内部重试）。

        image: {"url": ..., "name": ..., "kind": "image"}；
        drop_point: 落点在画布 iframe 内的屏幕坐标 (x, y)，缺省时放到视口中心；
        view_size: 画布 iframe 可视尺寸 (w, h)，用于把落点换算成世界坐标。
        canvas_kind: "smart" 创建 smart-image 节点；其他创建普通 image 节点。
        返回 {"node_id", "canvas_id", "canvas_title"}。
        """
        canvas = await self.get_canvas(canvas_id)
        wx, wy = _resolve_drop_world_point(canvas, drop_point, view_size)

        # 节点尺寸（用于碰撞检测）
        if canvas_kind == "smart":
            nw = nh = SMART_IMAGE_NODE_HALF * 2
        else:
            nw = nh = 300

        # 无指定落点时，自动避让现有节点
        if not drop_point:
            existing = list(canvas.get("nodes") or [])
            # 目标位置是节点左上角（wx/wy 是中心点）
            free_x, free_y = _find_free_position(
                existing, wx - nw / 2, wy - nh / 2, nw, nh
            )
            wx = free_x + nw / 2
            wy = free_y + nh / 2

        if canvas_kind == "smart":
            # 智能画布：smart-image 节点 + images[] 数组
            node = {
                "id": gen_id("smart", wide=True),
                "type": "smart-image",
                "x": round(wx - SMART_IMAGE_NODE_HALF),
                "y": round(wy - SMART_IMAGE_NODE_HALF),
                "title": "Image",
                "scale": SMART_IMAGE_NODE_SCALE,
                "images": [{"url": image["url"], "name": image.get("name") or "image", "kind": "image"}],
                "created_at": int(time.time() * 1000),
            }
        else:
            # 普通画布：image 节点（与拖拽文件进画布产生的节点格式一致）
            node = {
                "id": gen_id("img", wide=True),
                "type": "image",
                "x": round(wx - 150),
                "y": round(wy - 150),
                "w": 300,
                "h": 300,
                "url": image["url"],
                "name": image.get("name") or "image",
                "created_at": int(time.time() * 1000),
            }
        nodes = list(canvas.get("nodes") or [])
        nodes.append(node)
        await self.save_canvas(
            canvas_id,
            title=canvas.get("title", "未命名画布"),
            icon=canvas.get("icon", "🧩"),
            nodes=nodes,
            connections=canvas.get("connections", []),
            viewport=canvas.get("viewport", {}),
            logs=canvas.get("logs", []),
            settings_dict=canvas.get("settings", {}),
            base_updated_at=int(canvas.get("updated_at") or 0),
        )
        logger.info(f"[CanvasAdapter] 拖放图片已写入画布 {canvas_id}: node={node['id']}")
        return {"node_id": node["id"], "canvas_id": canvas_id, "canvas_title": canvas.get("title", "")}

    async def list_asset_library(self) -> Any:
        """获取熊布素材库管理系统完整数据（libraries/categories/items）"""
        data = await self._request("GET", "/api/asset-library")
        return data.get("library", data)

    async def list_local_assets(self) -> Any:
        """获取熊布本地上传素材列表"""
        data = await self._request("GET", "/api/local-assets")
        return data.get("items", [])

    # ---------- 生图任务 ----------

    async def submit_image_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """提交异步生图任务"""
        return await self._request("POST", "/api/canvas-image-tasks", json=payload)

    async def get_image_task(self, task_id: str) -> Dict[str, Any]:
        """查询生图任务状态"""
        return await self._request("GET", f"/api/canvas-image-tasks/{task_id}")

    # ---------- 在线检测与智能路由 ----------

    async def is_online(self) -> bool:
        """检测熊布是否在线（带缓存，避免高频探测）"""
        global _health_cache, _health_cache_time
        cache_ttl = settings.canvas_health_cache_seconds
        if _health_cache is not None and (time.time() - _health_cache_time) < cache_ttl:
            return _health_cache
        try:
            async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
                resp = await client.get(f"{self.base_url}/api/providers")
                online = resp.status_code == 200
        except Exception:
            online = False
        _health_cache = online
        _health_cache_time = time.time()
        if not online:
            logger.debug("[CanvasAdapter] 熊布离线")
        return online

    async def generate_image_online(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """通过熊布的 /api/online-image 接口同步生图。
        失败抛 AdapterError。"""
        return await self._request("POST", "/api/online-image", json=payload)

    # ---------- 版本漂移探测（P1-5） ----------

    async def get_app_info(self) -> Dict[str, Any]:
        """读取熊布 /api/app-info（含 version 字段）"""
        return await self._request("GET", "/api/app-info")

    async def check_version_drift(self) -> Optional[str]:
        """比对熊布版本与上次记录，漂移时记录并返回告警信息（无漂移/离线返回 None）。

        adapter 硬编码了熊布内部 schema，熊布更新后需重新验证集成（跑契约测试），
        故启动时探测一次版本并在漂移时 warning。记录持久化到 data/canvas_integration.json。
        """
        try:
            if not await self.is_online():
                return None
            info = await self.get_app_info()
        except Exception:
            return None  # 探测失败不阻塞启动
        version = str(info.get("version") or "").strip()
        if not version:
            return None
        recorded = ""
        try:
            if _CANVAS_VERSION_FILE.exists():
                recorded = str(json.loads(_CANVAS_VERSION_FILE.read_text(encoding="utf-8")).get("version") or "")
        except Exception:
            recorded = ""
        drift_msg: Optional[str] = None
        if recorded and recorded != version:
            drift_msg = (
                f"熊布画布已更新: {recorded} → {version}。"
                "集成依赖其内部 schema，请重新验证（运行 tests/integration 画布契约测试）"
            )
            logger.warning(f"[CanvasAdapter] {drift_msg}")
        if recorded != version:
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                _CANVAS_VERSION_FILE.write_text(
                    json.dumps({"version": version, "checked_at": int(time.time())}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.debug(f"[CanvasAdapter] 版本记录写入失败: {exc}")
        return drift_msg


# ---------- 模块级单例 ----------

_adapter_instance: Optional[CanvasAdapter] = None

# 心跳缓存
_health_cache: Optional[bool] = None
_health_cache_time: float = 0.0


def get_canvas_adapter() -> CanvasAdapter:
    """获取全局 CanvasAdapter 单例"""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = CanvasAdapter()
        logger.debug(f"[CanvasAdapter] 初始化: base_url={_adapter_instance.base_url}")
    return _adapter_instance


def reset_canvas_adapter():
    """重置单例与健康检查缓存（测试用，避免测试间缓存串味）"""
    global _adapter_instance, _health_cache, _health_cache_time
    _adapter_instance = None
    _health_cache = None
    _health_cache_time = 0.0
