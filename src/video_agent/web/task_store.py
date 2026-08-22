"""
TaskStore — 任务表/运行台账的事务性 KV 存储（任务 #24 存储层单一事实源收敛）。

背景：agent_tasks.json / generation_tasks.json 此前各自以 data/*.json 整文件
原子重写方式落盘（写放大 + 无事务 + 与项目状态库并存三源）。收敛后统一进
workspace/state.sqlite3 的 kv 表：一个 key 一行、整份 JSON 载荷存 TEXT blob 列。

选型坦承（任务 #24 非目标）：本表定位「带事务的 KV」，不做规范化拆表——
任务表规模小（上限 50/200 条）、整进整出语义与旧文件完全一致，
blob 列实现成本最小且天然单语句事务原子。

与 SqliteStateRepository 共用同一 DB 文件（WAL 下多连接并发读写安全），
但职责互不交叉：projects/meta 表归状态仓库，kv 表归本模块。
"""
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from src.video_agent.utils.paths import WORKSPACE_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class TaskStore:
    """workspace/state.sqlite3 kv 表的事务性读写（线程安全：实例级锁）。"""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_file = Path(db_path) if db_path else WORKSPACE_DIR / "state.sqlite3"
        self._lock = threading.Lock()
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_file, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        """按键读取整份 JSON 载荷；不存在/损坏返回 None（损坏只警告不抛）。"""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception as e:
            logger.warning(f"[TaskStore] kv 载荷解析失败 key={key}: {e}")
            return None

    def save(self, key: str, payload: Dict[str, Any]) -> None:
        """整份 JSON 载荷单语句事务写入（INSERT OR REPLACE 原子覆盖）。"""
        text = json.dumps(payload, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, text))

    def exists(self, key: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT 1 FROM kv WHERE key=?", (key,)).fetchone()
        return row is not None
