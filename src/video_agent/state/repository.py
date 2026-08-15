"""
StateRepository — 纯持久化层（从 StateManager 拆分）。

职责：
- 项目目录的读写（state.json）
- 项目索引（index.json）的读写
- 兼容文件（studio_state.json）的写入
- 时间戳工具

不包含任何业务逻辑，仅负责 I/O。
"""
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from src.video_agent.exceptions import StateError
from src.video_agent.utils.fileio import atomic_write_text

# project_id 白名单格式（如 proj_1736000000），杜绝 ../ 等路径遍历字符
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class StateRepository:
    """状态持久化仓库 — 管理项目目录、索引文件、兼容文件。"""

    def __init__(self, workspace_dir: Path):
        self._workspace_dir = workspace_dir
        self._projects_dir = workspace_dir / "projects"
        self._state_file = workspace_dir / "studio_state.json"  # 兼容旧版
        self._index_file = self._projects_dir / "index.json"

    def _project_dir(self, project_id: str) -> Path:
        """校验 project_id 并返回项目目录（白名单正则 + resolve 前缀双重校验）。

        非法 id（如 ../../etc）直接抛 StateError，防止路径遍历读写 workspace 外文件。
        """
        if not project_id or not _PROJECT_ID_RE.match(project_id):
            raise StateError(f"非法的项目 ID: {project_id!r}", error_code="INVALID_PROJECT_ID")
        pdir = (self._projects_dir / project_id).resolve()
        if not str(pdir).startswith(str(self._projects_dir.resolve()) + os.sep) \
                and pdir != self._projects_dir.resolve():
            raise StateError(f"非法的项目路径: {project_id!r}", error_code="INVALID_PROJECT_ID")
        return pdir

    @property
    def projects_dir(self) -> Path:
        return self._projects_dir

    def ensure_dirs(self) -> None:
        """确保工作区和项目目录存在"""
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    # ====== 索引文件 ======

    def read_index(self) -> Dict[str, Any]:
        if self._index_file.exists():
            try:
                return json.loads(self._index_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[StateRepo] Failed to read index: {e}")
        return {"active_project_id": "", "projects": []}

    def write_index(self, index: Dict[str, Any]) -> None:
        atomic_write_text(self._index_file, json.dumps(index, ensure_ascii=False, indent=2))

    # ====== 项目目录 ======

    def save_project(self, project_id: str, state: Dict[str, Any]) -> None:
        """将状态写入项目目录"""
        pdir = self._project_dir(project_id)
        pdir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(pdir / "state.json", json.dumps(state, ensure_ascii=False, indent=2))

    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """从项目目录加载状态，不存在或失败返回 None"""
        sfile = self._project_dir(project_id) / "state.json"
        if not sfile.exists():
            return None
        try:
            return json.loads(sfile.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[StateRepo] Failed to load project {project_id}: {e}")
            return None

    def delete_project_dir(self, project_id: str) -> None:
        """删除项目目录（硬删除）"""
        pdir = self._project_dir(project_id)
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)

    # ====== 兼容文件 ======

    def save_compat(self, state: Dict[str, Any]) -> None:
        """写入旧版 studio_state.json（向后兼容）"""
        try:
            atomic_write_text(self._state_file, json.dumps(state, ensure_ascii=False, indent=2))
        except Exception as _e:
            logger.debug("[repository] 忽略异常: {}", _e)

    def load_compat(self) -> Optional[Dict[str, Any]]:
        """读取旧版 studio_state.json"""
        if self._state_file.exists():
            try:
                return json.loads(self._state_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    # ====== 工具 ======

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
