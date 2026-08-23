"""Agent 聊天后台任务管理。

目标：Agent 运行与 HTTP 连接解耦——
- 提交后立即返回 task_id，worker 在后台运行；
- 前端通过 /api/agent/events/{task_id} 订阅（新订阅先回放累计状态）；
- 页面刷新 / 切换项目只是断开订阅，不会取消 worker；
- 每个任务绑定所属项目的 StateManager（contextvar），多项目并发互不串写。
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.utils import gen_id
from src.video_agent.utils.paths import DATA_DIR
from src.video_agent.web.error_payload import classify_exception
from src.video_agent.web.task_store import TaskStore

_TASK_MAX = 50

# 任务 #24：任务表持久化单源收敛 —— data/agent_tasks.json 停写，
# 落盘迁入 workspace/state.sqlite3 kv 表（事务性，见 task_store）；
# 旧文件仅作首启一次性导入兜底，导入后保留只读一个版本周期
_STORE_KEY = "agent_tasks"


class AgentTaskManager:
    def __init__(
        self,
        store: Optional[TaskStore] = None,
        legacy_file: Optional[Path] = None,
    ) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        # store/legacy_file 可注入（测试隔离）；生产默认全局库 + data/ 旧文件
        self._store = store or TaskStore()
        self._legacy_file = Path(legacy_file) if legacy_file else DATA_DIR / "agent_tasks.json"
        self._import_legacy_file()
        self._load_persisted()

    def _import_legacy_file(self) -> None:
        """一次性导入兜底：sqlite 无数据而旧 JSON 存在时读入 kv 表（幂等）。

        导入后旧文件不再被读写（停写保留只读），防止重启反复导入无谓告警。
        """
        try:
            if self._store.exists(_STORE_KEY) or not self._legacy_file.exists():
                return
            data = json.loads(self._legacy_file.read_text(encoding="utf-8"))
            payload = data if isinstance(data, dict) else {"tasks": data}
            self._store.save(_STORE_KEY, payload)
            logger.info(f"[AgentTask] 已从旧任务表导入 SQLite: {self._legacy_file}")
        except Exception as e:
            logger.warning(f"[AgentTask] 旧任务表导入失败: {e}")

    # ====== 创建 / 生命周期 ======

    def create(
        self,
        project_id: str,
        worker_factory: Callable[[], Awaitable[None]],
        task_id: str = "",
        model: str = "",
    ) -> Dict[str, Any]:
        """创建后台任务并启动 worker，返回任务记录。"""
        self._purge_stale()
        task_id = task_id or gen_id("agt")
        record: Dict[str, Any] = {
            "task_id": task_id,
            "project_id": project_id,
            "model": model,
            "status": "running",
            "created_at": time.time(),
            "reasoning": "",
            "text": "",
            "status_text": "正在连接…",
            "tools": [],
            "snapshot": None,
            "done_payload": None,
            # 停止终态事件（任务 #17）：stopped 事件完整负载，replay 携带供刷新后恢复痕迹
            "stopped_payload": None,
            # 降级即时联动（D-A）：最近一次 fallback 切换实际生效的厂商/模型，
            # 随 replay 下发，刷新重连后前端仍能把选择器跳到正确组合
            "fallback": None,
            "error": None,
            # 轮间引导注入队列（用户推理中发送的排队消息，planner 逐轮消费）
            "pending_guidance": [],
            "_subscribers": [],
            "_task": None,
        }
        record["_task"] = asyncio.create_task(worker_factory())
        record["_task"].add_done_callback(lambda t: self._on_done(task_id, t))
        self._tasks[task_id] = record
        self._persist()
        logger.info(f"[AgentTask] created task_id={task_id} project={project_id}")
        return record

    def stop(self, task_id: str) -> bool:
        """取消后台任务（用户点击停止）。"""
        record = self._tasks.get(task_id)
        if not record:
            return False
        task = record.get("_task")
        if task and not task.done():
            task.cancel()
        record["status"] = "cancelled"
        self._persist()
        self._notify(record, {"type": "task_status", "status": "cancelled"})
        return True

    # ====== 轮间引导注入（恢复：机制重新接线） ======

    def add_pending_guidance(self, task_id: str, item: Dict[str, Any]) -> bool:
        """把用户排队消息登记到运行中任务，供 planner 轮间注入。

        item: {id, text}。任务不存在/已结束返回 False（前端回落自动出队重发）。
        上限 20 条防灌爆；注入后由 drain 消费，任务结束由 clear 清空。"""
        record = self._tasks.get(task_id)
        if not record or record.get("status") != "running":
            return False
        gid = str(item.get("id") or "")
        gtext = str(item.get("text") or "").strip()
        if not gid or not gtext:
            return False
        pending = record.setdefault("pending_guidance", [])
        if len(pending) >= 20 or any(p.get("id") == gid for p in pending):
            return False
        pending.append({"id": gid, "text": gtext})
        logger.info(f"[AgentTask] {task_id} 登记轮间引导: {gid}")
        return True

    def drain_pending_guidance(self, task_id: str) -> List[Dict[str, Any]]:
        """取出并清空任务的排队引导项（planner 每轮调用，单次消费语义）。"""
        record = self._tasks.get(task_id)
        if not record:
            return []
        pending = record.get("pending_guidance") or []
        record["pending_guidance"] = []
        return pending

    def clear_pending_guidance(self, task_id: str) -> None:
        """任务结束时清空未注入项（前端 done 后自动重发为普通请求，防双注入）。"""
        record = self._tasks.get(task_id)
        if record:
            record["pending_guidance"] = []

    def cancel_project(self, project_id: str) -> int:
        """取消某项目的全部后台任务（项目删除时调用），返回取消数量。"""
        n = 0
        for record in list(self._tasks.values()):
            if record.get("project_id") != project_id or record.get("status") != "running":
                continue
            self.stop(record["task_id"])
            n += 1
        return n

    def _on_done(self, task_id: str, task: asyncio.Task) -> None:
        record = self._tasks.get(task_id)
        if not record:
            return
        if task.cancelled():
            # 任务 #17：worker 已在 CancelledError 落地时发过 stopped 终态事件
            # （协作式停止）时，保留 stopped 状态，不覆盖为 cancelled
            if record["status"] != "stopped":
                record["status"] = "cancelled"
            # 取消路径原先完全静默，必须留痕
            logger.warning(f"[AgentTask] {task_id} 后台任务被取消")
        elif task.exception():
            exc = task.exception()
            record["status"] = "error"
            record["error"] = str(exc)
            # 任务 #19：结构化归类随 replay 下发（刷新恢复后前端映射表仍能命中）
            _p = classify_exception(exc)  # type: ignore[arg-type]
            record["error_payload"] = {"code": _p.code, "kind": _p.kind, "raw": _p.raw}
            logger.error(f"[AgentTask] {task_id} 后台异常: {exc}")
        else:
            # asyncio 任务结束即权威终态——worker 未自发 done 事件时
            # 状态不得永停 running（静默死亡症状），兜底落 done
            if record["status"] == "running":
                record["status"] = "done"
            logger.info(f"[AgentTask] {task_id} 后台任务结束")
        self._persist()

    # ====== 事件写入 / 订阅 ======

    def emit(self, task_id: str, event: Dict[str, Any]) -> None:
        """worker 事件入口：更新累计状态 + 推送给所有订阅者。"""
        record = self._tasks.get(task_id)
        if not record:
            return
        self._apply_event(record, event)
        self._notify(record, event)

    def subscribe(self, task_id: str) -> Optional[asyncio.Queue]:
        """订阅任务事件流；新订阅者立即收到一条 replay（累计状态）。"""
        record = self._tasks.get(task_id)
        if not record:
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        record.setdefault("_subscribers", []).append(q)
        q.put_nowait({
            "type": "replay",
            "payload": {
                "task_id": task_id,
                "project_id": record["project_id"],
                "model": record.get("model", ""),
                "status": record["status"],
                "status_text": record["status_text"],
                "reasoning": record["reasoning"],
                "text": record["text"],
                "tools": record["tools"],
                "snapshot": record["snapshot"],
                "done_payload": record["done_payload"],
                "stopped_payload": record.get("stopped_payload"),
                "docs": list(record.get("docs") or []),
                "wf_event_sequence": int(record.get("wf_event_sequence") or 0),
                "fallback": record.get("fallback"),
                "error": record["error"],
                # 任务 #19：结构化错误归类（code/kind/raw；旧记录无此键时为 None）
                "error_payload": record.get("error_payload"),
            },
        })
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue) -> None:
        record = self._tasks.get(task_id)
        if record:
            subs = record.get("_subscribers") or []
            if q in subs:
                subs.remove(q)

    def _notify(self, record: Dict[str, Any], event: Dict[str, Any]) -> None:
        dead: List[asyncio.Queue] = []
        for q in list(record.get("_subscribers") or []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            record["_subscribers"].remove(q)

    def _apply_event(self, record: Dict[str, Any], event: Dict[str, Any]) -> None:
        etype = event.get("type", "")
        if etype == "status":
            record["status_text"] = str(event.get("text") or "")
        elif etype == "delta":
            record["text"] += str(event.get("text") or "")
        elif etype == "reasoning_delta":
            record["reasoning"] += str(event.get("text") or "")
        elif etype == "tool_started":
            record["tools"].append({
                "id": event.get("id", ""),
                "name": event.get("name", ""),
                "summary": event.get("summary", ""),
                # 输入参数预览（后端已裁剪脱敏，任务 #2）：重连 replay 后
                # 详情卡展开区不丢
                "args": event.get("args") or {},
                "status": "running",
                "elapsed_ms": None,
                "result_summary": "",
                # 运行中走秒起点（replay/重连后前端继续计时）
                "started_at_ms": round(time.time() * 1000),
            })
        elif etype == "tool_finished":
            tid = event.get("id", "")
            for t in record["tools"]:
                if t.get("id") == tid:
                    t["status"] = "done" if event.get("ok") else "failed"
                    t["elapsed_ms"] = event.get("elapsed_ms")
                    t["result_summary"] = str(event.get("result_summary") or "")
                    # 规划级标记入账本，重连 replay 后徽标不丢
                    if event.get("planning"):
                        t["planning"] = True
                    break
        elif etype == "actions_applied":
            payload = event.get("payload") or {}
            if payload.get("state"):
                record["snapshot"] = payload["state"]
        elif etype == "model_fallback":
            # 降级切换时刻累计：刷新/重连后 replay 携带，前端补跳选择器
            record["fallback"] = {
                "provider": str(event.get("provider") or ""),
                "model": str(event.get("model") or ""),
            }
        elif etype == "done":
            payload = event.get("payload") or {}
            record["status"] = "done"
            record["done_payload"] = payload
            if payload.get("state"):
                record["snapshot"] = payload["state"]
            # v2 收尾：workflow 事件序列高水位（重连按 sequence 补发/去重依据）
            _wf = payload.get("workflow") or {}
            _seq = int(_wf.get("event_sequence") or 0)
            if _seq > int(record.get("wf_event_sequence") or 0):
                record["wf_event_sequence"] = _seq
        elif etype == "doc_written":
            # Rule2 v6 产物账本累积：断连重连 replay 补渲染文档卡
            _dn = str(event.get("name") or "")
            if _dn and _dn not in record.setdefault("docs", []):
                record["docs"].append(_dn)
        elif etype == "stopped":
            # 停止终态（任务 #17）：落终态标记与完整负载，供 replay 恢复痕迹
            record["status"] = "stopped"
            record["stopped_payload"] = event
            record["status_text"] = "已被用户停止"
        elif etype == "error":
            record["status"] = "error"
            record["error"] = str(event.get("detail") or event.get("text") or "")
            # 任务 #19：error 事件携带结构化归类时入账，replay 同源下发
            if event.get("code") or event.get("kind"):
                record["error_payload"] = {
                    "code": str(event.get("code") or ""),
                    "kind": str(event.get("kind") or ""),
                    "raw": str(event.get("raw") or ""),
                }

    # ====== 查询 ======

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        record = self._tasks.get(task_id)
        if not record:
            return None
        return {
            k: v for k, v in record.items()
            if not k.startswith("_")
        }

    def list_running(self, project_id: str = "") -> List[Dict[str, Any]]:
        out = []
        for record in self._tasks.values():
            if record.get("status") != "running":
                continue
            if project_id and record.get("project_id") != project_id:
                continue
            out.append({
                "task_id": record["task_id"],
                "project_id": record["project_id"],
                "status": record["status"],
                "created_at": record["created_at"],
                "status_text": record["status_text"],
            })
        return sorted(out, key=lambda t: t["created_at"], reverse=True)

    # ====== 清理 / 落盘 ======

    def _purge_stale(self) -> None:
        now = time.time()
        stale = [
            tid for tid, r in self._tasks.items()
            if r.get("status") != "running" and now - r.get("created_at", now) > 3600
        ]
        for tid in stale:
            self._tasks.pop(tid, None)
        if len(self._tasks) > _TASK_MAX:
            # 保留最新的（创建时间倒序），运行中的不清理
            running = [tid for tid, r in self._tasks.items() if r.get("status") == "running"]
            done_sorted = sorted(
                (tid for tid, r in self._tasks.items() if tid not in running),
                key=lambda tid: self._tasks[tid].get("created_at", 0),
                reverse=True,
            )
            for tid in done_sorted[len(self._tasks) - len(running) - _TASK_MAX:]:
                self._tasks.pop(tid, None)

    def _persist(self) -> None:
        try:
            payload = {
                "tasks": [
                    {
                        "task_id": r["task_id"],
                        "project_id": r["project_id"],
                        "status": r["status"],
                        "created_at": r["created_at"],
                    }
                    for r in self._tasks.values()
                ]
            }
            self._store.save(_STORE_KEY, payload)
        except Exception as e:
            logger.warning(f"[AgentTask] 任务表落盘失败: {e}")

    def _load_persisted(self) -> None:
        try:
            data = self._store.load(_STORE_KEY)
        except Exception as e:
            logger.warning(f"[AgentTask] 恢复任务表失败: {e}")
            return
        if not data:
            return
        for t in (data.get("tasks") or []):
            if not isinstance(t, dict) or not t.get("task_id"):
                continue
            # 重启后无 worker：running 任务标记为 interrupted（产出已持久化在项目里）
            status = "interrupted" if t.get("status") == "running" else t.get("status", "interrupted")
            self._tasks[t["task_id"]] = {
                "task_id": t["task_id"],
                "project_id": t.get("project_id", ""),
                "status": status,
                "created_at": t.get("created_at", time.time()),
                "reasoning": "",
                "text": "",
                "status_text": "已中断",
                "tools": [],
                "snapshot": None,
                "done_payload": None,
                "fallback": None,
                "error": "服务重启中断",
                "pending_guidance": [],
                "_subscribers": [],
                "_task": None,
            }


_instance: Optional[AgentTaskManager] = None


def get_agent_task_manager() -> AgentTaskManager:
    """全局单例"""
    global _instance
    if _instance is None:
        _instance = AgentTaskManager()
    return _instance
