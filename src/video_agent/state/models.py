from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone

from src.video_agent.utils import gen_id

# 管线模型从 models_pipeline 导入（Phase 4 拆分）
from .models_pipeline import (  # noqa: 1
    AssetType, AssetStatus, AudioCategory,
    TimelineStatus, TaskType, TaskStatus, ErrorLevel,
    AssetState, Clip, Track, TimelineState,
    TaskOutput, TaskState, ErrorState,
    MetadataModelConfig, MetadataPreferences, MetadataCostTracking, MetadataState,
)

# =======================
# 状态 Category 常量（消除硬编码字符串）
# =======================
CAT_KEY_ELEMENTS = "keyElements"
CAT_SHOTS = "shots"
CAT_AUDIO_ITEMS = "audioItems"
ALL_CATEGORIES = [CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS]
ALL_CATEGORIES_TUPLE = (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS)

# 组装阶段客观产物文档名（批 6）：video_assembler 执行器落盘，assembly 阶段
# 完成探针据此区分「已生成未组装」与「已组装」（放 state 层避免 core↔skill_runtime 环）
ASSEMBLY_PLAN_DOC_NAME = "Final_Assembly_Plan.md"

# =======================
# Enums
# =======================
class ProjectStatus(str, Enum):
    idle = "idle"
    planning = "planning"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    paused = "paused"


# =======================
# Studio 前端对齐模型
# =======================

class DraftRecord(BaseModel):
    """对应前端的 draft 概念 — 故事板草稿卡片
    
    JSON 输出使用 camelCase/前端字段名；Python 内部使用 snake_case。
    """
    model_config = ConfigDict(populate_by_name=True)

    draft_id: str = Field(alias="id")
    label: str = "草稿"
    tag: str = "草稿"  # "推荐" | "已确认" | "草稿" | "生成中" | "Agent"
    media_type: str = Field(alias="mediaType", default="image")  # "image" | "video" | "audio"
    gen_type: str = Field(alias="genType", default="")  # 当前选中的生成类型（缺省回退 media_type）
    prompt: str = ""
    provider_id: str = Field(alias="providerId", default="")
    model: str = ""
    mode: str = ""
    aspect_ratio: str = Field(alias="aspectRatio", default="16:9")
    resolution: str = "1080p"
    duration: str = ""
    size: str = ""
    timbre: str = ""
    img_url: str = Field(alias="imgUrl", default="")
    video_url: str = Field(alias="videoUrl", default="")
    audio_url: str = Field(alias="audioUrl", default="")
    ref_assets: List[str] = Field(alias="refAssets", default_factory=list)
    asset_id: Optional[str] = None  # 关联到 AssetState


class KeyElementGroup(BaseModel):
    """关键元素分组（group_type=keyElement）"""
    model_config = ConfigDict(populate_by_name=True)

    group_id: str = Field(alias="id")
    title: str = ""
    description: str = Field(alias="desc", default="")
    drafts: List[DraftRecord] = Field(default_factory=list)


class ShotGroup(BaseModel):
    """分镜分组（group_type=shot）— 含原 Shot 专业字段"""
    model_config = ConfigDict(populate_by_name=True)

    group_id: str = Field(alias="id")
    title: str = ""
    duration: str = ""
    rough_desc: str = Field(alias="roughDesc", default="")
    shot_type: str = Field(alias="shotType", default="")
    camera_movement: str = Field(alias="cameraMovement", default="static")
    scene_refs: List[str] = Field(alias="sceneRefs", default_factory=list)
    transition: str = "cut"
    audio_cue: str = Field(alias="audioCue", default="")
    time_range: str = Field(alias="timeRange", default="")
    generation_config: Dict[str, Any] = Field(alias="generationConfig", default_factory=dict)
    status: str = "pending"  # pending | generating | ready | failed
    linked_scene_id: Optional[str] = Field(alias="linkedSceneId", default=None)
    drafts: List[DraftRecord] = Field(default_factory=list)


class AudioGroup(BaseModel):
    """音频分组（group_type=audio）"""
    model_config = ConfigDict(populate_by_name=True)

    group_id: str = Field(alias="id")
    title: str = ""
    time_range: str = Field(alias="timeRange", default="")
    prompt: str = ""
    drafts: List[DraftRecord] = Field(default_factory=list)


class StoryGroup(BaseModel):
    """统一故事板分组 — §1.1 设计：替代三个分离列表的单一视图。

    group_type 鉴别器：keyElement | shot | audio
    前端 JSON 仍使用 keyElements/shots/audioItems 三列表，
    但后端通过此模型提供统一访问入口。
    """
    model_config = ConfigDict(populate_by_name=True)

    group_id: str = Field(alias="id")
    group_type: str = Field(alias="groupType")  # keyElement | shot | audio
    title: str = ""
    description: str = Field(alias="desc", default="")
    # shot 专属
    shot_type: str = Field(alias="shotType", default="")
    camera_movement: str = Field(alias="cameraMovement", default="static")
    rough_desc: str = Field(alias="roughDesc", default="")
    duration: str = ""
    time_range: str = Field(alias="timeRange", default="")
    transition: str = "cut"
    audio_cue: str = Field(alias="audioCue", default="")
    scene_refs: List[str] = Field(alias="sceneRefs", default_factory=list)
    # 生成配置
    generation_config: Dict[str, Any] = Field(alias="generationConfig", default_factory=dict)
    # 草稿列表
    drafts: List[DraftRecord] = Field(default_factory=list)
    # 状态
    status: str = "pending"
    linked_scene_id: Optional[str] = Field(alias="linkedSceneId", default=None)


class FrontendAsset(BaseModel):
    """前端资产列表中的素材（与 AssetState 职责不同，用于 UI 绑定）"""
    model_config = ConfigDict(populate_by_name=True)

    asset_id: str = Field(alias="id")
    name: str = ""
    asset_type: str = Field(alias="type", default="image")
    is_bound: bool = Field(alias="isBound", default=False)
    url: str = ""


class ChatMessage(BaseModel):
    """Agent 聊天记录"""
    model_config = ConfigDict(populate_by_name=True)

    role: str = Field(alias="sender")  # "user" | "agent"
    content: str = Field(alias="text")
    timestamp: str = ""


class ProjectDocument(BaseModel):
    """项目文档工件（如 Final_Video_Spec.md）"""
    model_config = ConfigDict(populate_by_name=True)

    doc_id: str = Field(alias="id")
    name: str
    content: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class InteractionState(BaseModel):
    """对话式交互运行时状态"""
    model_config = ConfigDict(populate_by_name=True)

    current_phase: str = "idle"        # idle | story | storyboard | image | video | audio | edit
    awaiting_confirmation: bool = False
    confirmation_message: str = ""
    selected_draft_id: str = ""
    selected_type: str = ""


class ProjectState(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    version: str = "2.0.0"
    project_id: str
    project_name: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: ProjectStatus = ProjectStatus.idle
    user_goal: str = ""

    # CLI 遗留 plan/story 字段已清偿（旧模型文件已删除）。
    # ProjectState extra="ignore" 保证旧 state.json 里残留的 plan/story 键加载时
    # 被静默忽略、不报错（2026-08-16 实测：存量文件该两键仅空壳默认值）。
    # 注意：原 storyboard: StoryboardState 已删除，由 key_elements/shots/audio_items 替代（v2.0.0）
    pipeline_assets: List[AssetState] = Field(default_factory=list)  # 生成管线资产（CLI/Workflow 用）
    timeline: TimelineState = Field(default_factory=TimelineState)
    tasks: List[TaskState] = Field(default_factory=list)
    errors: List[ErrorState] = Field(default_factory=list)
    metadata: MetadataState = Field(default_factory=MetadataState)

    # Studio 前端对齐字段（唯一数据源，替代 storyboard.shots）
    key_elements: List[KeyElementGroup] = Field(alias="keyElements", default_factory=list)
    shots: List[ShotGroup] = Field(default_factory=list)
    audio_items: List[AudioGroup] = Field(alias="audioItems", default_factory=list)
    assets: List[FrontendAsset] = Field(default_factory=list)  # 前端素材列表（UI 绑定用）
    chat_history: List[ChatMessage] = Field(alias="chatMessages", default_factory=list)
    documents: List[ProjectDocument] = Field(default_factory=list)
    interaction: InteractionState = Field(default_factory=InteractionState)

    @property
    def story_groups(self) -> List["StoryGroup"]:
        """§1.1 统一故事板视图 — 将三个类型化列表合并为单一 StoryGroup 列表。
        供 Planner/Tool 统一访问，不额外持久化（序列化时仍输出三列表）。
        """
        groups: List[StoryGroup] = []
        for g in self.key_elements:
            groups.append(StoryGroup(
                id=g.group_id, groupType="keyElement", title=g.title, desc=g.description,
                drafts=g.drafts,
            ))
        for g in self.shots:
            groups.append(StoryGroup(
                id=g.group_id, groupType="shot", title=g.title,
                shotType=g.shot_type, cameraMovement=g.camera_movement,
                roughDesc=g.rough_desc, duration=g.duration,
                sceneRefs=g.scene_refs, transition=g.transition,
                audioCue=g.audio_cue, timeRange=g.time_range,
                generationConfig=g.generation_config,
                status=g.status, linkedSceneId=g.linked_scene_id,
                drafts=g.drafts,
            ))
        for g in self.audio_items:
            groups.append(StoryGroup(
                id=g.group_id, groupType="audio", title=g.title,
                timeRange=g.time_range, drafts=g.drafts,
            ))
        return groups


# =======================
# Draft 构建工厂（消除 4 处重复）
# =======================

# Draft 字典的默认字段值
DRAFT_DEFAULT_FIELDS: Dict[str, Any] = {
    "label": "Agent 草稿",
    "tag": "Agent",
    "mediaType": "image",
    "genType": "",
    "imgUrl": "",
    "videoUrl": "",
    "audioUrl": "",
    "prompt": "",
    "providerId": "",
    "model": "",
    "mode": "",
    "aspectRatio": "16:9",
    #分辨率/时长等硬参数唯一来源为顶部「全局设置」，
    # 草稿默认留空，由 stamp_draft_spec_preference 按全局设置补印，
    # 不再用硬编码默认值挡住补印（生成时也不得偏离全局设置）
    "resolution": "",
    "imageResolution": "",
    "duration": "",
    "timbre": "",
    "refAssets": [],
}


def build_draft_dict(data: Optional[Dict[str, Any]] = None, *, draft_id: str = "") -> Dict[str, Any]:
    """统一的 Draft 字典构建工厂。

    从 data 中提取已知字段，缺失的使用默认值。
    所有需要构建 draft dict 的地方都应调用此函数，避免重复。

    Args:
        data: 原始草稿数据（可部分字段缺失）
        draft_id: 显式指定 ID；为空时自动生成

    Returns:
        完整的 draft 字典（含 id 和所有默认字段）
    """
    data = data or {}
    result: Dict[str, Any] = {"id": draft_id or data.get("id") or gen_id("draft")}
    for field_name, default in DRAFT_DEFAULT_FIELDS.items():
        value = data.get(field_name)
        # refAssets 需要拷贝列表避免共享引用
        result[field_name] = value if value is not None else (list(default) if isinstance(default, list) else default)
    return result

