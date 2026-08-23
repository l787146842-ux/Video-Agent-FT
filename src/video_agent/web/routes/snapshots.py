"""B11：对话分支 / 工作流快照。

- 快照 = 当前对话消息 + 状态快照 + trace 引用的不可变副本
  （workspace/snapshots/<project>/<snap_id>.json）；
- 分支 = 从快照派生新对话（消息装载进新对话，原对话与当前状态不动——
  非破坏性；状态回滚属危险操作，另行走版本账本）；
- 快照列表可预览/删除。
"""
import json
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.utils import gen_id
from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import WORKSPACE_DIR
from src.video_agent.web.error_payload import classify_legacy_code

router = APIRouter()

# 文件名编码的创建时间戳：snap_id 形如 snap-<unix_ts>-<rand>（gen_id 约定），
# 淘汰排序直接解析文件名，免全量反序列化快照正文（性能优化）；
# 解析失败（存量手工文件/改名等）回落读正文 created_at，再失败视为最旧。
_TS_FROM_STEM_RE = re.compile(r"^snap-(\d+)-[0-9a-f]+$")


def _snap_dir(project_id: str):
    d = WORKSPACE_DIR / "snapshots" / (project_id or "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pinned_index(d) -> set:
    """pinned 旁路索引（snap_id 集合）：淘汰豁免名单，免反序列化正文。"""
    f = d / "_pinned.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return {str(x) for x in data} if isinstance(data, list) else set()
    except Exception:
        return set()


def _save_pinned_index(d, ids: set) -> None:
    atomic_write_text(d / "_pinned.json", json.dumps(sorted(ids), ensure_ascii=False))


def _snap_files(d) -> List:
    """快照文件清单（排除 `_` 前缀的旁路索引文件）。"""
    return [f for f in d.glob("*.json") if not f.name.startswith("_")]


def _created_at_for(f, fallback_read: bool = True) -> float:
    """快照创建时间：优先文件名编码（零反序列化），回落正文 created_at，
    再失败（损坏/缺字段）返回 0.0 = 视为最旧优先淘汰（既有兜底语义）。"""
    m = _TS_FROM_STEM_RE.match(f.stem)
    if m:
        return float(m.group(1))
    if not fallback_read:
        return 0.0
    try:
        return float(json.loads(f.read_text(encoding="utf-8")).get("created_at") or 0.0)
    except Exception:
        return 0.0


def _prune_snapshots(project_id: str) -> List[str]:
    """每项目快照数量上限（默认 20，SNAPSHOT_MAX_PER_PROJECT 可配）。

    超限淘汰最旧（按创建时间升序）：pinned 快照豁免淘汰；其余「最新优先
    保留」。淘汰在创建成功后执行，新快照永不被当次淘汰。
    返回被淘汰的快照 id 清单（create 响应带回，前端据此提示用户）。
    """
    cap = max(1, int(settings.snapshot_max_per_project))
    d = _snap_dir(project_id)
    pinned = _pinned_index(d)
    entries = [(f, _created_at_for(f)) for f in _snap_files(d)]
    # 旁路索引陈腐清理：指向已不存在文件的 pinned 条目随本次淘汰一并清除
    existing_stems = {f.stem for f, _ in entries}
    if pinned - existing_stems:
        pinned &= existing_stems
        _save_pinned_index(d, pinned)
    evictable = [(f, ts) for f, ts in entries if f.stem not in pinned]
    removed_ids: List[str] = []
    over = len(entries) - cap
    for f, _ts in sorted(evictable, key=lambda e: (e[1], e[0].name)):
        if over <= 0:
            break
        try:
            f.unlink()
            removed_ids.append(f.stem)
            over -= 1
            logger.info(f"[Snapshot] 超出上限（{cap}），已淘汰最旧快照 {f.stem}")
        except OSError as e:
            logger.warning(f"[Snapshot] 淘汰快照失败 {f.name}: {e}")
    return removed_ids


def _read_snapshot(project_id: str, snap_id: str) -> Dict[str, Any]:
    f = _snap_dir(project_id) / f"{snap_id}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="快照不存在")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"快照读取失败: {e}")


class BranchRequest(BaseModel):
    title: str = ""


class SnapshotRequest(BaseModel):
    # 分叉点截断（任务 #16）：提供时快照仅含 messages[:up_to_index+1]（含该条）；
    # 不提供时全量快照（既有调用零行为变化）
    up_to_index: Optional[int] = None
    # pinned：豁免数量上限淘汰（手动创建时可带；默认 false）
    pinned: bool = False


@router.get("/conversations/snapshots")
async def list_snapshots():
    """列出当前项目全部快照（元信息，不含全文）。"""
    svc = StateManager.get_instance()
    pid = svc.active_project_id or ""
    d = _snap_dir(pid)
    pinned = _pinned_index(d)
    out: List[Dict[str, Any]] = []
    for f in sorted(_snap_files(d), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "snap_id": data.get("snap_id"),
                "title": data.get("title"),
                "message_count": len(data.get("messages") or []),
                "created_at": data.get("created_at"),
                "pinned": bool(data.get("pinned")) or f.stem in pinned,
            })
        except Exception:
            continue
    return {"snapshots": out}


@router.post("/conversations/snapshot")
async def create_snapshot(body: SnapshotRequest = SnapshotRequest()):
    """把当前活跃对话打为不可变快照（消息 + 状态 + trace 引用）。

    up_to_index（可选，分叉点）：仅截取至该索引（含）；越界/为负返回 400
    结构化错误。派生分支接口不变：分支装载快照内的全部消息。
    """
    svc = StateManager.get_instance()
    async with svc.lock:
        payload = svc.list_conversations()
    active = next(
        (c for c in payload.get("conversations") or [] if c.get("id") == payload.get("active_conversation_id")),
        None,
    )
    if active is None:
        raise HTTPException(status_code=400, detail="没有可快照的对话")
    messages = list(active.get("messages") or [])
    if body.up_to_index is not None:
        if body.up_to_index < 0 or body.up_to_index >= len(messages):
            msg = f"up_to_index 越界：{body.up_to_index}（当前对话共 {len(messages)} 条消息）"
            return JSONResponse(
                status_code=400,
                content=classify_legacy_code("SNAPSHOT_INDEX_OUT_OF_RANGE", msg).http_body(
                    "SNAPSHOT_INDEX_OUT_OF_RANGE"),
            )
        messages = messages[: body.up_to_index + 1]
    snap_id = gen_id("snap")
    record = {
        "snap_id": snap_id,
        "project_id": svc.active_project_id or "",
        "title": str(active.get("title") or "工作流快照"),
        "messages": messages,
        "state": svc.get_full_snapshot(),
        "created_at": time.time(),
        "pinned": bool(body.pinned),
    }
    d = _snap_dir(record["project_id"])
    f = d / f"{snap_id}.json"
    atomic_write_text(f, json.dumps(record, ensure_ascii=False))
    if body.pinned:
        _save_pinned_index(d, _pinned_index(d) | {snap_id})
    # 淘汰对用户可见：清单随响应带回，前端非空即 toast 提示
    pruned = _prune_snapshots(record["project_id"])
    logger.info(f"[Snapshot] 已创建快照 {snap_id}（{len(record['messages'])} 条消息）")
    return {"snap_id": snap_id, "title": record["title"], "pruned": pruned}


@router.get("/conversations/snapshots/{snap_id}")
async def get_snapshot(snap_id: str):
    """查看快照详情（消息 + 状态）。"""
    svc = StateManager.get_instance()
    return _read_snapshot(svc.active_project_id or "", snap_id)


@router.post("/conversations/snapshots/{snap_id}/branch")
async def branch_snapshot(snap_id: str, body: BranchRequest):
    """从快照派生新对话（分支）：消息装载进新对话并设为活跃；当前状态不动。"""
    svc = StateManager.get_instance()
    snap = _read_snapshot(svc.active_project_id or "", snap_id)
    async with svc.lock:
        payload = svc.create_conversation(body.title or f"{snap.get('title', '分支')} · 分支")
        conv_id = payload.get("active_conversation_id") or ""
        convs = svc.state_dict.setdefault("conversations", [])
        for c in convs:
            if c.get("id") == conv_id:
                c["messages"] = list(snap.get("messages") or [])
                c["title"] = body.title or f"{snap.get('title', '分支')} · 分支"
                c.setdefault("_meta", {})["branched_from"] = snap_id
                break
        svc.save()
    logger.info(f"[Snapshot] 从 {snap_id} 派生分支对话 {conv_id}")
    # E-2 消息单一来源：响应只含元信息，分支消息由前端经
    # GET /conversations/{conv_id}/messages 装载
    return svc.conversations_meta_payload()


@router.delete("/conversations/snapshots/{snap_id}")
async def delete_snapshot(snap_id: str):
    """删除快照（不影响任何对话）。"""
    svc = StateManager.get_instance()
    d = _snap_dir(svc.active_project_id or "")
    f = d / f"{snap_id}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="快照不存在")
    f.unlink()
    pinned = _pinned_index(d)
    if snap_id in pinned:
        _save_pinned_index(d, pinned - {snap_id})
    return {"ok": True}
