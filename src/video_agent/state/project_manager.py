"""
ProjectManager — 多项目 CRUD（从 StateManager 拆分）。

职责：
- 项目列表查询
- 项目创建 / 切换 / 删除
- 项目索引维护

不包含状态读写逻辑，仅管理项目生命周期。
状态读写由 StateManager 协调。
"""
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.utils import gen_id

from .models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS
from .repository import StateRepository


class ProjectManager:
    """多项目管理器 — 负责项目 CRUD 与索引维护。

    通过回调与 StateManager 协作：
    - get_state(): 获取当前 raw state（用于保存当前项目）
    - set_state(state): 设置 raw state（切换/创建后）
    """

    def __init__(
        self,
        repo: StateRepository,
        get_state: Callable[[], Dict[str, Any]],
        set_state: Callable[[Dict[str, Any], str], None],
        flush_state: Optional[Callable[[], None]] = None,
    ):
        self._repo = repo
        self._get_state = get_state
        self._set_state = set_state  # (state_dict, project_id) -> None
        # 切换/新建前只冲刷挂起变更（8888 二轮：不得用内存全量状态回写，
        # 任务级隔离后本实例可能过期，全量回写会抹掉后台任务的新数据）
        self._flush_state = flush_state or (lambda: None)

    @property
    def active_project_id(self) -> str:
        """当前活跃项目 ID（从索引读取）"""
        index = self._repo.read_index()
        return index.get("active_project_id", "")

    def list_projects(self, active_id: str) -> Dict[str, Any]:
        """返回所有项目列表 + 当前活跃 ID"""
        index = self._repo.read_index()
        return {
            "active_project_id": active_id,
            "projects": index.get("projects", []),
        }

    def create_project(self, name: str, active_id: str) -> str:
        """新建项目：冲刷当前挂起变更 → 创建新项目 → 更新索引 → 返回 project_id"""
        # 冲刷当前项目挂起变更（不脏不写；8888 二轮：不再内存全量回写）
        if active_id:
            self._flush_state()

        project_id = gen_id("proj")
        # 新建项目不预建任何占位分组/欢迎消息：
        # 关键元素/分镜/音频全部为空，由 Agent 按任务拆解结果创建，
        # 避免每次执行任务还得先删一遍空占位组。
        new_state: Dict[str, Any] = {
            "project_id": project_id,
            "project_name": name,
            "status": "idle",
            CAT_KEY_ELEMENTS: [],
            CAT_SHOTS: [],
            CAT_AUDIO_ITEMS: [],
            "assets": [],
            "documents": [],
            "chatMessages": [],
        }

        # 持久化新项目
        self._repo.save_project(project_id, new_state)
        self._repo.save_compat(new_state)

        # 更新索引
        index = self._repo.read_index()
        index["active_project_id"] = project_id
        index.setdefault("projects", []).append({
            "id": project_id,
            "name": name,
            "created_at": StateRepository.now_iso(),
            "updated_at": StateRepository.now_iso(),
        })
        self._repo.write_index(index)

        # 通知 StateManager 切换内部状态
        self._set_state(new_state, project_id)

        logger.info(f"[ProjectManager] Created project: {name} ({project_id})")
        return project_id

    def switch_project(self, project_id: str, active_id: str) -> bool:
        """切换项目：冲刷当前挂起变更 → 加载目标 → 更新索引"""
        if project_id == active_id:
            return True

        # 冲刷当前项目挂起变更（不脏不写；8888 二轮：不再内存全量回写）
        if active_id:
            self._flush_state()

        # 加载目标
        loaded = self._repo.load_project(project_id)
        if loaded is None:
            return False

        # 更新兼容文件 + 索引
        self._repo.save_compat(loaded)
        index = self._repo.read_index()
        index["active_project_id"] = project_id
        self._repo.write_index(index)

        # 通知 StateManager
        self._set_state(loaded, project_id)

        logger.info(f"[ProjectManager] Switched to project: {project_id}")
        return True

    def delete_project(self, project_id: str, active_id: str) -> Optional[str]:
        """删除项目（硬删除）。

        返回：
        - None: 删除失败（仅剩一个项目）
        - str: 删除成功，返回新的 active_project_id（可能需要切换）
        """
        index = self._repo.read_index()
        projects = index.get("projects", [])
        if len(projects) <= 1:
            return None

        index["projects"] = [p for p in projects if p["id"] != project_id]

        new_active = active_id
        if active_id == project_id:
            new_active = index["projects"][0]["id"] if index["projects"] else ""
            index["active_project_id"] = new_active

        self._repo.write_index(index)
        self._repo.delete_project_dir(project_id)
        logger.info(f"[ProjectManager] Deleted project: {project_id}")
        return new_active
