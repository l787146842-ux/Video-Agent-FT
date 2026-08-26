"""
GenerationTaskManager — 生成任务统一管理（从 routes/generate.py 抽离）。

职责：
- 任务生命周期管理（创建、查询、更新、清理）
- 后台 asyncio.Task 追踪（防止 fire-and-forget 丢失）
- SSE 订阅者通知（任务完成时推送事件）

单例模式：通过 get_task_manager 获取全局实例。
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.utils.paths import DATA_DIR
from src.video_agent.web.task_store import TaskStore

# 任务表持久化单源收敛 —— 落盘走 workspace/state.sqlite3 kv 表
# （事务性，见 task_store）；旧 JSON 文件仅作首启一次性导入兜底，
# 导入后保留只读一个版本周期
_STORE_KEY = "generation_tasks"


class GenerationTaskManager:
    """生成任务管理器 — 统一管理图片/视频生成任务的生命周期与生成日志。"""

    def __init__(
        self,
        store: Optional[TaskStore] = None,
        legacy_file: Optional[Path] = None,
    ):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._background_tasks: set = set()
        self._sse_subscribers: List[asyncio.Queue] = []
        self._task_ttl = settings.task_ttl_seconds
        self._task_max = settings.task_max
        # 生成日志环形缓冲（最新在前）：图/视频/音频每次生成的成败记录，
        # 供顶部导航「生成日志」面板展示（照搬画布日志风格）
        self._gen_logs: List[Dict[str, Any]] = []
        # event_seq 契约：管理器级帧序号计数器，每条通知从 1 单调递增
        # （前端按 (task_id, event_seq) 去重）
        self._event_seq = 0
        # 任务表 + 生成日志落盘：重启后 processing 任务不再永久丢失回调
        # store/legacy_file 可注入（测试隔离）；生产默认全局库 + data/ 旧文件
        self._store = store or TaskStore()
        self._legacy_file = Path(legacy_file) if legacy_file else DATA_DIR / "generation_tasks.json"
        self._import_legacy_file()
        self._load_persisted()

    def _import_legacy_file(self) -> None:
        """一次性导入兜底：sqlite 无数据而旧 JSON 存在时读入 kv 表（幂等）。

        导入后旧文件不再被读写（停写保留只读）。
        """
        try:
            if self._store.exists(_STORE_KEY) or not self._legacy_file.exists():
                return
            data = json.loads(self._legacy_file.read_text(encoding="utf-8"))
            payload = data if isinstance(data, dict) else {"tasks": data}
            self._store.save(_STORE_KEY, payload)
            logger.info(f"[TaskManager] 已从旧任务表导入 SQLite: {self._legacy_file}")
        except Exception as e:
            logger.warning(f"[TaskManager] 旧任务表导入失败: {e}")

    # ====== 任务 CRUD ======

    def create_task(self, task_id: str, **fields: Any) -> Dict[str, Any]:
        """创建新任务并返回任务字典"""
        self._purge_stale()
        task = {"created_at": time.time(), **fields}
        self._tasks[task_id] = task
        self._persist()
        return task

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询单个任务"""
        return self._tasks.get(task_id)

    def update_task(self, task_id: str, **fields: Any) -> None:
        """更新任务字段"""
        task = self._tasks.get(task_id)
        if task:
            task.update(fields)
            self._persist()

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
        """向所有 SSE 订阅者推送事件（每帧附 event_seq；终态队列满时补投）"""
        # event_seq 契约（发射侧）：单调递增帧序号，前端按 (task_id, event_seq) 去重
        self._event_seq += 1
        stamped = {**event_data, "event_seq": self._event_seq}
        # 终态判定：生成任务成败状态或结构化终态类型；终态丢失 = 前端永挂
        terminal = (
            stamped.get("status") in ("succeeded", "failed", "completed", "cancelled")
            or stamped.get("type") in ("done", "error", "stopped", "task_status")
        )
        msg = json.dumps(stamped, ensure_ascii=False)
        dead: List[asyncio.Queue] = []
        for q in self._sse_subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                if terminal:
                    # 终态补投：先清空积压再强投本条；仍失败才摘除订阅者
                    while True:
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    try:
                        q.put_nowait(msg)
                        continue
                    except asyncio.QueueFull:
                        pass
                dead.append(q)
        for q in dead:
            self._sse_subscribers.remove(q)

    # ====== 生成日志（图/视频/音频，无论成败均记录） ======

    def record_gen_log(
        self,
        *,
        media_type: str,
        status: str,
        provider: str = "",
        model: str = "",
        prompt: str = "",
        draft_id: str = "",
        error: str = "",
        result_url: str = "",
        elapsed: float = 0.0,
        requested_size: str = "",
        source: str = "",
        task_id: str = "",
    ) -> Dict[str, Any]:
        """追加/合并生成日志（最新在前，上限 _GEN_LOG_MAX 条）。

        media_type: image | video | audio
        status: started | succeeded | failed
        source: 触发来源（agent / manual / batch），便于排查
        task_id: 同一任务的 started 与终态（succeeded/failed）按 task_id
        合并为同一条记录（原地更新），避免任务成功后日志里仍残留「进行中」。
        """
        # 终态合并：找到同 task_id 的 started 条目则原地更新
        if task_id and status in ("succeeded", "failed"):
            for entry in self._gen_logs:
                if entry.get("task_id") == task_id and entry.get("status") == "started":
                    entry["status"] = status
                    entry["error"] = error
                    entry["result_url"] = result_url
                    entry["elapsed"] = round(elapsed, 1)
                    if model:
                        entry["model"] = model
                    self._persist()
                    return entry

        entry: Dict[str, Any] = {
            "id": f"gl-{int(time.time() * 1000)}-{len(self._gen_logs) % 1000}",
            "task_id": task_id,
            "media_type": media_type,
            "status": status,
            "provider": provider,
            # 供应商显示名（API 配置页的名称，如 Grsai/Antigravity CLI），
            # 前端优先展示它；内部 id（如 custom-api）仅留作排查
            "provider_name": _resolve_provider_display_name(provider),
            "model": model,
            "prompt": (prompt or "")[:300],
            "draft_id": draft_id,
            "error": error,
            "result_url": result_url,
            "elapsed": round(elapsed, 1),
            "requested_size": requested_size,
            "source": source,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._gen_logs.insert(0, entry)
        if len(self._gen_logs) > _GEN_LOG_MAX:
            del self._gen_logs[_GEN_LOG_MAX:]
        self._persist()
        return entry

    def get_gen_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """返回最近 N 条生成日志（时间倒序）"""
        return self._gen_logs[: max(1, min(limit, _GEN_LOG_MAX))]

    def record_error_log(self, label: str, message: str, model: str = "") -> None:
        """错误事件记入生成日志（需求）：保存被拒/工具失败/流中断等
        原本只在右上角 toast 一闪而过的报错，事后可在「错误」页签回看。"""
        try:
            self.record_gen_log(
                media_type="error",
                status="failed",
                provider=label,
                model=model,
                error=(message or "")[:500],
                source="system",
            )
        except Exception:
            pass  # 记日志不得影响主流程

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
        self._persist()

    # ====== 落盘与恢复 ======

    def _load_persisted(self) -> None:
        """启动恢复：加载落盘任务与生成日志；processing/pending 标记为 failed。"""
        try:
            data = self._store.load(_STORE_KEY)
            if not data:
                return
            tasks = data.get("tasks") or []
            logs = data.get("logs") or []
        except Exception as e:
            logger.warning(f"[TaskManager] 恢复任务表失败: {e}")
            return
        recovered = 0
        for t in tasks:
            if not isinstance(t, dict) or not t.get("task_id"):
                continue
            if t.get("status") in ("processing", "pending"):
                t["status"] = "failed"
                t["error"] = "服务重启中断，任务未完成"
            self._tasks[t["task_id"]] = t
            recovered += 1
        if isinstance(logs, list):
            # 容量保护：恢复路径同样收敛至写入侧上限，
            # 防止历史超限载荷只进不出
            self._gen_logs = [l for l in logs if isinstance(l, dict)][:_GEN_LOG_MAX]
        if recovered:
            logger.info(f"[TaskManager] 已恢复 {recovered} 个任务（中断任务已标记 failed）")
        # 数据 TTL——启动恢复后立即清理过期/超量任务
        # （gen 日志保留，任务表按 TTL 收敛）
        try:
            self._purge_stale()
        except Exception as e:
            logger.warning(f"[TaskManager] 启动 TTL 清理失败: {e}")
        self._persist()

    def _persist(self) -> None:
        """任务表 + 生成日志事务落盘（供重启恢复；跳过不可序列化的运行时字段）。"""
        try:
            payload = {
                "tasks": [
                    {"task_id": tid, **{
                        k: v for k, v in t.items() if not k.startswith("_")
                    }}
                    for tid, t in self._tasks.items()
                ],
                "logs": self._gen_logs,
            }
            self._store.save(_STORE_KEY, payload)
        except Exception as e:
            logger.warning(f"[TaskManager] 任务表落盘失败: {e}")


# ====== 全局单例 ======

# 生成日志保留上限（内存环形缓冲，不落盘；重启后清空属预期行为）
_GEN_LOG_MAX = 200


def _resolve_provider_display_name(provider_id: str) -> str:
    """供应商内部 id → API 配置页的显示名（如 custom-api → Grsai）。

    日志面板展示用；解析失败回退内部 id。懒加载导入避免模块循环。
    """
    if not provider_id:
        return ""
    try:
        from src.video_agent.core.provider_config import get_provider_config
        cfg = get_provider_config(provider_id)
        if cfg and cfg.get("name"):
            return str(cfg["name"])
    except Exception as _e:
        logger.debug("[task_manager] 忽略异常: {}", _e)
    return provider_id


_instance: Optional[GenerationTaskManager] = None


def get_task_manager() -> GenerationTaskManager:
    """获取全局 TaskManager 单例"""
    global _instance
    if _instance is None:
        _instance = GenerationTaskManager()
    return _instance


def snapshot_inflight_generations() -> List[Dict[str, Any]]:
    """在途外部生成任务快照（端到端中断协议）。

    停止路径调用：列出仍在 processing/pending 的图片/视频生成任务。
    第一版不做真实撤销（供应商侧无统一取消通道），只登记 + 文案告知
    哪些生成仍在供应商侧继续进行；后续方向：按 task_id 对接供应商
    取消 API 实现真实撤销/补偿（见 stop_signal 模块注释）。
    """
    out: List[Dict[str, Any]] = []
    try:
        tasks = get_task_manager().tasks
    except Exception:
        return out
    for tid, task in tasks.items():
        if not isinstance(task, dict) or task.get("status") not in ("processing", "pending"):
            continue
        # 媒体类型判定：视频任务创建时带 adapter_type 标记，其余为图片
        media = "video" if task.get("adapter_type") == "video_generation" else "image"
        out.append({
            "task_id": str(tid),
            "media_type": media,
            "model": str(task.get("model") or ""),
            "draft_id": str(task.get("draft_id") or ""),
            # 提示词截断前 60 字：停止文案里可识别是哪一项生成
            "summary": str(task.get("prompt") or "")[:60],
        })
    return out


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
                    draft["tag"] = "已生成"
                    svc.save()
                    logger.info(f"[Generate] Writeback: draft {draft_id} → {field}={url[:60]}")
                    return
