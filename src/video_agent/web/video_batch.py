"""视频批量生成队列 + 断点续跑（任务级 + 步骤级）。

- 提交即返回 batch_id，worker 后台逐镜提交视频生成（复用 generation.submit_video_task，
  进度事件走既有生成任务 SSE，前端生成日志面板可见）；
- 步骤级断点：每镜落盘 status/error，resume 只重试 failed/pending 镜，已成功镜跳过；
- 任务级断点：批次表持久化 data/video_batch_tasks.json，服务重启后 running → interrupted，
  一键 resume 续跑；
- 服务重启安全：worker 绑定项目快照提交时收集的镜清单（不依赖内存状态）。
"""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.utils import gen_id
from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import DATA_DIR
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_SHOTS

_PERSIST_PATH = DATA_DIR / "video_batch_tasks.json"
_MAX_BATCHES = 50


def _shot_spec(state_dict: Dict[str, Any], group: Dict[str, Any], draft: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "group_id": str(group.get("id") or ""),
        "draft_id": str(draft.get("id") or ""),
        "title": str(group.get("title") or draft.get("label") or draft.get("id") or ""),
        "status": "pending",
        "task_id": "",
        "error": "",
    }


class VideoBatchManager:
    def __init__(self) -> None:
        self._batches: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ---------- 生命周期 ----------

    def create(
        self,
        project_id: str,
        provider_id: str,
        model: str,
        *,
        resolution: str = "",
        duration: int = 0,
        shot_group_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """按当前项目故事板的分镜清单创建批量任务（只收含提示词的镜头）。"""
        from src.video_agent.web.generation import resolve_provider_ref

        self._purge()
        svc = StateManager.get_instance()
        state = svc.state_dict
        shots: List[Dict[str, Any]] = []
        wanted = set(shot_group_ids or [])
        for group in state.get(CAT_SHOTS) or []:
            if not isinstance(group, dict):
                continue
            if wanted and str(group.get("id") or "") not in wanted:
                continue
            for draft in (group.get("drafts") or []):
                if not isinstance(draft, dict):
                    continue
                if not str(draft.get("prompt") or "").strip():
                    continue
                shots.append(_shot_spec(state, group, draft))
        if not shots:
            raise ValueError("故事板没有可生成的分镜（需先拆解分镜并编写提示词）")
        provider_id = resolve_provider_ref(provider_id) or settings.default_video_provider_id
        model = model or settings.default_video_model
        batch_id = gen_id("vb")
        record = {
            "batch_id": batch_id,
            "project_id": project_id,
            "provider_id": provider_id,
            "model": model,
            "resolution": resolution or settings.default_video_resolution,
            "duration": duration or settings.max_shot_duration,
            CAT_SHOTS: shots,
            "status": "running",
            "created_at": time.time(),
            "updated_at": time.time(),
            "done": 0,
            "failed": 0,
        }
        self._batches[batch_id] = record
        self._persist()
        self._spawn_worker(batch_id)
        logger.info(f"[VideoBatch] created {batch_id}: {len(shots)} shots")
        return self.get(batch_id)

    def resume(self, batch_id: str) -> Dict[str, Any]:
        """断点续跑：failed/pending 镜重置为 pending，running → running。"""
        record = self._batches.get(batch_id)
        if not record:
            raise KeyError(f"批次 {batch_id} 不存在")
        if record.get("status") == "running":
            return self.get(batch_id)
        for s in record[CAT_SHOTS]:
            if s.get("status") in ("failed", "pending", "interrupted"):
                s["status"] = "pending"
                s["error"] = ""
        record["status"] = "running"
        record["updated_at"] = time.time()
        self._persist()
        self._spawn_worker(batch_id)
        logger.info(f"[VideoBatch] resumed {batch_id}")
        return self.get(batch_id)

    def cancel(self, batch_id: str) -> bool:
        record = self._batches.get(batch_id)
        if not record:
            return False
        if record.get("status") == "running":
            record["status"] = "cancelled"
            record["updated_at"] = time.time()
            self._persist()
        return True

    def get(self, batch_id: str) -> Dict[str, Any]:
        record = self._batches.get(batch_id)
        if not record:
            raise KeyError(f"批次 {batch_id} 不存在")
        out = {k: v for k, v in record.items()}
        out["total"] = len(out[CAT_SHOTS])
        return out

    def list(self, project_id: str = "") -> List[Dict[str, Any]]:
        out = []
        for r in self._batches.values():
            if project_id and r.get("project_id") != project_id:
                continue
            out.append({
                "batch_id": r["batch_id"], "project_id": r["project_id"],
                "status": r["status"], "done": r["done"], "failed": r["failed"],
                "total": len(r[CAT_SHOTS]), "created_at": r["created_at"],
            })
        return sorted(out, key=lambda x: x["created_at"], reverse=True)

    # ---------- worker ----------

    async def _run_worker(self, batch_id: str) -> None:
        from src.video_agent.web.generation import collect_shot_video_refs, submit_video_task

        record = self._batches.get(batch_id)
        if not record:
            return
        svc = StateManager.get_instance()
        state = svc.state_dict
        shots_by_draft = {}
        for group in state.get(CAT_SHOTS) or []:
            if not isinstance(group, dict):
                continue
            for draft in (group.get("drafts") or []):
                if isinstance(draft, dict):
                    shots_by_draft[str(draft.get("id") or "")] = (group, draft)
        try:
            for shot in record[CAT_SHOTS]:
                if record.get("status") not in ("running",):
                    break
                if shot.get("status") != "pending":
                    continue
                pair = shots_by_draft.get(shot["draft_id"])
                if pair is None:
                    shot["status"] = "failed"
                    shot["error"] = "镜头草稿不存在（可能已被删除）"
                    record["failed"] += 1
                    self._touch(record)
                    continue
                group, draft = pair
                shot["status"] = "running"
                self._touch(record)
                try:
                    image_refs, audio_refs = collect_shot_video_refs(state, group, draft)
                    task_id = submit_video_task(
                        state, draft, "shot", record["provider_id"], record["model"],
                        duration=int(record.get("duration") or settings.max_shot_duration),
                        resolution=record.get("resolution") or settings.default_video_resolution,
                        aspect_ratio=str(draft.get("videoAspectRatio") or draft.get("aspectRatio") or "16:9"),
                        image_refs=image_refs, audio_refs=audio_refs,
                        source="batch",
                    )
                    shot["task_id"] = task_id
                    # 提交即视为排队成功；最终成败由生成任务写回草稿 videoUrl，
                    # 批次状态以「提交成功」计（失败镜 resume 重试）
                    shot["status"] = "succeeded"
                    record["done"] += 1
                except Exception as e:
                    shot["status"] = "failed"
                    shot["error"] = str(e)[:200]
                    record["failed"] += 1
                    logger.warning(f"[VideoBatch] {batch_id} shot {shot['draft_id']} 提交失败: {e}")
                self._touch(record)
                await asyncio.sleep(0.5)  # 逐镜间隔，防供应商并发限流
        except asyncio.CancelledError:
            record["status"] = "interrupted"
            self._touch(record)
            raise
        finally:
            if record.get("status") == "running":
                record["status"] = "done" if record["failed"] == 0 else "partial"
                self._touch(record)
                logger.info(
                    f"[VideoBatch] {batch_id} finished: {record['done']} ok / {record['failed']} failed"
                )

    def _spawn_worker(self, batch_id: str) -> None:
        """启动后台 worker；无运行中事件循环（测试/同步上下文）时静默跳过，
        由调用方显式驱动 _run_worker。"""
        try:
            asyncio.get_running_loop().create_task(self._run_worker(batch_id))
        except RuntimeError as _e:
            logger.debug("[video_batch] 忽略异常: {}", _e)

    def _touch(self, record: Dict[str, Any]) -> None:
        record["updated_at"] = time.time()
        self._persist()

    # ---------- 持久化 ----------

    def _persist(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload = {"batches": [
                {k: v for k, v in r.items() if k != "_task"} for r in self._batches.values()
            ]}
            atomic_write_text(_PERSIST_PATH, json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"[VideoBatch] 批次表落盘失败: {e}")

    def _load(self) -> None:
        try:
            if not _PERSIST_PATH.exists():
                return
            data = json.loads(_PERSIST_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[VideoBatch] 恢复批次表失败: {e}")
            return
        for r in (data.get("batches") or []):
            if not isinstance(r, dict) or not r.get("batch_id"):
                continue
            if r.get("status") == "running":
                r["status"] = "interrupted"  # 服务重启：无 worker，续跑入口 resume
            r.setdefault("done", 0)
            r.setdefault("failed", 0)
            self._batches[r["batch_id"]] = r

    def _purge(self) -> None:
        now = time.time()
        stale = [
            bid for bid, r in self._batches.items()
            if r.get("status") != "running" and now - r.get("created_at", now) > 7 * 86400
        ]
        for bid in stale:
            self._batches.pop(bid, None)
        if len(self._batches) > _MAX_BATCHES:
            done_sorted = sorted(
                (bid for bid, r in self._batches.items() if r.get("status") != "running"),
                key=lambda bid: self._batches[bid].get("created_at", 0),
                reverse=True,
            )
            for bid in done_sorted[_MAX_BATCHES:]:
                self._batches.pop(bid, None)


_instance: Optional[VideoBatchManager] = None


def get_video_batch_manager() -> VideoBatchManager:
    global _instance
    if _instance is None:
        _instance = VideoBatchManager()
    return _instance
