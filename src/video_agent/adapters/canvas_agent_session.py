"""本项目内置画布会话：替代 canvas-agent Node 进程（L2）。

与对端 canvas-agent 协议兼容（AGENT_PROTOCOL_VERSION=6）：
- 画布页经 SSE 接收 tool_call，执行后 POST /canvas/result 回传；
- 本模块只做连接管理、快照缓存与「高层工具 → canvas_apply_ops」翻译；
- 画布数据仍在浏览器 IndexedDB，本模块不落盘、不解析产物内容。

单进程单 worker 假设（本项目单用户本地部署）；多 worker 各持一份连接会互相看不见。
"""
from __future__ import annotations

import asyncio
import secrets
import uuid
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.exceptions import AdapterError
from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import DATA_DIR

AGENT_PROTOCOL_VERSION = 6
TOOL_TIMEOUT_SECONDS = 30.0
_CONTENT_PREVIEW_CHARS = 120

def _load_or_create_token() -> str:
    """本机画布接入令牌：首次生成后落 data/（运行时目录，已 gitignore）。

    持久化的理由：画布页会把 endpoint/token 记进 localStorage，刷新画布页时
    不再走 hash 引导；token 若每次重启就变，刷新会 401 直到外层页面重新注入。
    """
    path = DATA_DIR / "canvas_agent_token"
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    try:
        atomic_write_text(path, token)
    except OSError as exc:
        logger.warning(f"[CanvasSession] 令牌落盘失败（本次进程内有效）: {exc}")
    return token


# 本机接入令牌：经 /api/config 下发前端，画布页据此建 SSE。
LOCAL_AGENT_TOKEN = _load_or_create_token()


def agent_token_authorized(token: str) -> bool:
    """画布页接入令牌校验（空 token 仅在未下发时放行本机调试）。"""
    return not token or token == LOCAL_AGENT_TOKEN

# 站点工具（由浏览器直接执行，服务端不做翻译）
_SITE_TOOLS = frozenset({
    "site_navigate",
    "canvas_list_projects",
    "generation_get_status",
    "workbench_image_get_config",
    "workbench_image_generate",
    "workbench_video_get_config",
    "workbench_video_generate",
    "prompts_search",
    "assets_list",
    "assets_add",
})

# 读类工具（直接读服务端缓存的画布快照，不下发浏览器）
_READ_TOOLS = frozenset({"canvas_get_state", "canvas_get_selection", "canvas_export_snapshot"})

_GENERATION_MODES = ("text", "image", "video", "audio")


class CanvasAgentSession:
    """管理画布页连接、快照缓存与工具调用的双向等待。"""

    def __init__(self) -> None:
        self._clients: Dict[str, asyncio.Queue] = {}
        self._states: Dict[str, Dict[str, Any]] = {}
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._active = ""
        self._bound = ""
        self._ever_connected = False

    # ---------- 连接生命周期 ----------

    def ever_connected(self) -> bool:
        """是否曾有画布页连过（区分“从未探测”与“连过又断开”）。"""
        return self._ever_connected

    def connect(self, client_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._clients[client_id] = queue
        self._ever_connected = True
        if not self._active:
            self._active = client_id
        logger.info(f"[CanvasSession] 画布页已连接: {client_id}（在线 {len(self._clients)}）")
        return queue

    def disconnect(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        self._states.pop(client_id, None)
        for request_id, item in list(self._pending.items()):
            if item["client_id"] != client_id:
                continue
            self._pending.pop(request_id, None)
            future = item["future"]
            if not future.done():
                future.set_exception(AdapterError("画布页面已断开，操作未完成"))
        if self._active == client_id:
            self._active = next(iter(self._clients), "")
        if self._bound == client_id:
            self._bound = ""
        logger.info(f"[CanvasSession] 画布页已断开: {client_id}（在线 {len(self._clients)}）")

    def activate(self, client_id: str) -> None:
        if client_id in self._clients:
            self._active = client_id

    def update_state(self, client_id: str, snapshot: Any) -> None:
        if client_id and client_id in self._clients and isinstance(snapshot, dict):
            self._states[client_id] = dict(snapshot)

    def resolve(self, client_id: str, body: Dict[str, Any]) -> bool:
        request_id = str(body.get("requestId") or "")
        item = self._pending.pop(request_id, None)
        if not item or item["client_id"] != client_id:
            return False
        future = item["future"]
        if future.done():
            return True
        error = body.get("error")
        if error:
            future.set_exception(AdapterError(f"画布工具执行失败: {error}"))
        else:
            future.set_result(body.get("result"))
        return True

    # ---------- 协议快照 ----------

    def _state(self) -> Optional[Dict[str, Any]]:
        return self._states.get(self._target_client_id)

    @property
    def _target_client_id(self) -> str:
        return self._bound or self._active

    def has_canvas(self) -> bool:
        return bool(self._clients) and self._state() is not None

    def hello(self, client_id: str) -> Dict[str, Any]:
        return {
            "ok": True,
            "protocolVersion": AGENT_PROTOCOL_VERSION,
            "clientId": client_id,
            "workspace": {"activeThreadId": ""},
            "conversation": {
                "revision": 1,
                "conversationId": client_id,
                "threadId": "",
                "status": "idle",
                "mcpStatuses": {},
            },
            "codex": {"busy": False, "threadId": "", "turnId": ""},
            "pendingApprovals": [],
        }

    def health(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "protocolVersion": AGENT_PROTOCOL_VERSION,
            "hasCanvas": self.has_canvas(),
            "clients": len(self._clients),
            "codexBusy": False,
        }

    # ---------- 工具调用 ----------

    async def call_tool(self, name: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        tool_input = dict(payload or {})
        if name in _READ_TOOLS:
            state = self._state()
            if state is None:
                raise AdapterError("当前没有已连接画布")
            if name == "canvas_get_selection":
                return _selection(state)
            return _compact_state(state)
        if name not in _SITE_TOOLS:
            name, tool_input = _build_request(name, tool_input, self._state())
        return await self._request(name, tool_input)

    async def _request(self, name: str, tool_input: Dict[str, Any]) -> Any:
        client_id = self._target_client_id
        queue = self._clients.get(client_id)
        if queue is None:
            raise AdapterError("当前没有已连接画布，请先打开画布页面")
        request_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = {"client_id": client_id, "future": future}
        queue.put_nowait(("tool_call", {"requestId": request_id, "name": name, "input": tool_input}))
        try:
            return await asyncio.wait_for(future, timeout=TOOL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise AdapterError("画布操作超时", retryable=True) from exc


# ---------- 快照压缩（对齐对端 compactNode：长正文只留预览） ----------


def _compact_node(node: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    content = metadata.get("content")
    if isinstance(content, str) and len(content) > _CONTENT_PREVIEW_CHARS * 2:
        metadata["content"] = f"{content[:_CONTENT_PREVIEW_CHARS]}..."
    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "title": node.get("title"),
        "position": node.get("position"),
        "width": node.get("width"),
        "height": node.get("height"),
        "metadata": metadata,
    }


def _compact_state(state: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(state)
    data["nodes"] = [_compact_node(node) for node in (state.get("nodes") or []) if isinstance(node, dict)]
    return data


def _selection(state: Dict[str, Any]) -> Dict[str, Any]:
    selected = set(state.get("selectedNodeIds") or [])
    nodes = [_compact_node(node) for node in (state.get("nodes") or [])
             if isinstance(node, dict) and node.get("id") in selected]
    return {"nodes": nodes}


# ---------- 高层工具 → canvas_apply_ops 翻译 ----------


def _ops(ops: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    return "canvas_apply_ops", {"ops": ops}


def _next_x(state: Optional[Dict[str, Any]]) -> float:
    nodes = (state or {}).get("nodes") or []
    if not nodes:
        return 0.0
    return max(float(n.get("position", {}).get("x", 0)) + float(n.get("width") or 0) for n in nodes) + 80


def _mode(value: Any) -> str:
    return value if value in _GENERATION_MODES else "image"


def _generation_title(mode: str) -> str:
    return {"text": "文本生成", "video": "视频生成", "audio": "音频生成"}.get(mode, "图片生成")


def _text_op(data: Dict[str, Any], x: float, y: float) -> Dict[str, Any]:
    return {
        "type": "add_node",
        "nodeType": "text",
        "title": data.get("title"),
        "position": {"x": x, "y": y},
        "width": data.get("width"),
        "height": data.get("height"),
        "metadata": {"content": data.get("text") or "", "status": "success", "fontSize": 14},
    }


def _config_op(node_id: str, data: Dict[str, Any], x: float, y: float) -> Dict[str, Any]:
    mode = _mode(data.get("mode"))
    prompt = str(data.get("prompt") or "")
    metadata = {
        "generationMode": mode,
        "composerContent": prompt,
        "prompt": prompt,
        "status": "idle",
    }
    for key in ("model", "size", "quality", "count", "seconds", "vquality", "generateAudio",
                "watermark", "videoMode", "audioVoice", "audioFormat", "audioSpeed", "audioInstructions"):
        if data.get(key) not in (None, ""):
            metadata[key] = data[key]
    return {
        "type": "add_node",
        "id": node_id,
        "nodeType": "config",
        "title": str(data.get("title") or _generation_title(mode)),
        "position": {"x": x, "y": y},
        "width": data.get("width") if isinstance(data.get("width"), (int, float)) else None,
        "height": data.get("height") if isinstance(data.get("height"), (int, float)) else None,
        "metadata": metadata,
    }


def _run_generation_op(node_id: str, mode: str, prompt: str) -> Dict[str, Any]:
    return {"type": "run_generation", "nodeId": node_id, "mode": mode, "prompt": prompt}


def _generation_flow(data: Dict[str, Any], state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mode = _mode(data.get("mode"))
    prompt = str(data.get("prompt") or "")
    x = float(data.get("x") if data.get("x") is not None else _next_x(state))
    y = float(data.get("y") or 0)
    text_id = f"text-{uuid.uuid4()}"
    config_id = f"config-{uuid.uuid4()}"
    references = [i for i in (data.get("referenceNodeIds") or []) if isinstance(i, str)]
    ops: List[Dict[str, Any]] = []
    ops.append(_text_op({"id": text_id, "text": prompt, "title": str(data.get("title") or "提示词")}, x, y))
    ops.append(_config_op(config_id, {**data, "prompt": prompt}, x + 420, y))
    ops.append({"type": "connect_nodes", "fromNodeId": text_id, "toNodeId": config_id})
    ops.extend({"type": "connect_nodes", "fromNodeId": ref, "toNodeId": config_id} for ref in references)
    ops.append({"type": "select_nodes", "ids": [config_id]})
    if data.get("autoRun"):
        ops.append(_run_generation_op(config_id, mode, prompt))
    return ops


def _build_request(
    name: str, data: Dict[str, Any], state: Optional[Dict[str, Any]]
) -> Tuple[str, Dict[str, Any]]:
    """把高层画布工具翻译为浏览器可直接执行的 canvas_apply_ops。"""
    if name == "canvas_apply_ops":
        return name, {"ops": list(data.get("ops") or [])}
    if name == "canvas_select_nodes":
        return _ops([{"type": "select_nodes", "ids": data.get("ids") or []}])
    if name == "canvas_group_nodes":
        return _ops([{"type": "group_nodes", "ids": data.get("ids") or []}])
    if name == "canvas_ungroup_nodes":
        return _ops([{"type": "ungroup_nodes", "ids": data.get("ids") or []}])
    if name == "canvas_create_node":
        node = {
            "type": "add_node",
            "nodeType": _mode(data.get("nodeType")) if data.get("nodeType") in ("image", "text", "config", "video", "audio") else data.get("nodeType"),
            "title": data.get("title"),
            "position": {"x": data.get("x", _next_x(state)), "y": data.get("y", 0)},
            "width": data.get("width"),
            "height": data.get("height"),
            "metadata": data.get("metadata"),
        }
        return _ops([node])
    if name == "canvas_create_text_node":
        return _ops([_text_op(data, float(data.get("x", _next_x(state))), float(data.get("y") or 0))])
    if name == "canvas_create_config_node":
        return _ops([_config_op(f"config-{uuid.uuid4()}", data,
                                float(data.get("x", _next_x(state))), float(data.get("y") or 0))])
    if name in ("canvas_create_image_prompt_flow", "canvas_create_generation_flow",
                "canvas_generate_image", "canvas_generate_text", "canvas_generate_video",
                "canvas_generate_audio"):
        mode = name.replace("canvas_generate_", "") if name.startswith("canvas_generate_") else data.get("mode")
        flow = {**data, "mode": "image" if name == "canvas_create_image_prompt_flow" else mode}
        if name.startswith("canvas_generate_"):
            flow["autoRun"] = True
        return _ops(_generation_flow(flow, state))
    if name == "canvas_update_node":
        return _ops([{"type": "update_node", "id": data.get("id"),
                      "patch": data.get("patch"), "metadata": data.get("metadata")}])
    if name == "canvas_delete_nodes":
        return _ops([{"type": "delete_node", "ids": data.get("ids") or []}])
    if name == "canvas_connect_nodes":
        connections = data.get("connections") or []
        return _ops([{"type": "connect_nodes", **c} for c in connections])
    if name == "canvas_set_viewport":
        return _ops([{"type": "set_viewport", "viewport": data.get("viewport")}])
    raise AdapterError(f"本项目未实现画布工具: {name}")


_session: Optional[CanvasAgentSession] = None


def get_canvas_agent_session() -> CanvasAgentSession:
    """进程内单例（连接与缓存都是进程级状态）。"""
    global _session
    if _session is None:
        _session = CanvasAgentSession()
    return _session
