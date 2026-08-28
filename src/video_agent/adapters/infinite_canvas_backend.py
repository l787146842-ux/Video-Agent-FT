"""
InfiniteCanvasBackend — infinite-canvas canvas-agent 通道适配器（Rule4: 外部调用走 Adapter）。

画布后端唯一实现（infinite-canvas），满足 adapters/canvas_port.py CanvasBackend 端口。
所有外部调用收敛为 POST /api/tools（工具调用）与 GET /health、/config（探活/版本），
Tool 层不直接出现 httpx 调用。失败统一抛 AdapterError。

对端契约出处（只读参照，禁止修改该目录任何文件）：
E:\\09 Github上的实用工具\\infinite-canvas-main\\canvas-agent\\src\\canvas\\schemas.ts（34 工具与 ops 闭集）
E:\\09 Github上的实用工具\\infinite-canvas-main\\canvas-agent\\src\\server\\http.ts（/api/tools、/health、/config、token 鉴权）
E:\\09 Github上的实用工具\\infinite-canvas-main\\canvas-agent\\src\\canvas\\session.ts（AGENT_PROTOCOL_VERSION）
"""
import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import httpx
from loguru import logger

from src.video_agent.adapters.canvas_schema import (
    CANVAS_TOOL_TO_INFINITE_CANVAS_NODE_TYPE,
    INFINITE_CANVAS_IMAGE_MEDIA_FIELD,
)
from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError
from src.video_agent.utils import gen_id
from src.video_agent.utils.paths import ASSETS_DIR, DATA_DIR

if TYPE_CHECKING:
    from src.video_agent.adapters.canvas_port import CanvasBackend

# canvas-agent 协议版本钉住值（契约出处 session.ts AGENT_PROTOCOL_VERSION；
# 漂移由契约测试 tests/integration/test_infinite_canvas_contract.py 拦截）
PROTOCOL_VERSION = 6

# canvas_apply_ops 批量分片：单批操作上限（串行提交，单批失败单批重试一次）
APPLY_OPS_BATCH_SIZE = 20

# 画布版本漂移记录文件（协议版本持久化，供更新后比对告警）
_CANVAS_VERSION_FILE = DATA_DIR / "canvas_integration.json"

# 生图轮询间隔（秒）
_IMAGE_POLL_INTERVAL = 2.0

# 生图轮询早停：提交的任务连续未出现在 generation_get_status 达此轮数即抛错降级，
# 避免任务丢失场景卡满 image_gen_timeout
_IMAGE_POLL_MAX_MISSES = 5

# /health 快探独立超时（秒）：在线探测不与写路径 canvas_timeout 共用，
# 与旧熊布快探口径对齐（负缓存维持原状，不在此新增）
_HEALTH_PROBE_TIMEOUT = 2.0

# 默认图片节点尺寸（世界坐标 px）
_IMAGE_NODE_SIZE = 320

# 单批失败重试前的退避（秒）
_RETRY_BACKOFF = 0.5


def _resolve_token(explicit: str = "") -> str:
    """token 优先取显式参数/环境变量，回退读 ~/.infinite-canvas/canvas-agent.json。

    canvas-agent 首次启动自动生成该配置文件（含 url+token，仅本机使用）。
    """
    tok = (explicit or settings.canvas_agent_token or "").strip()
    if tok:
        return tok
    cfg = Path.home() / ".infinite-canvas" / "canvas-agent.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return str(data.get("token") or "").strip()
    except Exception:
        return ""


def resolve_canvas_agent_token(explicit: str = "") -> str:
    """token 解析的对外公开入口（/api/config 下发等复用，避免重复实现）"""
    return _resolve_token(explicit)


def _agent_static_base() -> str:
    """本 Agent 服务对浏览器可见的基址（画布站点需回源拉取素材图）"""
    host = settings.host if settings.host not in ("0.0.0.0", "::") else "127.0.0.1"
    return f"http://{host}:{settings.port}"


def _absolutize_url(url: str) -> str:
    """把 /workspace/assets/... 相对地址换算为 Agent 静态绝对 URL（画布节点可直接引用）"""
    if url.startswith("/"):
        return f"{_agent_static_base()}{url}"
    return url


def _to_infinite_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """把工具层节点字典转换为 infinite-canvas 节点结构（add_node/update_node 用）。

    类型映射经 canvas_schema.CANVAS_TOOL_TO_INFINITE_CANVAS_NODE_TYPE；
    图片 URL / 文本正文统一存 metadata.content（对端 image/text 节点负载契约，
    出处 canvas-agent/src/canvas/schemas.ts 的 metadata recordSchema）。
    """
    raw_type = str(node.get("type") or "text")
    node_type = CANVAS_TOOL_TO_INFINITE_CANVAS_NODE_TYPE.get(raw_type)
    if node_type is None:
        raise AdapterError(f"画布写入校验失败: 不支持的节点类型 {raw_type!r}")
    pos = node.get("position") or {}
    x = float(node.get("x", pos.get("x", 0)) or 0)
    y = float(node.get("y", pos.get("y", 0)) or 0)
    if node_type == "image":
        images = node.get("images") or []
        url = ""
        if images and isinstance(images[0], dict):
            url = str(images[0].get("url") or "")
        url = url or str(node.get("url") or "")
        if not url:
            raise AdapterError(f"画布写入校验失败: 图片节点 {node.get('id')} 缺少 url")
        content = _absolutize_url(url)
    else:
        content = str(node.get("prompt") or node.get("content") or node.get("text") or "")
    metadata: Dict[str, Any] = {INFINITE_CANVAS_IMAGE_MEDIA_FIELD: content}
    if node.get("status"):
        metadata["status"] = node["status"]
    out: Dict[str, Any] = {
        "id": node.get("id"),
        "nodeType": node_type,
        "title": node.get("title") or "",
        "position": {"x": x, "y": y},
        "metadata": metadata,
    }
    width = node.get("w") or node.get("width")
    height = node.get("h") or node.get("height")
    if width:
        out["width"] = float(width)
    if height:
        out["height"] = float(height)
    return out


def _resolve_drop_point(
    state: Dict[str, Any],
    drop_point: Optional[Tuple[float, float]],
    view_size: Optional[Tuple[float, float]],
) -> Tuple[float, float]:
    """把落点屏幕坐标换算为画布世界坐标（viewport {x,y,k}: screen = world*k + offset）。

    缺省/越界时回退到当前视口中心（含边距夹取）。
    """
    viewport = state.get("viewport") or {}
    vx = float(viewport.get("x") or 0)
    vy = float(viewport.get("y") or 0)
    k = float(viewport.get("k") or 1)
    if k <= 0:
        k = 1.0
    vw, vh = view_size if view_size and view_size[0] > 0 and view_size[1] > 0 else (1200.0, 800.0)
    center = ((vw / 2 - vx) / k, (vh / 2 - vy) / k)
    if not drop_point:
        return center
    ox = float(settings.canvas_shell_offset_x)
    oy = float(settings.canvas_shell_offset_y)
    wx = (drop_point[0] - ox - vx) / k
    wy = (drop_point[1] - oy - vy) / k
    margin = 80
    min_x, max_x = (0 - vx) / k + margin, (vw - vx) / k - margin
    min_y, max_y = (0 - vy) / k + margin, (vh - vy) / k - margin
    wx = min(max(wx, min_x), max_x) if min_x <= max_x else center[0]
    wy = min(max(wy, min_y), max_y) if min_y <= max_y else center[1]
    return (wx, wy)


def _safe_asset_name(filename: str) -> str:
    """assets 目录内不重名安全文件名（防路径穿越，与 /api/ai/upload 口径一致）"""
    stem = "".join(ch for ch in Path(filename).stem if ch.isalnum() or ch in "-_") or "file"
    suffix = Path(filename).suffix.lower()
    allowed = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".mp4", ".webm",
               ".mp3", ".wav", ".txt", ".md", ".json")
    if suffix not in allowed:
        suffix = ".bin"
    return f"{stem}-{gen_id('up', wide=True)}{suffix}"


def _extract_generated_ids(result: Any) -> List[str]:
    """从提交结果中扫描生成配置节点 id（config-*，供轮询定位任务）"""
    ids: List[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if value.startswith("config-"):
                ids.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(result)
    return ids


class InfiniteCanvasBackend:
    """infinite-canvas canvas-agent 客户端（单例 AsyncClient，token 头 x-canvas-agent-token）"""

    def __init__(self, base_url: str = "", token: str = "", timeout: int = 0):
        self.base_url = (base_url or settings.canvas_agent_url).rstrip("/")
        self.timeout = timeout or settings.canvas_timeout
        self._explicit_token = token
        self._client: Optional[httpx.AsyncClient] = None
        # canvas_get_state TTL 快照缓存（写路径一律绕过）；代际号防写前旧快照回填：
        # invalidate_state_cache 递增代际，在途读回填前比对，代际已变则弃回填
        self._state_cache: Optional[Dict[str, Any]] = None
        self._state_cache_time: float = 0.0
        self._state_cache_generation: int = 0
        self._health_cache: Optional[Dict[str, Any]] = None
        self._health_cache_time: float = 0.0

    def client(self) -> httpx.AsyncClient:
        """进程内单例连接池（懒建：等 canvas-agent 生成配置文件后仍能取到 token）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                trust_env=False,  # 禁用系统代理，避免本地回环被代理拦截
                headers={"x-canvas-agent-token": _resolve_token(self._explicit_token)},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ---------- 底层通道 ----------

    async def _get_json(self, path: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """GET 公开端点（/health、/config），失败抛 AdapterError；
        timeout 为本次请求独立超时（快探用），缺省沿用客户端全局超时"""
        try:
            extra = {"timeout": timeout} if timeout is not None else {}
            resp = await self.client().get(path, **extra)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError as exc:
            raise AdapterError(
                f"无法连接 canvas-agent ({self.base_url})，请确认 canvas-agent 已启动: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AdapterError(f"canvas-agent 响应超时 ({self.timeout}s): {exc}", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            raise AdapterError(
                f"canvas-agent API 错误 [{exc.response.status_code}]: {exc.response.text[:300]}",
                http_status=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"canvas-agent 请求失败: {exc}") from exc

    async def _call_tool(self, name: str, tool_input: Optional[Dict[str, Any]] = None) -> Any:
        """统一工具调用入口：POST /api/tools，body {name, input}，返回 result 字段"""
        try:
            resp = await self.client().post(
                "/api/tools", json={"name": name, "input": tool_input or {}}
            )
        except httpx.ConnectError as exc:
            raise AdapterError(
                f"无法连接 canvas-agent ({self.base_url})，请确认 canvas-agent 已启动: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AdapterError(f"canvas-agent 响应超时 ({self.timeout}s): {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"canvas-agent 请求失败: {exc}") from exc
        if resp.status_code == 401:
            raise AdapterError(
                "canvas-agent token 无效，请检查 CANVAS_AGENT_TOKEN 或 ~/.infinite-canvas/canvas-agent.json",
                status_code=401,
            )
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400 or not data.get("ok"):
            msg = str(data.get("error") or resp.text[:300])
            timeout_like = "超时" in msg or "timed out" in msg.lower()
            raise AdapterError(
                f"infinite-canvas 工具 {name} 失败: {msg}",
                retryable=True if timeout_like else None,
                http_status=resp.status_code,
            )
        return data.get("result")

    async def health(self) -> Dict[str, Any]:
        """GET /health 全量（含 hasCanvas，可区分“服务在线但画布页未开”），带 TTL 缓存；
        探测用独立 2s 快超时，不复用写路径 canvas_timeout"""
        ttl = settings.canvas_health_cache_seconds
        if self._health_cache is not None and (time.time() - self._health_cache_time) < ttl:
            return self._health_cache
        data = await self._get_json("/health", timeout=_HEALTH_PROBE_TIMEOUT)
        self._health_cache = data
        self._health_cache_time = time.time()
        return data

    async def _get_state(self, *, use_cache: bool = True) -> Dict[str, Any]:
        """canvas_get_state（TTL 快照缓存）；写路径/差异计算须 use_cache=False"""
        ttl = settings.canvas_agent_state_cache_seconds
        if use_cache and self._state_cache is not None and (time.time() - self._state_cache_time) < ttl:
            return self._state_cache
        generation = self._state_cache_generation
        state = await self._call_tool("canvas_get_state")
        if not isinstance(state, dict):
            raise AdapterError("infinite-canvas canvas_get_state 返回结构异常")
        # 在途读回填前比对代际：读期间发生过写失效则弃回填，防旧快照覆盖新状态
        if generation == self._state_cache_generation:
            self._state_cache = state
            self._state_cache_time = time.time()
        return state

    def invalidate_state_cache(self) -> None:
        self._state_cache = None
        self._state_cache_time = 0.0
        self._state_cache_generation += 1

    async def _apply_ops(self, ops: List[Dict[str, Any]]) -> List[Any]:
        """canvas_apply_ops 分片串行提交（每批 APPLY_OPS_BATCH_SIZE，单批失败重试一次）"""
        results: List[Any] = []
        for i in range(0, len(ops), APPLY_OPS_BATCH_SIZE):
            batch = ops[i:i + APPLY_OPS_BATCH_SIZE]
            try:
                results.append(await self._call_tool("canvas_apply_ops", {"ops": batch}))
            except AdapterError as exc:
                if exc.status_code == 401:
                    raise
                logger.warning(
                    f"[InfiniteCanvas] canvas_apply_ops 第 {i // APPLY_OPS_BATCH_SIZE + 1} 批失败，重试: {exc}"
                )
                await asyncio.sleep(_RETRY_BACKOFF)
                results.append(await self._call_tool("canvas_apply_ops", {"ops": batch}))
        return results

    def _build_sync_ops(
        self,
        current: Dict[str, Any],
        target_nodes: List[Dict[str, Any]],
        target_connections: List[Dict[str, Any]],
        viewport: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """对当前页状态做增量 diff，产出 ops（add/update/delete/connect/viewport）"""
        cur_nodes = {n["id"]: n for n in current.get("nodes", []) if isinstance(n, dict) and n.get("id")}
        ops: List[Dict[str, Any]] = []
        target_ids: set = set()
        for node in target_nodes:
            ic = _to_infinite_node(node)
            node_id = ic.get("id")
            if not node_id:
                add_op: Dict[str, Any] = {"type": "add_node"}
                add_op.update({k: v for k, v in ic.items() if k != "id"})
                ops.append(add_op)
                continue
            target_ids.add(node_id)
            if node_id in cur_nodes:
                patch: Dict[str, Any] = {"position": ic["position"]}
                if ic.get("title"):
                    patch["title"] = ic["title"]
                if ic.get("width"):
                    patch["width"] = ic["width"]
                if ic.get("height"):
                    patch["height"] = ic["height"]
                ops.append({"type": "update_node", "id": node_id, "patch": patch, "metadata": ic["metadata"]})
            else:
                add_op = {"type": "add_node"}
                add_op.update(ic)
                ops.append(add_op)
        removed = [nid for nid in cur_nodes if nid not in target_ids]
        for i in range(0, len(removed), APPLY_OPS_BATCH_SIZE):
            ops.append({"type": "delete_node", "ids": removed[i:i + APPLY_OPS_BATCH_SIZE]})
        # 连线：按 (from, to) 对 diff（对端连线带独立 id，删除需 id）
        cur_pairs: Dict[Tuple[str, str], str] = {}
        for c in current.get("connections", []):
            if isinstance(c, dict) and c.get("fromNodeId") and c.get("toNodeId"):
                cur_pairs[(c["fromNodeId"], c["toNodeId"])] = str(c.get("id") or "")
        target_pairs: set = set()
        for c in target_connections:
            if not isinstance(c, dict):
                continue
            frm = c.get("fromNodeId") or c.get("from")
            to = c.get("toNodeId") or c.get("to")
            if frm and to:
                target_pairs.add((str(frm), str(to)))
        del_ids = [cid for pair, cid in cur_pairs.items() if pair not in target_pairs and cid]
        if del_ids:
            ops.append({"type": "delete_connections", "ids": del_ids})
        for frm, to in sorted(target_pairs):
            if (frm, to) not in cur_pairs:
                ops.append({"type": "connect_nodes", "fromNodeId": frm, "toNodeId": to})
        if viewport:
            scale = float(viewport.get("scale") or viewport.get("k") or 1)
            if scale <= 0:
                scale = 1.0
            ops.append({
                "type": "set_viewport",
                "viewport": {
                    "x": float(viewport.get("x") or 0),
                    "y": float(viewport.get("y") or 0),
                    "k": scale,
                },
            })
        return ops

    # ---------- 画布 CRUD ----------

    async def list_canvases(self) -> List[Dict[str, Any]]:
        """canvas_list_projects → items[]（id/title/createdAt/updatedAt/nodeCount/connectionCount）"""
        data = await self._call_tool("canvas_list_projects", {"page": 1, "pageSize": 100})
        items = (data or {}).get("items", [])
        return [i for i in items if isinstance(i, dict) and i.get("id")]

    async def get_canvas(self, canvas_id: str = "") -> Dict[str, Any]:
        """canvas_get_state（TTL 缓存）；当前连接页不是目标画布时先 site_navigate 再读"""
        state = await self._get_state()
        if canvas_id and state.get("projectId") and state["projectId"] != canvas_id:
            await self._call_tool("site_navigate", {"path": f"/canvas/{canvas_id}"})
            self.invalidate_state_cache()
            state = await self._get_state(use_cache=False)
            if state.get("projectId") and state["projectId"] != canvas_id:
                raise AdapterError(f"infinite-canvas 无法打开目标画布: {canvas_id}")
        return state

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
        """全量写回 → 换算为增量 canvas_apply_ops（infinite-canvas 无整板替换接口）。

        对当前页状态差异计算：新增/更新/删除节点、连线 diff、set_viewport。
        title/icon/logs/settings_dict/base_updated_at/_max_retries 为整板保存参数，
        本通道不适用（项目重命名无对应工具），忽略。
        """
        await self.get_canvas(canvas_id)  # 确保页面在目标画布
        current = await self._get_state(use_cache=False)
        ops = self._build_sync_ops(current, nodes or [], connections or [], viewport)
        if ops:
            await self._apply_ops(ops)
        self.invalidate_state_cache()
        return await self._get_state(use_cache=False)

    async def create_canvas(
        self, title: str = "未命名画布", kind: str = "smart", icon: str = "sparkles"
    ) -> Dict[str, Any]:
        """infinite-canvas 34 工具闭集无新建项目工具：尽力打开画布列表页引导手动创建"""
        try:
            await self._call_tool("site_navigate", {"path": "/canvas"})
        except AdapterError:
            pass
        raise AdapterError(
            "infinite-canvas 未提供新建画布工具，请在画布页面手动创建", status_code=501
        )

    # ---------- 节点级写（增量 canvas_apply_ops 直发，无整板读改写） ----------
    # 入参节点字典为工具层语义形状，经 _to_infinite_node 转换。

    async def add_node(self, canvas_id: str, *, node: Dict[str, Any]) -> Dict[str, Any]:
        """追加单个节点：单条 add_node op 直发"""
        await self.get_canvas(canvas_id)
        ic = _to_infinite_node(node)
        op: Dict[str, Any] = {"type": "add_node"}
        op.update(ic)
        await self._apply_ops([op])
        self.invalidate_state_cache()
        return {"node_id": ic.get("id"), "canvas_id": canvas_id}

    async def update_node(
        self, canvas_id: str, *, node_id: str, patch: Dict[str, Any]
    ) -> bool:
        """修改指定节点：新鲜快照定位后单条 update_node op 直发；返回是否存在"""
        await self.get_canvas(canvas_id)
        state = await self._get_state(use_cache=False)
        node = next(
            (n for n in state.get("nodes", []) if isinstance(n, dict) and n.get("id") == node_id),
            None,
        )
        if node is None:
            return False
        pos = node.get("position") or {}
        x, y = patch.get("x"), patch.get("y")
        ic_patch: Dict[str, Any] = {
            "position": {
                "x": float(x) if x is not None else float(pos.get("x") or 0),
                "y": float(y) if y is not None else float(pos.get("y") or 0),
            }
        }
        if patch.get("title") is not None:
            ic_patch["title"] = str(patch["title"])
        metadata: Optional[Dict[str, Any]] = None
        if node.get("type") == "image":
            if patch.get("image_url") is not None:
                metadata = {INFINITE_CANVAS_IMAGE_MEDIA_FIELD: _absolutize_url(str(patch["image_url"]))}
        else:
            text = patch.get("prompt") if patch.get("prompt") is not None else patch.get("content")
            if text is not None:
                metadata = {INFINITE_CANVAS_IMAGE_MEDIA_FIELD: str(text)}
        op: Dict[str, Any] = {"type": "update_node", "id": node_id, "patch": ic_patch}
        if metadata is not None:
            op["metadata"] = metadata
        await self._apply_ops([op])
        self.invalidate_state_cache()
        return True

    async def delete_node(self, canvas_id: str, *, node_id: str) -> bool:
        """删除指定节点（新鲜快照定位；相关连线一并 delete_connections）；返回是否存在"""
        await self.get_canvas(canvas_id)
        state = await self._get_state(use_cache=False)
        if not any(isinstance(n, dict) and n.get("id") == node_id for n in state.get("nodes", [])):
            return False
        ops: List[Dict[str, Any]] = [{"type": "delete_node", "ids": [node_id]}]
        conn_ids = [
            str(c.get("id")) for c in state.get("connections", [])
            if isinstance(c, dict) and c.get("id")
            and (c.get("fromNodeId") == node_id or c.get("toNodeId") == node_id)
        ]
        if conn_ids:
            ops.append({"type": "delete_connections", "ids": conn_ids})
        await self._apply_ops(ops)
        self.invalidate_state_cache()
        return True

    async def add_nodes_batch(
        self, canvas_id: str, *, nodes: List[Dict[str, Any]]
    ) -> List[str]:
        """批量追加节点：一次 canvas_apply_ops 批量提交（网格坐标由调用方预计算）"""
        await self.get_canvas(canvas_id)
        ops: List[Dict[str, Any]] = []
        ids: List[str] = []
        for n in nodes:
            ic = _to_infinite_node(n)
            op: Dict[str, Any] = {"type": "add_node"}
            op.update(ic)
            ops.append(op)
            ids.append(str(ic.get("id") or ""))
        if ops:
            await self._apply_ops(ops)
            self.invalidate_state_cache()
        return ids

    async def get_selection(self) -> Dict[str, Any]:
        """canvas_get_selection 读当前页选中节点（契约：{nodes: [...]}）"""
        data = await self._call_tool("canvas_get_selection")
        nodes = (data or {}).get("nodes", []) if isinstance(data, dict) else []
        return {"supported": True, "nodes": [n for n in nodes if isinstance(n, dict)]}

    async def select_nodes(self, node_ids: List[str]) -> Dict[str, Any]:
        """canvas_select_nodes 设置当前页选中节点（契约：{ids: [...]}，schemas.ts 闭集内）"""
        ids = [str(n) for n in node_ids if str(n).strip()]
        if not ids:
            return {"supported": True, "selected": 0}
        await self._call_tool("canvas_select_nodes", {"ids": ids})
        self.invalidate_state_cache()
        return {"supported": True, "selected": len(ids)}

    # ---------- 素材库 ----------

    async def list_assets(self) -> Any:
        """assets_list（kind=all）→ {total, page, pageSize, items}"""
        return await self._call_tool("assets_list", {"kind": "all", "page": 1, "pageSize": 100})

    async def list_asset_library(self) -> Any:
        """素材库全量 → assets_list（infinite-canvas 无 library/category 层级，返回平铺列表）"""
        data = await self._call_tool("assets_list", {"kind": "all", "page": 1, "pageSize": 100})
        return {"items": (data or {}).get("items", []), "total": (data or {}).get("total", 0)}

    async def list_local_assets(self) -> Any:
        """本地上传素材 → assets_list（kind=image）的 items"""
        data = await self._call_tool("assets_list", {"kind": "image", "page": 1, "pageSize": 100})
        return (data or {}).get("items", [])

    async def upload_files(self, files: List[Tuple[str, bytes, str]]) -> List[Dict[str, Any]]:
        """写文件到 workspace/assets/ 后以 imageUrl 形式经 assets_add 注册。

        返回 {url, name, kind, mime}，url 为 /workspace/assets/... 相对地址；
        画布节点引用时经 _absolutize_url 换算为 Agent 静态绝对 URL。
        注册失败不回滚（文件已可用，仅素材库缺少条目）。
        """
        if not files:
            return []
        results: List[Dict[str, Any]] = []
        for filename, content, mime in files:
            safe = _safe_asset_name(filename)
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            (ASSETS_DIR / safe).write_bytes(content)
            url = f"/workspace/assets/{safe}"
            kind = "image" if str(mime).startswith("image/") else (
                "text" if str(mime).startswith("text/") else "file")
            if kind == "image":
                try:
                    await self._call_tool("assets_add", {
                        "kind": "image", "title": filename,
                        "imageUrl": _absolutize_url(url), "source": "ftdyb-agent",
                    })
                except AdapterError as exc:
                    logger.warning(f"[InfiniteCanvas] assets_add(image) 失败，文件仍可用: {exc}")
            elif kind == "text":
                try:
                    await self._call_tool("assets_add", {
                        "kind": "text", "title": filename,
                        "content": content.decode("utf-8", errors="replace"),
                        "source": "ftdyb-agent",
                    })
                except AdapterError as exc:
                    logger.warning(f"[InfiniteCanvas] assets_add(text) 失败，文件仍可用: {exc}")
            results.append({"url": url, "name": filename, "kind": kind, "mime": mime})
        return results

    # ---------- 拖放图片节点 ----------

    async def prepare_drop_image(
        self,
        *,
        url: str,
        name: str,
        local_path: Optional[Path],
        mime: str,
        public_base: str,
    ) -> Dict[str, str]:
        """infinite-canvas 拖放物化：节点直接引用本站绝对 URL，无二次上传。
        （画布站点经 Agent 静态端点回源拉取素材图）"""
        if url.startswith(("http://", "https://", "data:", "blob:")):
            return {"url": url, "name": name}
        return {"url": f"{public_base.rstrip('/')}/{url.lstrip('/')}", "name": name}

    async def _active_canvas(self) -> Optional[Dict[str, Any]]:
        """当前连接页的画布（infinite-canvas 无 smart/classic 之分，统一返回当前页）"""
        try:
            state = await self._get_state()
        except AdapterError:
            return None
        if not state.get("projectId"):
            return None
        return {
            "id": state["projectId"],
            "title": state.get("title") or "",
            "kind": "smart",
            "updated_at": int(time.time() * 1000),
            "deleted_at": None,
        }

    async def find_active_smart_canvas(self) -> Optional[Dict[str, Any]]:
        """当前连接页画布（端口语义对齐：infinite-canvas 无画布类型区分）"""
        return await self._active_canvas()

    async def find_active_canvas(self) -> Optional[Dict[str, Any]]:
        """当前连接页画布"""
        return await self._active_canvas()

    async def add_image_node(
        self,
        canvas_id: str,
        *,
        image: Dict[str, str],
        drop_point: Optional[Tuple[float, float]] = None,
        view_size: Optional[Tuple[float, float]] = None,
        canvas_kind: str = "smart",
    ) -> Dict[str, Any]:
        """在当前连接页可视区内 add_node 一个 image 节点（imageUrl 存 metadata.content）"""
        state = await self.get_canvas(canvas_id)
        wx, wy = _resolve_drop_point(state, drop_point, view_size)
        node_id = gen_id("image", wide=True)
        op = {
            "type": "add_node",
            "id": node_id,
            "nodeType": "image",
            "title": image.get("name") or "image",
            "position": {
                "x": round(wx - _IMAGE_NODE_SIZE / 2),
                "y": round(wy - _IMAGE_NODE_SIZE / 2),
            },
            "width": _IMAGE_NODE_SIZE,
            "height": _IMAGE_NODE_SIZE,
            "metadata": {
                INFINITE_CANVAS_IMAGE_MEDIA_FIELD: _absolutize_url(image["url"]),
                "status": "success",
            },
        }
        await self._apply_ops([op])
        self.invalidate_state_cache()
        logger.info(f"[InfiniteCanvas] 拖放图片已写入画布 {canvas_id}: node={node_id}")
        return {"node_id": node_id, "canvas_id": canvas_id, "canvas_title": state.get("title") or ""}

    # ---------- 生图任务 ----------

    async def submit_image_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """canvas_generate_image：创建生成流程并立即触发（异步，结果经 generation_get_status 查）"""
        tool_input: Dict[str, Any] = {"prompt": str(payload.get("prompt") or "")}
        for key in ("model", "size", "quality", "count"):
            if payload.get(key) is not None:
                tool_input[key] = payload[key]
        refs = payload.get("reference_node_ids") or payload.get("referenceNodeIds")
        if refs:
            tool_input["referenceNodeIds"] = [str(r) for r in refs]
        result = await self._call_tool("canvas_generate_image", tool_input)
        return result if isinstance(result, dict) else {"result": result}

    async def get_image_task(self, task_id: str) -> Dict[str, Any]:
        """generation_get_status 查询（taskId/节点 id 均可）"""
        data = await self._call_tool("generation_get_status", {"taskId": task_id})
        tasks = (data or {}).get("tasks", [])
        matched = next((t for t in tasks if t.get("id") == task_id), None) or (tasks[0] if tasks else None)
        if not matched:
            return {"status": "unknown", "task_id": task_id, "raw": data}
        return {**matched, "task_id": task_id}

    async def generate_image_online(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """同步在线生图：提交后轮询 generation_get_status 至终态（失败/超时抛 AdapterError）；
        提交的任务连续 _IMAGE_POLL_MAX_MISSES 轮未出现在返回中即早停抛错降级"""
        submit = await self.submit_image_task(payload)
        node_ids = _extract_generated_ids(submit)
        deadline = time.time() + settings.image_gen_timeout
        last: Dict[str, Any] = submit
        misses = 0
        while time.time() < deadline:
            await asyncio.sleep(_IMAGE_POLL_INTERVAL)
            query: Dict[str, Any] = {"scope": "canvas"}
            if node_ids:
                query["nodeIds"] = node_ids
            status = await self._call_tool("generation_get_status", query)
            last = status if isinstance(status, dict) else {"result": status}
            tasks = last.get("tasks", [])
            considered = [t for t in tasks if t.get("id") in set(node_ids)] if node_ids else tasks
            if not considered:
                if node_ids:
                    misses += 1
                    if misses >= _IMAGE_POLL_MAX_MISSES:
                        raise AdapterError(
                            f"infinite-canvas 在线生图任务丢失: 提交的 {node_ids} 连续 "
                            f"{misses} 轮未出现在 generation_get_status，早停降级",
                            retryable=True,
                        )
                continue
            misses = 0
            if any(t.get("status") == "failed" for t in considered):
                raise AdapterError(
                    f"infinite-canvas 在线生图失败: {json.dumps(considered, ensure_ascii=False)[:300]}"
                )
            if all(t.get("status") == "succeeded" for t in considered):
                return {"status": "succeeded", "tasks": considered, "raw": last}
        raise AdapterError(
            f"infinite-canvas 在线生图超时 ({settings.image_gen_timeout}s)", retryable=True
        )

    # ---------- 在线检测与版本漂移 ----------

    async def is_online(self) -> bool:
        """/health 在线且画布页已连接（hasCanvas）；“服务在线但画布页未开”经 health() 区分"""
        try:
            h = await self.health()
        except AdapterError:
            return False
        return bool(h.get("ok")) and bool(h.get("hasCanvas"))

    def online_cached(self) -> Optional[bool]:
        """最近一次 /health 探测的缓存结果（不触发网络请求）；None = 尚未探测过"""
        if self._health_cache is None:
            return None
        return bool(self._health_cache.get("ok")) and bool(self._health_cache.get("hasCanvas"))

    async def get_app_info(self) -> Dict[str, Any]:
        """GET /config → {version, protocolVersion, url}（version 为协议版本字符串）"""
        data = await self._get_json("/config")
        pv = data.get("protocolVersion")
        return {"version": str(pv), "protocolVersion": pv, "url": data.get("url") or self.base_url}

    async def check_version_drift(self) -> Optional[str]:
        """比对 /config protocolVersion 与上次记录，漂移时告警（离线/失败返回 None）"""
        try:
            info = await self.get_app_info()
        except Exception:
            return None  # 探测失败不阻塞启动
        version = str(info.get("version") or "").strip()
        if not version:
            return None
        recorded = _read_version_record()
        drift_msg: Optional[str] = None
        if recorded and recorded != version:
            drift_msg = (
                f"infinite-canvas canvas-agent 已更新: {recorded} → {version}（代码钉住协议 {PROTOCOL_VERSION}）。"
                "集成依赖其工具契约，请重新验证（运行 tests/integration infinite-canvas 契约测试）"
            )
            logger.warning(f"[InfiniteCanvas] {drift_msg}")
        if recorded != version:
            _write_version_record(version)
        return drift_msg


def _read_version_record() -> str:
    """读 data/canvas_integration.json 中 infinite_canvas 段的协议版本"""
    try:
        if _CANVAS_VERSION_FILE.exists():
            data = json.loads(_CANVAS_VERSION_FILE.read_text(encoding="utf-8"))
            return str(data.get("infinite_canvas", {}).get("protocol_version") or "")
    except Exception:
        pass
    return ""


def _write_version_record(version: str) -> None:
    """合并写（保留文件内其他段），失败仅 debug（不阻塞启动）"""
    try:
        data: Dict[str, Any] = {}
        if _CANVAS_VERSION_FILE.exists():
            try:
                data = json.loads(_CANVAS_VERSION_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        data["infinite_canvas"] = {"protocol_version": version, "checked_at": int(time.time())}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CANVAS_VERSION_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[InfiniteCanvas] 版本记录写入失败: {exc}")


# ---------- 模块级单例 ----------

_backend_instance: Optional["CanvasBackend"] = None


def get_infinite_canvas_backend() -> "CanvasBackend":
    """模块级单例（工厂 get_canvas_adapter 分发至此）"""
    global _backend_instance
    if _backend_instance is None:
        backend = InfiniteCanvasBackend()
        logger.debug(f"[InfiniteCanvas] 初始化: base_url={backend.base_url}")
        _backend_instance = backend
    return _backend_instance


def reset_infinite_canvas_backend() -> None:
    """重置单例（测试用，避免测试间缓存串味）"""
    global _backend_instance
    _backend_instance = None
