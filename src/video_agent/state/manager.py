"""
StateManager — Rule3: 唯一状态写入点。支持多项目。

设计方案 §1.3：
- 多项目管理内置于 StateManager（不另设 service 层）
- 内部视图（Pydantic，后端使用）+ 外部视图（camelCase JSON，前端使用）
- 点号路径 update 统一写入入口

向后兼容：
- CLI 路径（agent.py）通过 .state 属性获取 Pydantic 模型
- Web 路径通过 .state_dict 获取 raw dict，供 Tool/Route 直接操作

实现拆分：对话域/落盘闸/快照组装实现体分别切出至
conversation_ops / save_ops / context_builder；本文件保留 StateManager 类本体
与承重壳委托（壳清单登记于 coupling_registry R13），公开 API 零变化。
方法壳为 StateManager 公开 API 门面，长期承重；
测试 monkeypatch 目标应为壳方法（调用方经实例方法查找）。
"""
import asyncio
import copy
import json
import time
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.utils.paths import WORKSPACE_DIR, DATA_DIR
from src.video_agent.exceptions import StateError

from .models import ProjectState, CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS
from .models_pipeline import TaskStatus, AssetState, AssetStatus
from .repository import StateRepository
from .repository_sqlite import SqliteStateRepository
from .project_manager import ProjectManager
from .context_builder import (
    build_agent_context as _build_context,
    build_frontend_view as _build_frontend_view,
    build_full_snapshot as _build_full_snapshot,
)
from .undo_redo import UndoRedoMixin
from . import chat_tail_ops, conversation_ops, save_ops

# 后台 Agent 任务的按任务隔离实例：worker 上下文内 get_instance
# 返回任务专属 StateManager，切项目/刷新不串写。
_task_state_var: ContextVar[Optional["StateManager"]] = ContextVar(
    "agent_task_state", default=None,
)

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
            CAT_KEY_ELEMENTS: [], CAT_SHOTS: [], CAT_AUDIO_ITEMS: [], "assets": [], "chatMessages": []}


# ---------- 内部工具函数 ----------

def _set_path_dict(obj: Any, path: str, value: Any) -> None:
    """按点号路径设置 dict/list 元素（纯 dict 路径；非 dict/list 中间节点
    显式报错而非静默 setattr）。"""
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
                raise StateError(f"update() 路径 '{path}' 中间节点非 dict/list：{type(current).__name__}")
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
            raise StateError(f"update() 路径 '{path}' 末端节点非 dict/list：{type(current).__name__}")


class StateManager(UndoRedoMixin):
    """Rule3: 唯一状态写入点。支持多项目。

    版本账本：`_board_versions` 类级共享（同项目所有实例同一本账），
    随项目文件落盘，进程重启后从落盘值继承，不断号。

    设计 §1.3：多项目管理内置于 StateManager，不另设 service 层。

    双视图：
    - state_dict → raw dict（Web Tool/Route 直接操作）
    - state → Pydantic ProjectState（CLI 路径，属性访问）

    多项目：
    - list_projects / create_project / switch_project / delete_project
    """

    _board_versions: Dict[str, int] = {}

    # 单例
    _instance: Optional["StateManager"] = None

    @classmethod
    def get_instance(cls) -> "StateManager":
        """获取状态管理器：后台任务上下文内返回任务专属实例，其余返回全局单例。"""
        bound = _task_state_var.get()
        if bound is not None:
            return bound
        if cls._instance is None:
            cls._instance = cls(str(DEFAULT_WORKSPACE_DIR))
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（测试用）"""
        cls._instance = None

    @classmethod
    def create_task_bound(
        cls, project_id: str, workspace_dir: str = str(DEFAULT_WORKSPACE_DIR),
    ) -> "tuple[StateManager, Token]":
        """为后台 Agent 任务创建专属实例并绑定到当前 context（任务级隔离）。

        任务提交时锁定所属项目：即使之后用户切换项目/刷新页面，
        worker 内所有 StateManager.get_instance 都命中本实例，不串写。
        """
        svc = cls(workspace_dir)
        if svc.active_project_id != project_id:
            svc.switch_project(project_id)
        token = _task_state_var.set(svc)
        return svc, token

    @staticmethod
    def release_task_bound(token: Token) -> None:
        """解除任务上下文绑定（worker finally 调用）。"""
        _task_state_var.reset(token)

    # ====== 构造 & 加载 ======

    def __init__(self, workspace_dir: str):
        self._workspace_dir = Path(workspace_dir)
        self._repo = self._build_repo(self._workspace_dir)

        # 供 async 路由在「变更 + 落盘」临界区使用
        self.lock = asyncio.Lock()

        # 内部状态：raw dict（Web 路径）
        self._raw_state: Dict[str, Any] = {}
        self._active_project_id: str = ""

        # Pydantic 视图缓存（脏标记优化，避免每次访问都 model_validate）
        self._cached_state: Optional[ProjectState] = None
        self._state_dirty: bool = True

        # Agent 上下文缓存（状态未变时复用，避免重复构建 JSON）
        self._context_cache: Dict[str, str] = {}

        # Undo/Redo（继承自 UndoRedoMixin）
        self._init_undo_redo(max_undo=20)

        # 防抖落盘状态（save_debounced 用）
        self._save_dirty = False
        self._save_flush_task: Optional[asyncio.Task] = None

        # 本实例已知的项目落盘版本号（版本闸：磁盘账本比它新
        # 说明别的实例写过更新数据，本实例的保存必须放弃，防旧盖新）
        self._known_version: Optional[int] = None

        # 多项目管理器（委托）
        self._project_mgr = ProjectManager(
            repo=self._repo,
            get_state=lambda: self._raw_state,
            set_state=self._on_project_switch,
            flush_state=self.flush_save,
        )

        # 初始化
        self._load()

    @staticmethod
    def _build_repo(workspace_dir: Path):
        """按 settings.state_backend 选择状态仓库（sqlite 默认 / json 回落，可回退）。"""
        from src.video_agent.config import settings
        backend = (settings.state_backend or "json").strip().lower()
        if backend == "sqlite":
            logger.info("[StateManager] 状态后端：SQLite（首次启用自动从 JSON 迁移）")
            return SqliteStateRepository(workspace_dir)
        return StateRepository(workspace_dir)

    def _on_project_switch(self, state: Dict[str, Any], project_id: str) -> None:
        """ProjectManager 回调：切换内部状态"""
        self._raw_state = state
        self._active_project_id = project_id
        self._known_version = self._disk_board_version(project_id)
        self._state_dirty = True
        self._context_cache.clear()
        # 切换项目时清空 undo/redo 栈
        self._clear_undo_redo()
        # 多对话不变式：chatMessages 始终指向活跃对话的消息列表
        self._ensure_conversations()

    def _load(self):
        """加载：优先从索引找活跃项目，否则迁移旧 studio_state.json。

        读写均经 self._repo 接口（sqlite 后端下索引/项目体都在
        state.sqlite3）。
        """
        self._repo.ensure_dirs()

        index = self._repo.read_index()
        active_id = index.get("active_project_id", "")
        projects = index.get("projects", [])

        if active_id and projects:
            self._active_project_id = active_id
            loaded = self._repo.load_project(active_id)
            if loaded is not None:
                self._raw_state = loaded
                self._known_version = self._disk_board_version(active_id)
                self._ensure_conversations()
                logger.info(f"[StateManager] Loaded project: {active_id}")
                return

        # 迁移旧 studio_state.json
        old_state = self._repo.load_compat()
        if old_state:
            try:
                pid = old_state.get("project_id", f"proj-{int(time.time())}")
                pname = old_state.get("project_name", "迁移项目")
                self._raw_state = old_state
                self._active_project_id = pid
                self._ensure_conversations()
                self._repo.save_project(pid, self._raw_state)
                self._repo.write_index({
                    "active_project_id": pid,
                    "projects": [{"id": pid, "name": pname, "created_at": StateRepository.now_iso(), "updated_at": StateRepository.now_iso()}]
                })
                logger.info(f"[StateManager] Migrated legacy state to project: {pid}")
                return
            except Exception as e:
                logger.warning(f"[StateManager] Migration failed: {e}")

        # 全新初始化：创建 demo 项目
        self._raw_state = _load_default_state()
        self._active_project_id = self._raw_state.get("project_id", "proj_001")
        self._ensure_conversations()
        self._repo.save_project(self._active_project_id, self._raw_state)
        self._repo.write_index({
            "active_project_id": self._active_project_id,
            "projects": [{"id": self._active_project_id, "name": self._raw_state.get("project_name", "Demo"), "created_at": StateRepository.now_iso(), "updated_at": StateRepository.now_iso()}]
        })
        self._repo.save_compat(self._raw_state)
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
                    try:
                        setattr(ps, k, v)
                    except (ValueError, TypeError):
                        # extra="ignore" 模型拒绝未知字段（pydantic 抛 ValueError）：
                        # 静默跳过，降级视图仅用于 CLI 兼容，不影响 raw dict 主路径
                        continue
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
        """返回前端使用的 camelCase JSON 视图（实现见 context_builder.build_frontend_view）。"""
        return _build_frontend_view(self._raw_state)

    def get_full_snapshot(self) -> Dict[str, Any]:
        """返回完整状态快照（供前端刷新/SSE done payload）：
        契约与实现见 context_builder.build_full_snapshot（深拷贝，调用方可任意使用）。"""
        return _build_full_snapshot(self._raw_state, self.board_version)

    # ====== 批级检查点（批 6：条件回滚的快照/恢复公开 API） ======

    def snapshot_state(self) -> Dict[str, Any]:
        """整态深拷贝快照（批级检查点用；参考 _push_undo 的 deepcopy 先例）。

        与 get_full_snapshot 的前端视图快照不同：不做 json round-trip/
        不附加 board_version/不裁剪对话消息，恢复时可原样写回。"""
        return copy.deepcopy(self._raw_state)

    def restore_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        """把整态恢复到快照时刻（批级条件回滚的唯一写面，Rule 3）。

        经 StateManager 自身受控写面写回：当前态先压 undo 栈留痕
        （恢复本身可被 undo 复核）、落盘持久化、重建多对话不变式。
        禁止绕开本方法对 state_dict 做 clear()/update() 直接字典改法。
        """
        self._push_undo()
        self._raw_state = copy.deepcopy(snapshot)
        self._state_dirty = True
        self._context_cache.clear()
        self._ensure_conversations()
        return self.save()

    # ====== 写入（Rule3: 唯一写入点） ======

    def update(self, path: str, value: Any) -> None:
        """按点号路径更新状态并持久化（Rule3: 唯一写入点入口）。

        同时支持 dict 路径（Web）和 Pydantic 属性路径（CLI）。
        落盘走防抖合并：避免高频路径同步全量写盘阻塞事件循环；
        无运行中事件循环时（CLI/同步测试）退化为立即同步落盘，
        项目切换/服务关闭前由 flush_save 保证持久性。
        """
        self._push_undo()
        _set_path_dict(self._raw_state, path, value)
        self._state_dirty = True
        self.save_debounced()

    def record_used_skill(self, slug: str) -> None:
        """记录用户随消息发送给 Agent 的 Skill（按项目持久化）。

        文档面板只展示已发送过的 Skill 文档：新建项目 usedSkills 为空，
        只有 Skill 引用块随消息发出后才写入，模型据此记住流程规则。
        不走 update（避免污染 undo 栈）。
        """
        if not slug:
            return
        used = self._raw_state.setdefault("usedSkills", [])
        if slug not in used:
            used.append(slug)
            self.save()

    def set_active_skill(self, slug: str, source: str = "user") -> None:
        """写入项目态当前活跃 Skill 绑定（批 C：激活语义归项目态）。

        slug 为空串 = 显式自由对话（摘除）；source 记激活来源（用户选择/
        建议采纳）。与 usedSkills 同属项目事实（随完整快照下发前端），
        不走 update（避免污染 undo 栈）。
        """
        self._raw_state["activeSkill"] = {
            "slug": str(slug or ""),
            "source": "suggested" if source == "suggested" else "user",
        }
        self.save()

    def set_style_skills(self, slugs: List[str]) -> None:
        """写入项目态叠加风格层清单（任务 #11：1 pipeline 可选 + N style 层）。

        只存清洗后的 slug 清单（去重保序由调用方/消费方清洗保障，
        此处原样落盘）；空清单 = 摘除全部风格层。与 activeSkill/usedSkills
        同属项目事实（随完整快照下发前端），不走 update（避免污染 undo 栈）。"""
        self._raw_state["styleSkills"] = [str(s) for s in (slugs or [])]
        self.save()

    def record_flow_event(self, kind: str, detail: str) -> None:
        """记录一条流程事件（截断/部分完成等事实进账本）。

        只写 raw state 的 flowEvents 列表（chat_service 用 get_full_snapshot
        构建模型可见状态 JSON，模型下个轮次能直接看到「上次只完成一半」），
        不走 update（避免污染 undo 栈）。
        """
        events = self._raw_state.get("flowEvents")
        if not isinstance(events, list):
            events = []
            self._raw_state["flowEvents"] = events
        events.append({
            "kind": kind,
            "detail": detail,
            "text": detail,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        self._state_dirty = True
        self._context_cache.clear()

    def clear_flow_events(self, prefix: str = "") -> None:
        """按 kind 前缀清除流程事件（全部完成/未截断时消解历史记录）。"""
        events = self._raw_state.get("flowEvents")
        if not isinstance(events, list):
            return
        if not prefix:
            self._raw_state["flowEvents"] = []
            self._context_cache.clear()
            return
        kept = [e for e in events if not str(e.get("kind") or "").startswith(prefix)]
        if len(kept) != len(events):
            self._raw_state["flowEvents"] = kept
            self._state_dirty = True
            self._context_cache.clear()

    def save(self) -> bool:
        """持久化（版本账本闸主通路）：契约与实现见 save_ops.save。

        返回是否真正落盘：版本闸放弃写入时返回 False（调用方据此判冲突，
        破坏性写入路径不得静默放行）。
        """
        return save_ops.save(self)

    def _disk_board_version(self, project_id: str) -> int:
        """索引落盘的项目版本号（实现见 save_ops.disk_board_version）。"""
        return save_ops.disk_board_version(self, project_id)

    def reload_if_stale(self) -> bool:
        """磁盘账本新于本实例已知号时从磁盘重载（实现见 save_ops.reload_if_stale）。"""
        return save_ops.reload_if_stale(self)

    @property
    def board_version(self) -> int:
        """当前项目版本号（同项目所有实例共享一本账；实现见 save_ops.board_version）。"""
        return save_ops.board_version(self)

    async def save_async(self) -> bool:
        """异步立即落盘：写盘移 worker 线程（实现见 save_ops.save_async）。"""
        return await save_ops.save_async(self)

    def save_debounced(self) -> None:
        """防抖落盘：合并短窗口变更统一写一次盘（实现见 save_ops.save_debounced）。"""
        save_ops.save_debounced(self)

    def flush_save(self) -> None:
        """立即冲刷防抖落盘的挂起变更（实现见 save_ops.flush_save）。"""
        save_ops.flush_save(self)

    def initialize_project(self, project_id: str, user_goal: str, project_name: str = "New Project") -> ProjectState:
        """初始化一个空项目（CLI 路径向后兼容）。"""
        # 多对话结构：既有聊天记录迁入首个对话
        self._raw_state = {
            "project_id": project_id,
            "project_name": project_name,
            "status": "idle",
            "user_goal": user_goal,
            CAT_KEY_ELEMENTS: [],
            CAT_SHOTS: [],
            CAT_AUDIO_ITEMS: [],
            "assets": [],
            "documents": [],
            "chatMessages": [],
        }
        self._active_project_id = project_id
        self._known_version = self._disk_board_version(project_id)
        self._ensure_conversations()
        self.save()
        return self.get()

    # ====== 多项目管理（委托给 ProjectManager） ======

    def list_projects(self) -> Dict[str, Any]:
        """返回所有项目列表 + 当前活跃 ID"""
        return self._project_mgr.list_projects(self._active_project_id)

    def create_project(self, name: str) -> str:
        """新建项目：保存当前 → 创建新项目 → 切换 → 返回 project_id"""
        return self._project_mgr.create_project(name, self._active_project_id)

    def switch_project(self, project_id: str) -> bool:
        """切换项目：保存当前 → 加载目标"""
        return self._project_mgr.switch_project(project_id, self._active_project_id)

    def delete_project(self, project_id: str) -> bool:
        """删除项目（硬删除）"""
        # 如果删除的是当前活跃项目，先切换到其他项目
        if project_id == self._active_project_id:
            index = self._repo.read_index()
            others = [p for p in index.get("projects", []) if p["id"] != project_id]
            if not others:
                return False
            # 先切换到第一个其他项目（保存当前状态）
            self._project_mgr.switch_project(others[0]["id"], self._active_project_id)
        # 执行删除
        new_active = self._project_mgr.delete_project(project_id, self._active_project_id)
        return new_active is not None

    def reset(self, project_name: str = "未命名项目", project_id: str = ""):
        """兼容旧接口：内部调用 create_project"""
        self.create_project(project_name)

    # ====== 查询辅助（Web 路由用） ======

    def get_groups(self) -> Dict[str, List[Dict]]:
        return {
            CAT_KEY_ELEMENTS: self._raw_state.get(CAT_KEY_ELEMENTS, []),
            CAT_SHOTS: self._raw_state.get(CAT_SHOTS, []),
            CAT_AUDIO_ITEMS: self._raw_state.get(CAT_AUDIO_ITEMS, []),
        }

    def get_assets(self) -> List[Dict]:
        return self._raw_state.get("assets", [])

    def get_chat_messages(self) -> List[Dict]:
        return self._raw_state.get("chatMessages", [])

    # ====== 多对话管理（委托给 conversation_ops） ======

    def _ensure_conversations(self) -> List[Dict[str, Any]]:
        """确保多对话结构存在并维护 chatMessages 不变式
        （实现见 conversation_ops.ensure_conversations）。"""
        return conversation_ops.ensure_conversations(self)

    def list_conversations(self) -> Dict[str, Any]:
        """列出当前项目的全部对话（含消息）+ 活跃对话 ID
        （实现见 conversation_ops.list_conversations）。"""
        return conversation_ops.list_conversations(self)

    def conversations_meta_payload(self) -> Dict[str, Any]:
        """多对话元信息响应（不含消息副本，消息单一来源；
        实现见 conversation_ops.conversations_meta_payload）。"""
        return conversation_ops.conversations_meta_payload(self)

    def get_conversation_messages(self, conversation_id: str) -> Optional[List[Dict[str, Any]]]:
        """按会话 ID 取消息（消息单一来源装载接口）；会话不存在返回 None
        （实现见 conversation_ops.get_conversation_messages）。"""
        return conversation_ops.get_conversation_messages(self, conversation_id)

    def create_conversation(self, title: str = "") -> Dict[str, Any]:
        """新建对话并设为活跃（实现见 conversation_ops.create_conversation）。"""
        return conversation_ops.create_conversation(self, title)

    def switch_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """切换活跃对话；不存在返回 None（实现见 conversation_ops.switch_conversation）。"""
        return conversation_ops.switch_conversation(self, conversation_id)

    def delete_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """删除对话；仅剩一个时不允许删除（实现见 conversation_ops.delete_conversation）。"""
        return conversation_ops.delete_conversation(self, conversation_id)

    def add_chat_message(
        self,
        sender: str,
        text: str,
        model_name: str = "",
        image_urls: Optional[List[str]] = None,
        meta: str = "",
        confirm: str = "",
        applied_actions: int = 0,
        action_log: Optional[List[str]] = None,
        doc_card: str = "",
        trace: Optional[Dict[str, Any]] = None,
        doc_blocks: Optional[List[str]] = None,
        skill_blocks: Optional[List[str]] = None,
        confirm_options: Optional[List[Dict[str, Any]]] = None,
        turn_id: str = "",
        error_detail: str = "",
        pause_id: str = "",
        pause_answered: Optional[Dict[str, str]] = None,
        kind: str = "",
        video_items: Optional[List[Dict[str, Any]]] = None,
        suggested_actions: Optional[List[Dict[str, Any]]] = None,
    ):
        """追加聊天记录并持久化（防抖合并落盘）。截断保留最近 200 条，防止状态文件无上限增长。

        image_urls: image_generate 工具（single 模式）产出的图片 URL 列表，以 imageCard 结构随消息持久化，
        前端刷新后可从历史记录重建生图卡片。
        video_items: 对话流视频内联预览卡条目（done 结算 chat_inserts 中 kind=video 项），
        以 videoCard 结构随消息持久化（与 imageCard 对称，瞬态 SSE 不作唯一可见性），
        每项保留 url/name/thumb；url 为空的非法项丢弃。
        meta/confirm/applied_actions/action_log/doc_card: Agent 回复的附加展示信息
        （耗时角标/阶段确认卡片/操作数/具体操作清单/文档完成卡片），随消息持久化，
        保证刷新页面后「阶段完成」卡片与耗时角标不丢失。
        doc_blocks/skill_blocks: 用户消息携带的文档/Skill 引用块名称，
        前端以可点击的块状形式展示（点击可查看对应文档）。
        turn_id：轮次唯一标识（同轮的正文/文档卡/图片卡共用），
        前端据此把产出聚合进同次容器，消除消息流碎片化。
        pause_id：agent 暂停卡的结构化标识（三个 confirm 产生源统一签发），
        用户回应消息经 pause_answered 回携，前端「当时所选」对勾不再靠文本反推。
        pause_answered：用户回应暂停的结构化标记 {"pause_id", "value", "label"}。
        kind：消息形态标记（如 system_action=系统动作行，不渲染为用户气泡）。
        suggested_actions：建议动作按钮列表（每项 {kind,label,value}，如
        kind=retry「继续刚才的任务」），随错误/停止消息落盘，历史装载后前端
        按既有 suggestedActions 渲染规则重建（刷新不再丢失）。

        实现体已切出：契约与实现见 conversation_ops.add_chat_message
        （条目构建 build_chat_entry + 防抖落盘 + 截断保留上限）。
        """
        conversation_ops.add_chat_message(
            self, sender, text, model_name, image_urls, meta, confirm,
            applied_actions, action_log, doc_card, trace, doc_blocks,
            skill_blocks, confirm_options, turn_id, error_detail, pause_id,
            pause_answered, kind, video_items, suggested_actions,
        )

    def truncate_chat_tail(self, keep_index: int, new_text: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """截断对话尾部（截断重答用）：契约与实现见 chat_tail_ops.truncate_chat_tail
        （破坏性写入；落盘被版本闸拒绝时抛 StateConflictError）。"""
        return chat_tail_ops.truncate_chat_tail(self, keep_index, new_text)

    def build_agent_context(self, asset_mode: str = "bound") -> str:
        """构建发送给 LLM 的 Studio 状态上下文（带缓存，状态未变时复用）"""
        return _build_context(self._raw_state, asset_mode, self._context_cache)

    def build_agent_context_degraded(self, asset_mode: str = "bound") -> str:
        """降级状态上下文（system 超预算保险丝）：只留组标题/编号/草稿计数"""
        return _build_context(self._raw_state, asset_mode, self._context_cache, degraded=True)

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


