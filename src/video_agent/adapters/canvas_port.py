"""CanvasBackend — 画布后端端口（Protocol）。

画布领域语义的端口定义：上游（Tool 层 / 路由层）只依赖本端口，
不感知具体实现（当前唯一实现 = infinite-canvas）。
方法签名为画布领域操作闭集；新增后端实现须满足本端口。
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple


class CanvasBackend(Protocol):
    """画布后端端口：画布 CRUD / 素材 / 拖放 / 生图 / 健康探测等领域操作。"""

    # ---------- 画布 CRUD ----------

    async def list_canvases(self) -> List[Dict[str, Any]]:
        """获取画布列表"""
        ...

    async def get_canvas(self, canvas_id: str) -> Dict[str, Any]:
        """获取画布完整数据（含 nodes/connections/viewport）"""
        ...

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
        """全量写回画布（乐观锁冲突时自动 re-read + re-apply）"""
        ...

    async def create_canvas(
        self, title: str = "未命名画布", kind: str = "smart", icon: str = "sparkles"
    ) -> Dict[str, Any]:
        """新建画布"""
        ...

    # ---------- 节点级写（工具层读-改-写语义的差异实现） ----------
    # 实现：增量 canvas_apply_ops 直发（无整板读改写）。
    # 节点字典均为工具层语义形状（tools/canvas_tools._build_node_dict 产物）。

    async def add_node(self, canvas_id: str, *, node: Dict[str, Any]) -> Dict[str, Any]:
        """追加单个节点（须带 id）。返回 {"node_id", "canvas_id"}"""
        ...

    async def update_node(
        self, canvas_id: str, *, node_id: str, patch: Dict[str, Any]
    ) -> bool:
        """修改指定节点属性（patch 键：title/x/y/prompt/image_url/content，仅非 None 生效）。
        返回节点是否存在并已更新。"""
        ...

    async def delete_node(self, canvas_id: str, *, node_id: str) -> bool:
        """删除指定节点（同时清理相关连线）。返回节点是否存在。"""
        ...

    async def add_nodes_batch(
        self, canvas_id: str, *, nodes: List[Dict[str, Any]]
    ) -> List[str]:
        """批量追加节点（一次批量 ops 提交）。返回新节点 id 列表。"""
        ...

    # ---------- 选中态 ----------

    async def get_selection(self) -> Dict[str, Any]:
        """读取当前画布选中节点。
        返回 {"supported": bool, "nodes": [...]}；后端无选中态读能力时
        返回空选中并标注 supported=False。"""
        ...

    async def select_nodes(self, node_ids: List[str]) -> Dict[str, Any]:
        """反向联动：设置画布当前选中节点。
        返回 {"supported": bool, "selected": int}；后端无选中态写能力时
        返回 supported=False 且不抛错。"""
        ...

    # ---------- 素材库 ----------

    async def list_assets(self) -> Any:
        """获取画布素材索引"""
        ...

    async def upload_files(self, files: List[Tuple[str, bytes, str]]) -> List[Dict[str, Any]]:
        """上传文件到画布素材库。

        files: [(filename, content, mime)]，返回 [{url, name, kind, mime?}]。
        """
        ...

    async def list_asset_library(self) -> Any:
        """获取画布素材库管理系统完整数据（libraries/categories/items）"""
        ...

    async def list_local_assets(self) -> Any:
        """获取画布本地上传素材列表"""
        ...

    # ---------- 拖放图片节点（对话栏图片拖入画布） ----------

    async def prepare_drop_image(
        self,
        *,
        url: str,
        name: str,
        local_path: Optional[Path],
        mime: str,
        public_base: str,
    ) -> Dict[str, str]:
        """物化拖放图片引用：返回 {"url", "name"}。

        实现：节点直接引用本站绝对 URL，无二次上传（画布站点经 Agent 静态端点回源）。
        local_path: 本站素材绝对路径（非本站素材为 None）；
        public_base: 本 Agent 服务对浏览器可见基址（绝对化用）。
        """
        ...

    async def find_active_smart_canvas(self) -> Optional[Dict[str, Any]]:
        """推断当前活跃的智能画布（无命中返回 None）"""
        ...

    async def find_active_canvas(self) -> Optional[Dict[str, Any]]:
        """推断当前活跃画布（不限类型，无命中返回 None）"""
        ...

    async def add_image_node(
        self,
        canvas_id: str,
        *,
        image: Dict[str, str],
        drop_point: Optional[Tuple[float, float]] = None,
        view_size: Optional[Tuple[float, float]] = None,
        canvas_kind: str = "smart",
    ) -> Dict[str, Any]:
        """在画布可视区内追加一个图片节点并写回。

        image: {"url": ..., "name": ..., "kind": "image"}；
        drop_point: 落点在画布 iframe 内的屏幕坐标 (x, y)，缺省时放到视口中心；
        view_size: 画布 iframe 可视尺寸 (w, h)，用于把落点换算成世界坐标。
        返回 {"node_id", "canvas_id", "canvas_title"}。
        """
        ...

    # ---------- 生图任务 ----------

    async def submit_image_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """提交异步生图任务"""
        ...

    async def get_image_task(self, task_id: str) -> Dict[str, Any]:
        """查询生图任务状态"""
        ...

    async def generate_image_online(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """同步在线生图（失败抛 AdapterError）"""
        ...

    # ---------- 在线检测与版本漂移 ----------

    async def is_online(self) -> bool:
        """检测画布是否在线"""
        ...

    async def get_app_info(self) -> Dict[str, Any]:
        """读取画布应用信息（含 version 字段）"""
        ...

    async def check_version_drift(self) -> Optional[str]:
        """比对画布版本与上次记录，漂移时返回告警信息（无漂移/离线返回 None）"""
        ...
