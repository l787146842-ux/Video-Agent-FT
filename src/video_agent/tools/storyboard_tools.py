"""
故事板操作 Tool 集 — 将 studio-actions 映射为标准 Tool（Rule2: 统一接口）。

每个 Tool 对应一个前端故事板操作，内部通过 StudioStateService 修改状态。
后续 Phase 将迁移为直接操作 StateManager。
"""
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from loguru import logger

from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ALL_CATEGORIES_TUPLE
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.web.prompt_refs import media_of_draft


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


class MediaToChatInput(BaseModel):
    draft_ids: List[str] = Field(default_factory=list, description="要插入的草稿 ID 数组（与 target 二选一，优先）")
    target: str = Field("", description="批量目标: current | all | all_keyElements | all_shots | all_audio")
    media_type: str = Field("", description="媒体类型过滤: image | video | audio（可选）")
    limit: int = Field(0, description="插入数量上限（0 = 系统默认）")


class ReadDraftInput(BaseModel):
    draft_id: str = Field(..., description="草稿编号（如 '1-2' 表示第 1 组第 2 张卡）或草稿 ID")
    draft_type: str = Field("", description="草稿类型: keyElement | shot | audio（编号在各类别独立计数，建议指定以消除歧义）")


# ---------- Tool 实现 ----------

class StoryboardCreateGroupTool(BaseTool):
    name = "storyboard_create_group"
    description = "创建新的故事板分组（关键元素/分镜/音频），可附带草稿"

    def get_input_schema(self) -> Type[BaseModel]:
        return CreateGroupInput

    async def aexecute(self, params: CreateGroupInput) -> ToolResult:
        svc = StateManager.get_instance()
        cat_key = ops.category_for_group_type(params.group_type)

        new_id = ops.new_group_id(cat_key)
        new_group: Dict[str, Any] = {"id": new_id, "title": params.title, "desc": params.desc, "drafts": []}

        if cat_key == CAT_SHOTS:
            new_group["roughDesc"] = params.rough_desc or params.desc
            new_group["duration"] = params.duration or "5s"
            new_group["shotType"] = params.shot_type
            new_group["sceneRefs"] = params.scene_refs

        async with svc.lock:
            svc.state_dict.setdefault(cat_key, []).append(new_group)

            # 附带草稿
            if params.draft and isinstance(params.draft, dict):
                ops.append_draft(new_group, params.draft)

            svc.save()
        return ToolResult(success=True, data={"group_id": new_id})


class StoryboardPatchDraftTool(BaseTool):
    name = "storyboard_patch_draft"
    description = "修改指定草稿的字段（提示词、标签、模型等）"

    def get_input_schema(self) -> Type[BaseModel]:
        return PatchDraftInput

    async def aexecute(self, params: PatchDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        async with svc.lock:
            found = ops.find_draft(svc.state_dict, params.draft_id, params.draft_type)
            if found:
                _, draft = found
                # 统一白名单（含 imageResolution/genType，与文本轨一致）
                if ops.patch_draft(draft, params.patch):
                    svc.save()
                    return ToolResult(success=True, data={"draft_id": draft.get("id", params.draft_id)})
        return ToolResult(success=False, error=f"Draft '{params.draft_id}' not found")


class StoryboardAddDraftTool(BaseTool):
    name = "storyboard_add_draft"
    description = "给指定分组新增一个草稿卡片"

    def get_input_schema(self) -> Type[BaseModel]:
        return AddDraftInput

    async def aexecute(self, params: AddDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        async with svc.lock:
            target_group = ops.find_group(svc.state_dict, params.group_id, params.group_type)
            if not target_group:
                return ToolResult(success=False, error=f"Group '{params.group_id}' not found")

            draft = ops.append_draft(target_group, params.draft)
            svc.save()
        return ToolResult(success=True, data={"draft_id": draft["id"]})


class StoryboardDeleteGroupTool(BaseTool):
    name = "storyboard_delete_group"
    description = "删除整个故事板分组（含其全部草稿）"

    def get_input_schema(self) -> Type[BaseModel]:
        return DeleteGroupInput

    async def aexecute(self, params: DeleteGroupInput) -> ToolResult:
        svc = StateManager.get_instance()

        async with svc.lock:
            if ops.delete_group(svc.state_dict, params.group_id, params.group_type):
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

        async with svc.lock:
            found = ops.find_draft(svc.state_dict, params.draft_id, params.draft_type)
            if found:
                _, draft = found
                ops.patch_draft(draft, {"tag": "已确认"})
                svc.save()
                return ToolResult(success=True, data={"draft_id": draft.get("id", params.draft_id), "tag": "已确认"})
        return ToolResult(success=False, error=f"Draft '{params.draft_id}' not found")


class StoryboardMediaToChatTool(BaseTool):
    name = "storyboard_media_to_chat"
    description = (
        "把故事板草稿卡片里的媒体（图片/视频/音频）自动添加到右侧 Agent 对话输入框，"
        "供用户确认后发送。不修改故事板状态。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return MediaToChatInput

    async def aexecute(self, params: MediaToChatInput) -> ToolResult:
        svc = StateManager.get_instance()
        media_type = params.media_type.lower().strip()
        if media_type not in ("", "image", "video", "audio"):
            media_type = ""
        limit = params.limit or settings.max_chat_inserts
        limit = min(limit, settings.max_chat_inserts)

        state = svc.state_dict
        pairs: List[tuple] = []
        if params.draft_ids:
            for did in params.draft_ids:
                for cat_key in ALL_CATEGORIES_TUPLE:
                    for group in state.get(cat_key, []):
                        for draft in group.get("drafts", []):
                            if draft.get("id") == did:
                                pairs.append((group, draft))
        else:
            target = (params.target or "").lower()
            cat_keys = {
                "all_keyelements": (CAT_KEY_ELEMENTS,),
                "all_shots": (CAT_SHOTS,),
                "all_audio": (CAT_AUDIO_ITEMS,),
                "all": ALL_CATEGORIES_TUPLE,
            }.get(target, ())
            for cat_key in cat_keys:
                for group in state.get(cat_key, []):
                    for draft in group.get("drafts", []):
                        pairs.append((group, draft))

        inserts: List[Dict[str, Any]] = []
        seen = set()
        for group, draft in pairs:
            if len(inserts) >= limit:
                break
            url, kind = media_of_draft(draft)
            if not url or url in seen:
                continue
            if media_type and kind != media_type:
                continue
            seen.add(url)
            inserts.append({
                "kind": kind,
                "url": url,
                "name": draft.get("label") or group.get("title") or draft.get("id", ""),
                "thumb": (draft.get("imgUrl") or "") if kind == "video" else "",
            })

        if not inserts:
            return ToolResult(success=False, error="没有找到带媒体的目标草稿")
        return ToolResult(success=True, data={"chat_inserts": inserts})


class StoryboardReadDraftTool(BaseTool):
    name = "read_draft"
    description = (
        "按需读取指定故事板草稿卡的提示词全文。上下文里草稿只有目录信息（编号/label/字数），"
        "审阅或修改提示词前必须先调用本工具读取全文；触发生成时系统会自动取提示词，无需先读。"
        "draft_id 支持「组号-卡序号」编号（如 '1-2'），编号在关键元素/分镜/音频各类别独立从 1 计数。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadDraftInput

    async def aexecute(self, params: ReadDraftInput) -> ToolResult:
        svc = StateManager.get_instance()
        wanted = (params.draft_id or "").strip()
        matches = ops.find_draft_matches(svc.state_dict, wanted, params.draft_type)
        if not matches:
            return ToolResult(
                success=False,
                error=f"未找到草稿「{wanted}」。编号格式为「组号-卡序号」（如 '1-2'），"
                      f"各类别（关键元素/分镜/音频）独立从 1 计数，可传 draft_type 消除歧义",
            )
        # 全文上限截断（与其他 read_* 工具一致，防单次返回撑爆上下文）
        max_chars = settings.max_doc_chars
        for m in matches:
            if len(m["prompt"]) > max_chars:
                m["prompt"] = m["prompt"][:max_chars] + f"\n……（提示词超长，已截断为前 {max_chars} 字）"
        # 同编号在多类别重复时全部返回，由模型确认具体目标
        return ToolResult(success=True, data={"drafts": matches})


# ---------- 注册 ----------

def register_storyboard_tools():
    """注册所有故事板 Tool 到 ToolManager"""
    from src.video_agent.tools.manager import ToolManager
    ToolManager.register(StoryboardCreateGroupTool())
    ToolManager.register(StoryboardPatchDraftTool())
    ToolManager.register(StoryboardAddDraftTool())
    ToolManager.register(StoryboardDeleteGroupTool())
    ToolManager.register(StoryboardConfirmDraftTool())
    ToolManager.register(StoryboardMediaToChatTool())
    ToolManager.register(StoryboardReadDraftTool())
    logger.info("[Tools] 7 storyboard tools registered")
