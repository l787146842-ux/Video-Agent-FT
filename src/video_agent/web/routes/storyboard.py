"""
/api/storyboard — 故事板 CRUD 端点
管理 StoryGroup 和 DraftRecord 的增删改查。
数据源：StudioStateService（共享 + 持久化）。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import time
import random

from src.video_agent.web.state_service import StudioStateService

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


@router.get("/storyboard/groups")
async def get_groups():
    """返回全部故事板分组"""
    svc = StudioStateService.get_instance()
    return svc.get_groups()


@router.post("/storyboard/groups/{group_id}/drafts")
async def add_draft(group_id: str, body: DraftCreate):
    """给指定分组添加草稿"""
    svc = StudioStateService.get_instance()
    groups = svc.get_groups()

    for category in groups.values():
        for group in category:
            if group["id"] == group_id:
                draft_id = f"draft-{int(time.time())}-{random.randint(100,999)}"
                draft = {
                    "id": draft_id,
                    "label": body.label,
                    "tag": body.tag,
                    "mediaType": body.mediaType,
                    "imgUrl": "",
                    "videoUrl": "",
                    "prompt": body.prompt,
                    "model": body.model,
                    "mode": body.mode,
                    "aspectRatio": body.aspectRatio,
                    "resolution": body.resolution,
                    "duration": body.duration,
                    "timbre": body.timbre,
                    "refAssets": body.refAssets,
                }
                group.setdefault("drafts", []).append(draft)
                svc.save()
                return {"ok": True, "draft_id": draft_id}
    raise HTTPException(status_code=404, detail=f"Group {group_id} not found")


@router.patch("/storyboard/drafts/{draft_id}")
async def update_draft(draft_id: str, body: DraftPatch):
    """更新指定草稿的字段"""
    svc = StudioStateService.get_instance()
    groups = svc.get_groups()
    patch = body.model_dump(exclude_none=True)

    for category in groups.values():
        for group in category:
            for draft in group.get("drafts", []):
                if draft["id"] == draft_id:
                    draft.update(patch)
                    svc.save()
                    return {"ok": True}
    raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
