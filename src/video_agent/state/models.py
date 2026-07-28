from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone
import time
import random

# 管线模型从 models_pipeline 导入（Phase 4 拆分）
from .models_pipeline import (  # noqa: F401
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

class Phase(str, Enum):
    story = "story"
    storyboard = "storyboard"
    image = "image"
    video = "video"
    audio = "audio"
    edit = "edit"

class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"

class StoryStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"

class ShotType(str, Enum):
    extreme_wide = "extreme_wide"
    wide = "wide"
    medium = "medium"
    close_up = "close_up"
    extreme_close_up = "extreme_close_up"
    over_shoulder = "over_shoulder"
    pov = "pov"

class CameraMovement(str, Enum):
    static = "static"
    pan_left = "pan_left"
    pan_right = "pan_right"
    tilt_up = "tilt_up"
    tilt_down = "tilt_down"
    push_in = "push_in"
    pull_out = "pull_out"
    tracking = "tracking"
    crane = "crane"
    handheld = "handheld"

class Transition(str, Enum):
    cut = "cut"
    fade_in = "fade_in"
    fade_out = "fade_out"
    dissolve = "dissolve"
    wipe = "wipe"

class ShotStatus(str, Enum):
    pending = "pending"
    generating_image = "generating_image"
    image_ready = "image_ready"
    generating_video = "generating_video"
    video_ready = "video_ready"
    failed = "failed"

# =======================
# Models
# =======================

class PlanStep(BaseModel):
    step_id: str
    phase: Phase
    description: str
    status: StepStatus = StepStatus.pending
    depends_on: List[str] = Field(default_factory=list)

class PlanState(BaseModel):
    plan_id: Optional[str] = None
    goal_summary: Optional[str] = None
    style: Optional[str] = None
    duration_seconds: Optional[int] = None
    resolution: Optional[str] = None
    fps: Optional[int] = None
    steps: List[PlanStep] = Field(default_factory=list)

class Dialogue(BaseModel):
    character: str
    line: str
    emotion: Optional[str] = None

class Scene(BaseModel):
    scene_id: str
    scene_number: int
    location: str
    time_of_day: str
    description: str
    dialogue: List[Dialogue] = Field(default_factory=list)
    duration_seconds: float
    mood: Optional[str] = None
    notes: Optional[str] = None

class Character(BaseModel):
    character_id: str
    name: str
    role: str
    description: str
    visual_reference: Optional[str] = None

class StoryState(BaseModel):
    story_id: Optional[str] = None
    title: Optional[str] = None
    genre: Optional[str] = None
    synopsis: Optional[str] = None
    scenes: List[Scene] = Field(default_factory=list)
    characters: List[Character] = Field(default_factory=list)
    status: StoryStatus = StoryStatus.pending

class GenerationConfig(BaseModel):
    image_adapter: Optional[str] = None
    video_adapter: Optional[str] = None
    seed: Optional[int] = None
    guidance_scale: Optional[float] = None
    steps: Optional[int] = None

class Shot(BaseModel):
    shot_id: str
    scene_id: str
    shot_number: int
    shot_type: ShotType
    camera_movement: CameraMovement
    description: str
    visual_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    duration_seconds: float
    transition: Transition = Transition.cut
    audio_cue: Optional[str] = None
    
    image_asset_id: Optional[str] = None
    video_asset_id: Optional[str] = None
    audio_asset_id: Optional[str] = None
    
    generation_config: GenerationConfig = Field(default_factory=GenerationConfig)
    status: ShotStatus = ShotStatus.pending
    retry_count: int = 0

class StoryboardState(BaseModel):
    storyboard_id: Optional[str] = None
    story_id: Optional[str] = None
    shots: List[Shot] = Field(default_factory=list)

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
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    version: str = "2.0.0"
    project_id: str
    project_name: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: ProjectStatus = ProjectStatus.idle
    user_goal: str = ""

    # 原有架构字段（保留以兼容 CLI 和旧 Workflow）
    plan: PlanState = Field(default_factory=PlanState)
    story: StoryState = Field(default_factory=StoryState)
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
    "imgUrl": "",
    "videoUrl": "",
    "prompt": "",
    "model": "",
    "mode": "",
    "aspectRatio": "16:9",
    "resolution": "1080p",
    "duration": "5s",
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
    result: Dict[str, Any] = {"id": draft_id or data.get("id") or f"draft-{int(time.time())}-{random.randint(100, 999)}"}
    for field_name, default in DRAFT_DEFAULT_FIELDS.items():
        value = data.get(field_name)
        # refAssets 需要拷贝列表避免共享引用
        result[field_name] = value if value is not None else (list(default) if isinstance(default, list) else default)
    return result

