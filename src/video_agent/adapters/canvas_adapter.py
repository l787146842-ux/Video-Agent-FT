"""
CanvasAdapter — 熊布画布 HTTP API 封装（Rule4: 外部调用走 Adapter）。

所有对熊布画布服务的 HTTP 请求集中在此，Tool 层不直接出现 httpx 调用。
失败统一抛 AdapterError。
"""
import time
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError


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
        payload = {
            "title": title,
            "icon": icon,
            "nodes": nodes or [],
            "connections": connections or [],
            "viewport": viewport or {"x": 0, "y": 0, "scale": 1},
            "logs": logs or [],
            "settings": settings_dict or {},
            "client_id": "flova-agent",
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
    """重置单例（测试用）"""
    global _adapter_instance
    _adapter_instance = None
