"""
SqliteStateRepository — SQLite 持久化层（与 StateRepository 同接口的可替换实现）。

动机（审查报告 3.1）：
- JSON 文件方案在高频防抖落盘、并发读写、大状态（聊天历史/故事板）下存在写放大与竞争风险；
- SQLite 提供事务原子性、单文件部署、按需查询能力，且仍保持零外部依赖（标准库 sqlite3）。

切换方式：STATE_BACKEND 默认 sqlite（P3-16 翻转，等价性测试守护）；
设 STATE_BACKEND=json 一键回退（json 为回落后端）。
迁移策略：首次启用且数据库为空时，自动从 workspace/projects/*/state.json + index.json 导入；
双写回退期：DB 为权威源，同时镜像写回 JSON 侧文件
（projects/*/state.json + index.json + 兼容文件 studio_state.json），
回退 json 后端时无损续跑（含混用工作区，不依赖兼容文件迁移单路径）。
"""
import json
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from src.video_agent.exceptions import StateError
from src.video_agent.utils.fileio import atomic_write_text

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SqliteStateRepository:
    """SQLite 状态仓库 — 与 StateRepository 同接口（duck typing 替换）。

    线程安全：sqlite3 连接 check_same_thread=False + 实例级锁
    （StateManager 的防抖落盘在 worker 线程执行）。
    """

    def __init__(self, workspace_dir: Path):
        self._workspace_dir = workspace_dir
        self._projects_dir = workspace_dir / "projects"
        self._state_file = workspace_dir / "studio_state.json"  # 兼容旧版（双写）
        self._db_file = workspace_dir / "state.sqlite3"
        self._lock = threading.Lock()

        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._projects_dir.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)
        self._auto_migrate_from_json()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_file, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")  # 并发读 + 写不阻塞读
        return conn

    # ====== 自动迁移（仅 DB 为空时） ======

    def _auto_migrate_from_json(self) -> None:
        with self._lock, self._connect() as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM projects").fetchone()
            if count > 0:
                return
        index_file = self._projects_dir / "index.json"
        if not index_file.exists():
            return
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[SqliteRepo] 迁移跳过：index.json 读取失败 {e}")
            return
        migrated = 0
        with self._lock, self._connect() as conn:
            for p in index.get("projects", []):
                pid = p.get("id", "")
                sfile = self._projects_dir / pid / "state.json"
                if not pid or not sfile.exists():
                    continue
                try:
                    state_text = sfile.read_text(encoding="utf-8")
                    json.loads(state_text)  # 校验合法性
                    conn.execute(
                        "INSERT OR REPLACE INTO projects (id, state, updated_at) VALUES (?, ?, ?)",
                        (pid, state_text, p.get("updated_at", "")),
                    )
                    migrated += 1
                except Exception as e:
                    logger.warning(f"[SqliteRepo] 迁移项目 {pid} 失败: {e}")
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('index', ?)",
                (json.dumps(index, ensure_ascii=False),),
            )
        logger.info(f"[SqliteRepo] 已从 JSON 迁移 {migrated} 个项目到 SQLite")

    # ====== 双写回退期镜像（P3-16）：DB 权威，JSON 文件回落无损 ======

    def _mirror_project(self, project_id: str, state_text: str) -> None:
        """镜像写回 projects/<id>/state.json（镜像失败只警告不阻断主路径）。"""
        try:
            pdir = self._projects_dir / project_id
            pdir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(pdir / "state.json", state_text)
        except Exception as e:
            logger.warning(f"[SqliteRepo] 双写镜像 state.json 失败（{project_id}）: {e}")

    def _mirror_index(self, index: Dict[str, Any]) -> None:
        try:
            atomic_write_text(
                self._projects_dir / "index.json",
                json.dumps(index, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"[SqliteRepo] 双写镜像 index.json 失败: {e}")

    # ====== 与 StateRepository 相同的接口 ======

    @property
    def projects_dir(self) -> Path:
        return self._projects_dir

    def ensure_dirs(self) -> None:
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(project_id: str) -> None:
        if not project_id or "/" in project_id or "\\" in project_id or ".." in project_id:
            raise StateError(f"非法的项目 ID: {project_id!r}", error_code="INVALID_PROJECT_ID")

    def read_index(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='index'").fetchone()
        if row:
            try:
                return json.loads(row[0])
            except Exception as e:
                logger.warning(f"[SqliteRepo] Failed to read index: {e}")
        return {"active_project_id": "", "projects": []}

    def write_index(self, index: Dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('index', ?)",
                (json.dumps(index, ensure_ascii=False),),
            )
        self._mirror_index(index)

    def save_project(self, project_id: str, state: Dict[str, Any]) -> None:
        self._validate_id(project_id)
        state_text = json.dumps(state, ensure_ascii=False)
        now = self.now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO projects (id, state, updated_at) VALUES (?, ?, ?)",
                (project_id, state_text, now),
            )
        self._mirror_project(project_id, state_text)

    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        self._validate_id(project_id)
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT state FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception as e:
            logger.warning(f"[SqliteRepo] Failed to load project {project_id}: {e}")
            return None

    def delete_project_dir(self, project_id: str) -> None:
        self._validate_id(project_id)
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        # 镜像目录同删（双写回退期：回退 json 后不得见已删项目的残留）
        try:
            pdir = self._projects_dir / project_id
            if pdir.exists():
                shutil.rmtree(pdir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"[SqliteRepo] 镜像目录删除失败（{project_id}）: {e}")

    def save_compat(self, state: Dict[str, Any]) -> None:
        """双写旧版 studio_state.json（双写回退期内保持兼容）"""
        try:
            atomic_write_text(self._state_file, json.dumps(state, ensure_ascii=False, indent=2))
        except Exception as _e:
            logger.debug("[repository_sqlite] 忽略异常: {}", _e)

    def load_compat(self) -> Optional[Dict[str, Any]]:
        if self._state_file.exists():
            try:
                return json.loads(self._state_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
