"""
StateManager — Rule3: 唯一状态写入点。支持多项目。

设计方案 §1.3：
- 多项目管理内置于 StateManager（不另设 service 层）
- 内部视图（Pydantic，后端使用）+ 外部视图（camelCase JSON，前端使用）
- 点号路径 update() 统一写入入口

向后兼容：
- CLI 路径（agent.py）通过 .state 属性获取 Pydantic 模型
- Web 路径通过 .state_dict 获取 raw dict，供 Tool/Route 直接操作
"""
import asyncio
import json
import os
import random
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import WORKSPACE_DIR, DATA_DIR

from .models import ProjectState
from .models_pipeline import TaskStatus, AssetState, AssetStatus

# 默认工作区目录
DEFAULT_WORKSPACE_DIR = WORKSPACE_DIR

# 默认 demo 数据（首次启动时使用，从 data/demo_state.json 加载）
_DEMO_STATE_FILE = DATA_DIR / "demo_state.json"


def _load_default_state() -> Dict[str, Any]:
    if _DEMO_STATE_FILE.exists():
        try:
            return json.loads(_DEMO_STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[StateManager] Failed to load demo state: {e}")
    return {"project_id": "proj_001", "project_name": "Demo", "status": "idle",
            "keyElements": [], "shots": [], "audioItems": [], "assets": [], "chatMessages": []}


# ---------- 内部工具函数 ----------

def _set_path_dict(obj: Any, path: str, value: Any) -> None:
    """按点号路径设置 dict/list 元素（Web 路径用）。"""
    parts = path.split(".")
    current = obj
    for i, part in enumerate(parts[:-1]):
        if part.isdigit():
            idx = int(part)
            if isinstance(current, list):
                current = current[idx]
            else:
                current = current[int(part)]
        else:
            if isinstance(current, dict):
                current = current.setdefault(part, {})
            else:
                current = getattr(current, part, None)
                if current is None:
                    return
    last = parts[-1]
    if last.isdigit():
        idx = int(last)
        if isinstance(current, list):
            if idx == len(current):
                current.append(value)
            else:
                current[idx] = value
        else:
            current[last] = value
    else:
        if isinstance(current, dict):
            current[last] = value
        else:
            setattr(current, last, value)


def _set_path_pydantic(obj: Any, path: str, value: Any) -> None:
    """按点号路径设置 Pydantic 模型属性（CLI 路径用）。"""
    parts = path.split(".")
    current = obj
    for i, part in enumerate(parts[:-1]):
        if part.isdigit():
            idx = int(part)
            current = current[idx]
        else:
            current = getattr(current, part)
    last = parts[-1]
    if last.isdigit():
        idx = int(last)
        if idx == len(current):
            current.append(value)
        else:
            current[idx] = value
    else:
        setattr(current, last, value)


class StateManager:
    """Rule3: 唯一状态写入点。支持多项目。

    设计 §1.3：多项目管理内置于 StateManager，不另设 service 层。

    双视图：
    - state_dict → raw dict（Web Tool/Route 直接操作）
    - state → Pydantic ProjectState（CLI 路径，属性访问）

    多项目：
    - list_projects / create_project / switch_project / delete_project
    """

    # 单例（替代原 StudioStateService）
    _instance: Optional["StateManager"] = None

    @classmethod
    def get_instance(cls) -> "StateManager":
        """获取全局单例（替代原 StudioStateService.get_instance()）"""
        if cls._instance is None:
            cls._instance = cls(str(DEFAULT_WORKSPACE_DIR))
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（测试用）"""
        cls._instance = None

    # ====== 构造 & 加载 ======

    def __init__(self, workspace_dir: str):
        self._workspace_dir = Path(workspace_dir)
        self._projects_dir = self._workspace_dir / "projects"
        self._state_file = self._workspace_dir / "studio_state.json"  # 兼容旧版
        self._index_file = self._projects_dir / "index.json"

        # 供 async 路由在「变更 + 落盘」临界区使用
        self.lock = asyncio.Lock()

        # 内部状态：raw dict（Web 路径）
        self._raw_state: Dict[str, Any] = {}
        self._active_project_id: str = ""

        # Pydantic 视图缓存（脏标记优化，避免每次访问都 model_validate）
        self._cached_state: Optional[ProjectState] = None
        self._state_dirty: bool = True

        # 初始化
        self._load()

    def _load(self):
        """加载：优先从 projects/index.json 找活跃项目，否则迁移旧 studio_state.json"""
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._projects_dir.mkdir(parents=True, exist_ok=True)

        index = self._read_index()
        active_id = index.get("active_project_id", "")
        projects = index.get("projects", [])

        if active_id and projects:
            self._active_project_id = active_id
            if self._load_from_project_dir(active_id):
                logger.info(f"[StateManager] Loaded project: {active_id}")
                return

        # 迁移旧 studio_state.json
        if self._state_file.exists():
            try:
                old_state = json.loads(self._state_file.read_text(encoding="utf-8"))
                pid = old_state.get("project_id", f"proj-{int(time.time())}")
                pname = old_state.get("project_name", "迁移项目")
                self._raw_state = old_state
                self._active_project_id = pid
                self._save_to_project_dir(pid)
                self._write_index({
                    "active_project_id": pid,
                    "projects": [{"id": pid, "name": pname, "created_at": self._now_iso(), "updated_at": self._now_iso()}]
                })
                logger.info(f"[StateManager] Migrated legacy state to project: {pid}")
                return
            except Exception as e:
                logger.warning(f"[StateManager] Migration failed: {e}")

        # 全新初始化：创建 demo 项目
        self._raw_state = _load_default_state()
        self._active_project_id = self._raw_state.get("project_id", "proj_001")
        self._save_to_project_dir(self._active_project_id)
        self._write_index({
            "active_project_id": self._active_project_id,
            "projects": [{"id": self._active_project_id, "name": self._raw_state.get("project_name", "Demo"), "created_at": self._now_iso(), "updated_at": self._now_iso()}]
        })
        self._save_compat()
        logger.info("[StateManager] Initialized with default demo project")

    # ====== 双视图访问 ======

    @property
    def state(self) -> Optional[ProjectState]:
        """Pydantic 视图（CLI 路径向后兼容）。带脏标记缓存。"""
        if not self._raw_state:
            return None
        if not self._state_dirty and self._cached_state is not None:
            return self._cached_state
        try:
            self._cached_state = ProjectState.model_validate(self._raw_state)
        except Exception:
            minimal = {"project_id": self._raw_state.get("project_id", "unknown")}
            ps = ProjectState.model_validate(minimal)
            for k, v in self._raw_state.items():
                if not hasattr(ps, k):
                    setattr(ps, k, v)
            self._cached_state = ps
        self._state_dirty = False
        return self._cached_state

    @property
    def state_dict(self) -> Dict[str, Any]:
        """Raw dict 视图（Web Tool/Route 直接操作）。"""
        return self._raw_state

    @property
    def active_project_id(self) -> str:
        return self._active_project_id

    def get(self) -> ProjectState:
        """返回 Pydantic ProjectState（CLI 向后兼容）。"""
        s = self.state
        if s is None:
            raise ValueError("State is not initialized.")
        return s

    def to_frontend_dict(self) -> Dict[str, Any]:
        """返回前端使用的 camelCase JSON 视图（Pydantic 校验后序列化）。"""
        try:
            ps = ProjectState.model_validate(self._raw_state)
            return ps.model_dump(by_alias=True, mode="json")
        except Exception:
            return dict(self._raw_state)

    def get_full_snapshot(self) -> Dict[str, Any]:
        """返回完整状态快照（raw dict，供前端刷新）。"""
        return self._raw_state

    # ====== 写入（Rule3: 唯一写入点） ======

    def update(self, path: str, value: Any) -> None:
        """按点号路径更新状态并持久化（Rule3: 唯一写入点入口）。

        同时支持 dict 路径（Web）和 Pydantic 属性路径（CLI）。
        """
        _set_path_dict(self._raw_state, path, value)
        self._state_dirty = True
        self.save()

    def save(self) -> None:
        """持久化：写入当前项目目录 + 兼容文件 + 更新 index 时间戳"""
        try:
            self._save_to_project_dir(self._active_project_id)
            self._save_compat()
            index = self._read_index()
            for p in index.get("projects", []):
                if p["id"] == self._active_project_id:
                    p["updated_at"] = self._now_iso()
                    break
            self._write_index(index)
            logger.debug("[StateManager] Saved")
        except Exception as e:
            logger.error(f"[StateManager] Save failed: {e}")

    # 向后兼容别名
    save_state = save

    def initialize_project(self, project_id: str, user_goal: str, project_name: str = "New Project") -> ProjectState:
        """初始化一个空项目（CLI 路径向后兼容）。"""
        self._raw_state = {
            "project_id": project_id,
            "project_name": project_name,
            "status": "idle",
            "user_goal": user_goal,
            "keyElements": [],
            "shots": [],
            "audioItems": [],
            "assets": [],
            "documents": [],
            "chatMessages": [],
        }
        self._active_project_id = project_id
        self.save()
        return self.get()

    # ====== 多项目管理 ======

    def list_projects(self) -> Dict[str, Any]:
        """返回所有项目列表 + 当前活跃 ID"""
        index = self._read_index()
        return {
            "active_project_id": self._active_project_id,
            "projects": index.get("projects", []),
        }

    def create_project(self, name: str) -> str:
        """新建项目：保存当前 → 创建新项目 → 切换 → 返回 project_id"""
        if self._active_project_id:
            self._save_to_project_dir(self._active_project_id)

        project_id = f"proj-{int(time.time())}-{random.randint(100, 999)}"
        self._raw_state = {
            "project_id": project_id,
            "project_name": name,
            "status": "idle",
            "keyElements": [],
            "shots": [],
            "audioItems": [],
            "assets": [],
            "documents": [],
            "chatMessages": [
                {
                    "sender": "agent",
                    "text": f"你好！我是你的 AI 编剧与导演助手。项目《{name}》已创建，告诉我你的创意目标，我来帮你规划关键元素、分镜和音频层！",
                }
            ],
        }
        self._active_project_id = project_id
        self._save_to_project_dir(project_id)
        self._save_compat()

        index = self._read_index()
        index["active_project_id"] = project_id
        index.setdefault("projects", []).append({
            "id": project_id,
            "name": name,
            "created_at": self._now_iso(),
            "updated_at": self._now_iso(),
        })
        self._write_index(index)
        logger.info(f"[StateManager] Created project: {name} ({project_id})")
        return project_id

    def switch_project(self, project_id: str) -> bool:
        """切换项目：保存当前 → 加载目标"""
        if project_id == self._active_project_id:
            return True
        if self._active_project_id:
            self._save_to_project_dir(self._active_project_id)
        if not self._load_from_project_dir(project_id):
            return False
        self._active_project_id = project_id
        self._save_compat()
        index = self._read_index()
        index["active_project_id"] = project_id
        self._write_index(index)
        logger.info(f"[StateManager] Switched to project: {project_id}")
        return True

    def delete_project(self, project_id: str) -> bool:
        """删除项目（硬删除）"""
        index = self._read_index()
        projects = index.get("projects", [])
        if len(projects) <= 1:
            return False
        index["projects"] = [p for p in projects if p["id"] != project_id]
        if self._active_project_id == project_id:
            new_active = index["projects"][0]["id"] if index["projects"] else ""
            index["active_project_id"] = new_active
            self._write_index(index)
            self.switch_project(new_active)
        else:
            self._write_index(index)
        pdir = self._projects_dir / project_id
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)
        logger.info(f"[StateManager] Deleted project: {project_id}")
        return True

    def reset(self, project_name: str = "未命名项目", project_id: str = ""):
        """兼容旧接口：内部调用 create_project"""
        self.create_project(project_name)

    # ====== 查询辅助（Web 路由用） ======

    def get_groups(self) -> Dict[str, List[Dict]]:
        return {
            "keyElements": self._raw_state.get("keyElements", []),
            "shots": self._raw_state.get("shots", []),
            "audioItems": self._raw_state.get("audioItems", []),
        }

    def get_assets(self) -> List[Dict]:
        return self._raw_state.get("assets", [])

    def get_chat_messages(self) -> List[Dict]:
        return self._raw_state.get("chatMessages", [])

    def add_chat_message(self, sender: str, text: str):
        self._raw_state.setdefault("chatMessages", []).append({"sender": sender, "text": text})
        self.save()

    def build_agent_context(self, asset_mode: str = "bound") -> str:
        """构建发送给 LLM 的 Studio 状态上下文"""
        assets = self._raw_state.get("assets", [])
        if asset_mode != "all":
            assets = [a for a in assets if a.get("isBound")]

        snapshot = {
            "keyElements": [
                {
                    "id": g["id"],
                    "title": g.get("title", ""),
                    "desc": g.get("desc", ""),
                    "drafts": [
                        {
                            "id": d["id"],
                            "label": d.get("label", ""),
                            "tag": d.get("tag", ""),
                            "mediaType": d.get("mediaType", ""),
                            "prompt": d.get("prompt", ""),
                            "model": d.get("model", ""),
                            "imgUrl": (d.get("imgUrl", "") or "")[:200],
                        }
                        for d in g.get("drafts", [])
                    ],
                }
                for g in self._raw_state.get("keyElements", [])
            ],
            "shots": [
                {
                    "id": g["id"],
                    "title": g.get("title", ""),
                    "duration": g.get("duration", ""),
                    "shotType": g.get("shotType", ""),
                    "sceneRefs": g.get("sceneRefs", []),
                    "roughDesc": g.get("roughDesc", ""),
                    "drafts": [
                        {
                            "id": d["id"],
                            "label": d.get("label", ""),
                            "tag": d.get("tag", ""),
                            "prompt": d.get("prompt", ""),
                            "model": d.get("model", ""),
                            "mode": d.get("mode", ""),
                        }
                        for d in g.get("drafts", [])
                    ],
                }
                for g in self._raw_state.get("shots", [])
            ],
            "audioItems": [
                {
                    "id": g["id"],
                    "title": g.get("title", ""),
                    "timeRange": g.get("timeRange", ""),
                    "prompt": g.get("prompt", ""),
                    "drafts": [
                        {
                            "id": d["id"],
                            "label": d.get("label", ""),
                            "prompt": d.get("prompt", ""),
                            "model": d.get("model", ""),
                        }
                        for d in g.get("drafts", [])
                    ],
                }
                for g in self._raw_state.get("audioItems", [])
            ],
            "assets": [
                {"id": a["id"], "name": a.get("name", ""), "type": a.get("type", ""), "isBound": a.get("isBound", False)}
                for a in assets
            ],
            "documents": [
                {
                    "name": d.get("name", ""),
                    "updated_at": d.get("updated_at", ""),
                    "content": (d.get("content", "") or "")[:4000],
                }
                for d in self._raw_state.get("documents", [])
            ],
        }
        return json.dumps(snapshot, ensure_ascii=False, indent=2)

    # ====== CLI 路径向后兼容 ======

    def update_task_status(self, task_id: str, status: TaskStatus, output_asset_id: Optional[str] = None, error: Optional[str] = None):
        """CLI 路径：更新任务状态"""
        ps = self.state
        if not ps:
            return
        for task in ps.tasks:
            if task.task_id == task_id:
                task.status = status
                if status == TaskStatus.completed:
                    task.completed_at = datetime.now(timezone.utc)
                if output_asset_id:
                    task.output.asset_id = output_asset_id
                if error:
                    task.error = error
                # 回写到 raw dict
                self._raw_state["tasks"] = [t.model_dump(by_alias=True, mode="json") for t in ps.tasks]
                self.save()
                return
        logger.warning(f"Task {task_id} not found.")

    def add_asset(self, asset: AssetState):
        """CLI 路径：添加管线资产"""
        ps = self.state
        if not ps:
            return
        for i, a in enumerate(ps.pipeline_assets):
            if a.asset_id == asset.asset_id:
                ps.pipeline_assets[i] = asset
                self._raw_state["pipeline_assets"] = [a.model_dump(by_alias=True, mode="json") for a in ps.pipeline_assets]
                self.save()
                return
        ps.pipeline_assets.append(asset)
        self._raw_state["pipeline_assets"] = [a.model_dump(by_alias=True, mode="json") for a in ps.pipeline_assets]
        self.save()

    def update_asset_status(self, asset_id: str, status: AssetStatus, file_path: Optional[str] = None):
        """CLI 路径：更新管线资产状态"""
        ps = self.state
        if not ps:
            return
        for asset in ps.pipeline_assets:
            if asset.asset_id == asset_id:
                asset.status = status
                if file_path:
                    asset.file_path = file_path
                self._raw_state["pipeline_assets"] = [a.model_dump(by_alias=True, mode="json") for a in ps.pipeline_assets]
                self.save()
                return
        logger.warning(f"Asset {asset_id} not found.")

    # ====== 内部持久化 ======

    def _read_index(self) -> Dict[str, Any]:
        if self._index_file.exists():
            try:
                return json.loads(self._index_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[StateManager] Failed to read index: {e}")
        return {"active_project_id": "", "projects": []}

    def _write_index(self, index: Dict[str, Any]):
        atomic_write_text(self._index_file, json.dumps(index, ensure_ascii=False, indent=2))

    def _now_iso(self) -> str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def _save_to_project_dir(self, project_id: str):
        pdir = self._projects_dir / project_id
        pdir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(pdir / "state.json", json.dumps(self._raw_state, ensure_ascii=False, indent=2))

    def _load_from_project_dir(self, project_id: str) -> bool:
        sfile = self._projects_dir / project_id / "state.json"
        if not sfile.exists():
            return False
        try:
            self._raw_state = json.loads(sfile.read_text(encoding="utf-8"))
            return True
        except Exception as e:
            logger.warning(f"[StateManager] Failed to load project {project_id}: {e}")
            return False

    def _save_compat(self):
        try:
            atomic_write_text(self._state_file, json.dumps(self._raw_state, ensure_ascii=False, indent=2))
        except Exception:
            pass
