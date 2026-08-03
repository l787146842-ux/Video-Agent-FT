"""
GenerationTaskManager — 生成任务统一管理（从 routes/generate.py 抽离）。

职责：
- 任务生命周期管理（创建、查询、更新、清理）
- 后台 asyncio.Task 追踪（防止 fire-and-forget 丢失）
- SSE 订阅者通知（任务完成时推送事件）

单例模式：通过 get_task_manager() 获取全局实例。
"""
import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager


class GenerationTaskManager:
    """生成任务管理器 — 统一管理图片/视频生成任务的生命周期。"""

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._background_tasks: set = set()
        self._sse_subscribers: List[asyncio.Queue] = []
        self._task_ttl = settings.task_ttl_seconds
        self._task_max = settings.task_max

    # ====== 任务 CRUD ======

    def create_task(self, task_id: str, **fields: Any) -> Dict[str, Any]:
        """创建新任务并返回任务字典"""
        self._purge_stale()
        task = {"created_at": time.time(), **fields}
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询单个任务"""
        return self._tasks.get(task_id)

    def update_task(self, task_id: str, **fields: Any) -> None:
        """更新任务字段"""
        task = self._tasks.get(task_id)
        if task:
            task.update(fields)

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """返回最近的任务列表（按创建时间倒序）"""
        items = sorted(self._tasks.values(), key=lambda t: t.get("created_at", 0), reverse=True)
        return items[:limit]

    @property
    def tasks(self) -> Dict[str, Dict[str, Any]]:
        """直接访问任务字典（向后兼容）"""
        return self._tasks

    # ====== 后台任务追踪 ======

    def track(self, coro) -> None:
        """创建并追踪后台 asyncio.Task，异常自动记录"""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        task.add_done_callback(self._log_exception)

    @staticmethod
    def _log_exception(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"[TaskManager] 后台任务未捕获异常: {exc}")

    # ====== SSE 通知 ======

    def subscribe(self) -> asyncio.Queue:
        """注册 SSE 订阅者，返回消息队列"""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._sse_subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """移除 SSE 订阅者"""
        if q in self._sse_subscribers:
            self._sse_subscribers.remove(q)

    def notify(self, event_data: Dict[str, Any]) -> None:
        """向所有 SSE 订阅者推送事件"""
        msg = json.dumps(event_data, ensure_ascii=False)
        dead: List[asyncio.Queue] = []
        for q in self._sse_subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._sse_subscribers.remove(q)

    # ====== 内部清理 ======

    def _purge_stale(self) -> None:
        """清理过期/超量任务（处理中的任务不清理）"""
        now = time.time()
        stale = [
            tid for tid, t in self._tasks.items()
            if now - t.get("created_at", now) > self._task_ttl
            and t.get("status") not in ("processing", "pending")
        ]
        for tid in stale:
            self._tasks.pop(tid, None)
        if len(self._tasks) > self._task_max:
            purgeable = [
                tid for tid in sorted(self._tasks, key=lambda t: self._tasks[t].get("created_at", 0))
                if self._tasks[tid].get("status") not in ("processing", "pending")
            ]
            for tid in purgeable[:len(self._tasks) - self._task_max]:
                self._tasks.pop(tid, None)


# ====== 全局单例 ======

_instance: Optional[GenerationTaskManager] = None


def get_task_manager() -> GenerationTaskManager:
    """获取全局 TaskManager 单例"""
    global _instance
    if _instance is None:
        _instance = GenerationTaskManager()
    return _instance


def writeback_if_complete(task_id: str) -> None:
    """任务完成后，将结果回写到 StateManager（更新对应 draft 并持久化）。

    从 routes/generate.py 下沉到本模块：消除 web 层（action_executor 等）
    对 routes 层的反向依赖。
    """
    task = get_task_manager().get_task(task_id)
    if not task or task.get("status") not in ("succeeded", "completed"):
        return

    draft_id = task.get("draft_id", "")
    if not draft_id:
        return

    url = ""
    field = "imgUrl"
    if task.get("video_url"):
        url = task["video_url"]
        field = "videoUrl"
    elif task.get("result", {}) and task["result"].get("images"):
        url = task["result"]["images"][0]
        field = "imgUrl"
    if not url:
        return

    svc = StateManager.get_instance()
    for category in svc.get_groups().values():
        for group in category:
            for draft in group.get("drafts", []):
                if draft.get("id") == draft_id:
                    draft[field] = url
                    # 同步生成媒体类型，保证预览区与参数栏跟随最新结果（如视频替换原图片）
                    media_type = "video" if field == "videoUrl" else "image"
                    draft["mediaType"] = media_type
                    draft["genType"] = media_type
                    # 一张卡片只存一个媒体：清空其他类型的 URL
                    for other_field in ("imgUrl", "videoUrl", "audioUrl"):
                        if other_field != field:
                            draft[other_field] = ""
                    draft["tag"] = "mock 演示" if task.get("mock") else "已生成"
                    svc.save()
                    logger.info(f"[Generate] Writeback: draft {draft_id} → {field}={url[:60]}")
                    return
