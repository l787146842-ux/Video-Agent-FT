"""
SqliteStateRepository — SQLite 持久化层（与 StateRepository 同接口的可替换实现）。

动机：
- JSON 文件方案在高频防抖落盘、并发读写、大状态（聊天历史/故事板）下存在写放大与竞争风险；
- SQLite 提供事务原子性、单文件部署、按需查询能力，且仍保持零外部依赖（标准库 sqlite3）。

切换方式：STATE_BACKEND 默认 sqlite；
设 STATE_BACKEND=json 仅可回落到「未迁入 sqlite 的旧 JSON 工作区」。
迁移策略：首次启用且数据库为空时，自动从 workspace/projects/*/state.json + index.json 导入；
兼容文件 studio_state.json 经 StateManager._load → load_compat 一次性迁入。

单一事实源：SQLite 为项目状态唯一事实源，无 JSON 镜像。
代价明示：sqlite 写入后回退 STATE_BACKEND=json 不再无损续跑；
STATE_BACKEND=json 保留为测试基线与旧 JSON 工作区回落路径，
不承担生产数据连续性承诺。

JSON 回落冷备语义（审核结论钉死，非热双写）：
- 持续写入只落 SQLite：save_project/write_index 不产出任何 JSON 镜像，
  save_compat 为空实现（studio_state.json 不再被写）；
- JSON 仅作为冷备在恢复路径被读取一次：
  ① 首次启用且 DB 为空 → _auto_migrate_from_json 一次性导入；
  ② SQLite 文件损坏/不可读 → 隔离损坏文件（改名 .corrupt-<时间戳>
     保留现场，不删除）重建空库，随后经同一条冷恢复路径从 JSON
     工作区尽力恢复一次（best-effort：JSON 是迁入时点快照，
     之后的增量只在 SQLite）；
- 正常生命周期内 JSON 既不写也不读（冷备身份，非双写副本）。
语义由 tests/unit/test_repository_sqlite.py 钉死（无镜像写入 +
损坏隔离冷恢复两条用例）。
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
        # 兼容旧版 studio_state.json：仅保留只读入口
        # 供 StateManager._load 一次性迁移（load_compat）
        self._state_file = workspace_dir / "studio_state.json"
        self._db_file = workspace_dir / "state.sqlite3"
        self._lock = threading.Lock()
        self._last_bootstrap_error: Optional[Exception] = None

        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._projects_dir.mkdir(parents=True, exist_ok=True)
        if not self._try_bootstrap_schema():
            # 冷备恢复语义：SQLite 损坏/不可读时不直接崩溃——
            # 隔离损坏文件保留现场，重建空库后由
            # _auto_migrate_from_json 从 JSON 冷备尽力恢复一次
            self._quarantine_corrupt_db(self._last_bootstrap_error)
            self._try_bootstrap_schema()
        self._auto_migrate_from_json()

    def _try_bootstrap_schema(self) -> bool:
        """尝试建表；失败时先关闭连接再返回 False。

        Windows 兼容：损坏文件上的失败连接仍持有文件句柄，
        不显式 close 则后续改名隔离会被 WinError 32（文件占用）拦住。
        """
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = self._connect()
            conn.executescript(_SCHEMA)
            return True
        except sqlite3.DatabaseError as e:
            self._last_bootstrap_error = e
            return False
        finally:
            if conn is not None:
                conn.close()

    def _quarantine_corrupt_db(self, cause: Exception) -> None:
        """隔离损坏的数据库文件（改名保留现场，不删除）。

        改名带时间戳避免与后续重建冲突；WAL 侧车文件（-wal/-shm）
        一并隔离。Windows 兼容：用 Path.replace（同盘原子改名），
        目标名带时间戳不覆盖既有文件。重建后 DB 为空，
        随即触发 JSON 冷备的一次性恢复路径。
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            f = self._db_file.parent / (self._db_file.name + suffix)
            if f.exists():
                try:
                    f.replace(f.parent / f"{f.name}.corrupt-{ts}")
                except OSError as mv_err:
                    logger.warning(f"[SqliteRepo] 损坏文件隔离失败 {f.name}: {mv_err}")
        logger.error(
            f"[SqliteRepo] SQLite 损坏（{cause}）：已隔离并重建空库，"
            "随后从 JSON 冷备尽力恢复一次（JSON 为迁入时点快照，"
            "其后增量无法找回）"
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_file, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # 并发读 + 写不阻塞读
        except sqlite3.DatabaseError:
            # 损坏文件上 PRAGMA 即失败：必须显式 close 释放文件句柄，
            # 否则 Windows 下后续改名隔离被 WinError 32（文件占用）拦住
            conn.close()
            raise
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
        # SQLite 为唯一事实源，无 index.json 镜像

    def save_project(self, project_id: str, state: Dict[str, Any]) -> None:
        self._validate_id(project_id)
        state_text = json.dumps(state, ensure_ascii=False)
        now = self.now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO projects (id, state, updated_at) VALUES (?, ?, ?)",
                (project_id, state_text, now),
            )
        # SQLite 为唯一事实源，无 state.json 镜像

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
        # 遗留的旧项目目录可能仍在：删除项目时顺带清掉残留目录，
        # 防止回退 json 后端时已删项目借陈旧文件复活
        try:
            pdir = self._projects_dir / project_id
            if pdir.exists():
                shutil.rmtree(pdir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"[SqliteRepo] 镜像目录删除失败（{project_id}）: {e}")

    def save_compat(self, state: Dict[str, Any]) -> None:
        """studio_state.json 不写入。

        保留空实现维持 StateRepository 接口对齐（StateManager.save /
        ProjectManager 无需感知后端差异）。该文件仅余只读身份：
        启动时经 load_compat 一次性迁入 SQLite。
        """
        return

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
