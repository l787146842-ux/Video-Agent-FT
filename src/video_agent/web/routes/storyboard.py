"""
/api/storyboard — 故事板 CRUD 端点
管理 StoryGroup 和 DraftRecord 的增删改查。
数据源：StudioStateService（共享 + 持久化）。
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import time
import random

from src.video_agent.exceptions import VideoAgentError
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import build_draft_dict
from src.video_agent.web.error_payload import LEGACY_NOT_FOUND, LEGACY_VALIDATION_ERROR

router = APIRouter()


class DraftCreate(BaseModel):
    label: str = "Agent 草稿"
    tag: str = "Agent"
    mediaType: str = "image"
    prompt: str = ""
    model: str = ""
    mode: str = ""
    aspectRatio: str = "16:9"
    resolution: str = "1080p"
    duration: str = "5s"
    timbre: str = ""
    refAssets: List[str] = []


class DraftPatch(BaseModel):
    label: Optional[str] = None
    tag: Optional[str] = None
    prompt: Optional[str] = None
    imgUrl: Optional[str] = None
    videoUrl: Optional[str] = None
    model: Optional[str] = None
    mode: Optional[str] = None
    aspectRatio: Optional[str] = None
    resolution: Optional[str] = None
    duration: Optional[str] = None
    timbre: Optional[str] = None
    refAssets: Optional[List[str]] = None


class GroupPatch(BaseModel):
    """用户直接编辑分组字段（不经 Planner，<10ms）"""
    title: Optional[str] = None
    desc: Optional[str] = None
    roughDesc: Optional[str] = None
    duration: Optional[str] = None
    timeRange: Optional[str] = None
    shotType: Optional[str] = None
    sceneRefs: Optional[List[str]] = None
    prompt: Optional[str] = None


@router.get("/storyboard/groups")
async def get_groups():
    """返回全部故事板分组"""
    svc = StateManager.get_instance()
    return svc.get_groups()


@router.post("/storyboard/groups/{group_id}/drafts")
async def add_draft(group_id: str, body: DraftCreate):
    """给指定分组添加草稿"""
    svc = StateManager.get_instance()
    groups = svc.get_groups()

    for category in groups.values():
        for group in category:
            if group["id"] == group_id:
                draft = build_draft_dict(body.model_dump())
                group.setdefault("drafts", []).append(draft)
                await svc.save_async()
                return {"ok": True, "draft_id": draft["id"]}
    raise VideoAgentError(
        f"Group {group_id} not found", status_code=404, error_code=LEGACY_NOT_FOUND
    )


class ReorderRequest(BaseModel):
    category: str  # keyElements | shots | audioItems
    group_ids: List[str]  # 新顺序的 group ID 列表


@router.patch("/storyboard/reorder")
async def reorder_groups(body: ReorderRequest):
    """重排分组顺序（拖拽排序后前端调用）"""
    svc = StateManager.get_instance()
    groups = svc.state_dict.get(body.category)
    if groups is None:
        raise VideoAgentError(
            f"Invalid category: {body.category}",
            status_code=400,
            error_code=LEGACY_VALIDATION_ERROR,
        )

    # 按新顺序重排
    id_to_group = {g["id"]: g for g in groups}
    new_order = [id_to_group[gid] for gid in body.group_ids if gid in id_to_group]
    # 未在列表中的分组追加到末尾（安全兜底）
    remaining = [g for g in groups if g["id"] not in set(body.group_ids)]
    svc.state_dict[body.category] = new_order + remaining
    await svc.save_async()
    return {"ok": True, "count": len(new_order)}


@router.patch("/storyboard/drafts/{draft_id}")
@router.patch("/state/draft/{draft_id}")  # 设计方案 §4.2 路径别名
async def update_draft(draft_id: str, body: DraftPatch):
    """更新指定草稿的字段（用户直接编辑，不经 Planner）"""
    svc = StateManager.get_instance()
    patch = body.model_dump(exclude_none=True)

    # D1 收拢：草稿查找经 StateManager.find_draft 唯一入口（三层循环抄写消灭）
    found = svc.find_draft(draft_id)
    if found is None:
        raise VideoAgentError(
            f"Draft {draft_id} not found", status_code=404, error_code=LEGACY_NOT_FOUND
        )
    _cat, _group, draft = found
    draft.update(patch)
    await svc.save_async()
    return {"ok": True}


@router.patch("/storyboard/groups/{group_id}")
@router.patch("/state/group/{group_id}")  # 设计方案 §4.2 路径别名
async def update_group(group_id: str, body: GroupPatch):
    """更新指定分组的字段（用户直接编辑，不经 Planner，<10ms）"""
    svc = StateManager.get_instance()
    patch = body.model_dump(exclude_none=True)

    # D1 收拢：分组查找经 StateManager.find_group 唯一入口（三层循环抄写消灭）
    found = svc.find_group(group_id)
    if found is None:
        raise VideoAgentError(
            f"Group {group_id} not found", status_code=404, error_code=LEGACY_NOT_FOUND
        )
    _cat, group = found
    group.update(patch)
    await svc.save_async()
    return {"ok": True}
