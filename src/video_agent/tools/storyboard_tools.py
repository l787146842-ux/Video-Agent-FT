"""
故事板操作 Tool 集 — 将 studio-actions 映射为标准 Tool（Rule2: 统一接口）。

每个 Tool 对应一个前端故事板操作，内部通过 StudioStateService 修改状态。
后续 Phase 将迁移为直接操作 StateManager。
"""
import time
import random
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from loguru import logger

from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import build_draft_dict, CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ALL_CATEGORIES_TUPLE


# ---------- Input Schemas ----------

class CreateGroupInput(BaseModel):
    group_type: str = Field(..., description="分组类型: keyElement | shot | audio")
    title: str = Field(..., description="分组标题")
    desc: str = Field("", description="分组描述")
    duration: str = Field("", description="时长（shot 类型用）")
    rough_desc: str = Field("", description="粗略描述（shot 类型用）")
    shot_type: str = Field("", description="镜头语言（shot 类型用）")
    scene_refs: List[str] = Field(default_factory=list, description="引用的关键元素标题数组")
    draft: Optional[Dict[str, Any]] = Field(None, description="附带草稿（可选）")


class PatchDraftInput(BaseModel):
    draft_id: str = Field(..., description="草稿 ID 或 'current'")
    draft_type: str = Field("", description="草稿类型: keyElement | shot | audio")
    patch: Dict[str, Any] = Field(..., description="要更新的字段字典")


class AddDraftInput(BaseModel):
    group_id: str = Field("current", description="目标分组 ID 或 'current'")
    group_type: str = Field("", description="分组类型")
    draft: Dict[str, Any] = Field(..., description="新草稿数据")


class DeleteGroupInput(BaseModel):
    group_id: str = Field(..., description="要删除的分组 ID")
    group_type: str = Field("", description="分组类型")


class ConfirmDraftInput(BaseModel):
    draft_id: str = Field("current", description="草稿 ID 或 'current'")
    draft_type: str = Field("", description="草稿类型")


# ---------- Tool 实现 ----------

class StoryboardCreateGroupTool(BaseTool):
    name = "storyboard_create_group"
    description = "创建新的故事板分组（关键元素/分镜/音频），可附带草稿"

    def get_input_schema(self) -> Type[BaseModel]:
        return CreateGroupInput

    async def aexecute(self, params: CreateGroupInput) -> ToolResult:
        svc = StateManager.get_instance()

        cat_map = {"keyelement": CAT_KEY_ELEMENTS, "shot": CAT_SHOTS, "audio": CAT_AUDIO_ITEMS}
        cat_key = cat_map.get(params.group_type.lower(), CAT_KEY_ELEMENTS)

        new_id = f"{'shot' if cat_key == 'shots' else 'ke' if cat_key == 'keyElements' else 'audio'}-{int(time.time())}-{random.randint(100, 999)}"
        new_group: Dict[str, Any] = {"id": new_id, "title": params.title, "desc": params.desc, "drafts": []}

        if cat_key == CAT_SHOTS:
            new_group["roughDesc"] = params.rough_desc or params.desc
            new_group["duration"] = params.duration or "5s"
            new_group["shotType"] = params.shot_type
            new_group["sceneRefs"] = params.scene_refs

        svc.state_dict.setdefault(cat_key, []).append(new_group)

        # 附带草稿
        if params.draft and isinstance(params.draft, dict):
            new_group["drafts"].append(build_draft_dict(params.draft))

        svc.save()
        return ToolResult(success=True, data={"group_id": new_id})


class StoryboardPatchDraftTool(BaseTool):
    name = "storyboard_patch_draft"
    description = "修改指定草稿的字段（提示词、标签、模型等）"

    def get_input_schema(self) -> Type[BaseModel]:
        return PatchDraftInput

    async def aexecute(self, params: PatchDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        allowed = [
            "label", "tag", "mediaType", "imgUrl", "videoUrl", "prompt", "mode",
            "model", "providerId", "resolution", "duration", "aspectRatio",
            "size", "timbre", "refAssets",
        ]
        for cat_key in ALL_CATEGORIES_TUPLE:
            for group in svc.state_dict.get(cat_key, []):
                for draft in group.get("drafts", []):
                    if draft.get("id") == params.draft_id:
                        changed = False
                        for field in allowed:
                            if field in params.patch:
                                draft[field] = params.patch[field]
                                changed = True
                        if changed:
                            svc.save()
                            return ToolResult(success=True, data={"draft_id": params.draft_id})
        return ToolResult(success=False, error=f"Draft '{params.draft_id}' not found")


class StoryboardAddDraftTool(BaseTool):
    name = "storyboard_add_draft"
    description = "给指定分组新增一个草稿卡片"

    def get_input_schema(self) -> Type[BaseModel]:
        return AddDraftInput

    async def aexecute(self, params: AddDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        # 查找目标分组
        target_group = None
        for cat_key in ALL_CATEGORIES_TUPLE:
            for group in svc.state_dict.get(cat_key, []):
                if group.get("id") == params.group_id:
                    target_group = group
                    break
            if target_group:
                break
        
        if not target_group:
            # 兆底：取第一个可用分组
            for cat_key in ALL_CATEGORIES_TUPLE:
                groups = svc.state_dict.get(cat_key, [])
                if groups:
                    target_group = groups[0]
                    break

        if not target_group:
            return ToolResult(success=False, error="No group available to add draft")

        draft = build_draft_dict(params.draft)
        target_group.setdefault("drafts", []).append(draft)
        svc.save()
        return ToolResult(success=True, data={"draft_id": draft["id"]})


class StoryboardDeleteGroupTool(BaseTool):
    name = "storyboard_delete_group"
    description = "删除整个故事板分组（含其全部草稿）"

    def get_input_schema(self) -> Type[BaseModel]:
        return DeleteGroupInput

    async def aexecute(self, params: DeleteGroupInput) -> ToolResult:
        svc = StateManager.get_instance()

        for cat_key in ALL_CATEGORIES_TUPLE:
            groups = svc.state_dict.get(cat_key, [])
            for i, g in enumerate(groups):
                if g.get("id") == params.group_id:
                    groups.pop(i)
                    svc.save()
                    return ToolResult(success=True, data={"deleted": params.group_id})
        return ToolResult(success=False, error=f"Group '{params.group_id}' not found")


class StoryboardConfirmDraftTool(BaseTool):
    name = "storyboard_confirm_draft"
    description = "将指定草稿标记为「已确认」"

    def get_input_schema(self) -> Type[BaseModel]:
        return ConfirmDraftInput

    async def aexecute(self, params: ConfirmDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        for cat_key in ALL_CATEGORIES_TUPLE:
            for group in svc.state_dict.get(cat_key, []):
                for draft in group.get("drafts", []):
                    if draft.get("id") == params.draft_id:
                        draft["tag"] = "已确认"
                        svc.save()
                        return ToolResult(success=True, data={"draft_id": params.draft_id, "tag": "已确认"})
        return ToolResult(success=False, error=f"Draft '{params.draft_id}' not found")


# ---------- 注册 ----------

def register_storyboard_tools():
    """注册所有故事板 Tool 到 ToolManager"""
    from src.video_agent.tools.manager import ToolManager
    ToolManager.register(StoryboardCreateGroupTool())
    ToolManager.register(StoryboardPatchDraftTool())
    ToolManager.register(StoryboardAddDraftTool())
    ToolManager.register(StoryboardDeleteGroupTool())
    ToolManager.register(StoryboardConfirmDraftTool())
    logger.info("[Tools] 5 storyboard tools registered")
