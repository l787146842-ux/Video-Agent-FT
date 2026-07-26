from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

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

class AssetType(str, Enum):
    image = "image"
    video = "video"
    audio = "audio"
    subtitle = "subtitle"
    project_file = "project_file"

class AssetStatus(str, Enum):
    generating = "generating"
    ready = "ready"
    failed = "failed"
    deleted = "deleted"

class AudioCategory(str, Enum):
    bgm = "bgm"
    sfx = "sfx"
    dialogue = "dialogue"
    foley = "foley"

class TimelineStatus(str, Enum):
    draft = "draft"
    rendering = "rendering"
    completed = "completed"
    failed = "failed"

class TaskType(str, Enum):
    generate_image = "generate_image"
    generate_video = "generate_video"
    generate_audio = "generate_audio"
    img2video = "img2video"
    edit_compose = "edit_compose"
    upscale = "upscale"
    retry = "retry"

class TaskStatus(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class ErrorLevel(str, Enum):
    warning = "warning"
    error = "error"
    fatal = "fatal"

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

class AssetState(BaseModel):
    asset_id: str
    type: AssetType
    source_shot_id: Optional[str] = None
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    format: Optional[str] = None
    
    # Image/Video specific
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None
    fps: Optional[float] = None
    
    # Audio specific
    category: Optional[AudioCategory] = None
    sample_rate: Optional[int] = None
    
    adapter_used: Optional[str] = None
    generation_params: Dict[str, Any] = Field(default_factory=dict)
    
    version: int = 1
    is_approved: bool = False
    created_at: Optional[datetime] = None
    status: AssetStatus = AssetStatus.generating

class Clip(BaseModel):
    clip_id: str
    asset_id: Optional[str] = None
    start_time: float
    end_time: float
    
    # Video details
    transition_in: Optional[Transition] = None
    transition_out: Optional[Transition] = None
    speed: float = 1.0
    filters: List[str] = Field(default_factory=list)
    
    # Audio details
    volume: float = 1.0
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0
    
    # Subtitle details
    text: Optional[str] = None
    style: Optional[str] = None

class Track(BaseModel):
    track_id: str
    type: AssetType
    clips: List[Clip] = Field(default_factory=list)

class TimelineState(BaseModel):
    timeline_id: Optional[str] = None
    total_duration_seconds: float = 0.0
    tracks: List[Track] = Field(default_factory=list)
    export_config: Dict[str, Any] = Field(default_factory=dict)
    status: TimelineStatus = TimelineStatus.draft

class TaskOutput(BaseModel):
    asset_id: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

class TaskState(BaseModel):
    task_id: str
    type: TaskType
    shot_id: Optional[str] = None
    adapter: Optional[str] = None
    priority: int = 1
    status: TaskStatus = TaskStatus.pending
    progress: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    output: TaskOutput = Field(default_factory=TaskOutput)
    error: Optional[str] = None

class ErrorState(BaseModel):
    error_id: str
    task_id: Optional[str] = None
    timestamp: datetime
    level: ErrorLevel = ErrorLevel.error
    phase: Phase
    adapter: Optional[str] = None
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None

class MetadataModelConfig(BaseModel):
    llm: Optional[str] = None
    image_default: Optional[str] = None
    video_default: Optional[str] = None
    audio_default: Optional[str] = None

class MetadataPreferences(BaseModel):
    auto_approve: bool = False
    max_retries: int = 3
    parallel_tasks: int = 2
    quality_threshold: float = 0.7

class MetadataCostTracking(BaseModel):
    total_api_calls: int = 0
    total_cost_usd: float = 0.0
    breakdown: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

class MetadataState(BaseModel):
    user_id: Optional[str] = None
    workspace_dir: Optional[str] = None
    output_dir: Optional[str] = None
    ai_model_config: MetadataModelConfig = Field(default_factory=MetadataModelConfig, alias="model_config")
    preferences: MetadataPreferences = Field(default_factory=MetadataPreferences)
    cost_tracking: MetadataCostTracking = Field(default_factory=MetadataCostTracking)
    tags: List[str] = Field(default_factory=list)
    created_by: Optional[str] = None

# =======================
# Studio 前端对齐模型
# =======================

class DraftRecord(BaseModel):
    """对应前端的 draft 概念 — 故事板草稿卡片"""
    draft_id: str
    label: str = "草稿"
    tag: str = "草稿"  # "推荐" | "已确认" | "草稿" | "生成中" | "Agent"
    media_type: str = "image"  # "image" | "video" | "audio"
    prompt: str = ""
    provider_id: str = ""
    model: str = ""
    mode: str = ""
    aspect_ratio: str = "16:9"
    resolution: str = "1080p"
    duration: str = ""
    size: str = ""
    timbre: str = ""
    img_url: str = ""
    video_url: str = ""
    ref_assets: List[str] = Field(default_factory=list)
    asset_id: Optional[str] = None  # 关联到 AssetState


class StoryGroup(BaseModel):
    """故事板分组（关键元素 / 分镜 / 音频）"""
    group_id: str
    group_type: str  # "keyElement" | "shot" | "audio"
    title: str
    description: str = ""
    duration: str = ""
    time_range: str = ""
    rough_desc: str = ""
    prompt: str = ""
    drafts: List[DraftRecord] = Field(default_factory=list)


class ChatMessage(BaseModel):
    """Agent 聊天记录"""
    role: str  # "user" | "agent"
    content: str
    timestamp: str = ""


class ProjectState(BaseModel):
    version: str = "1.0.0"
    project_id: str
    project_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: ProjectStatus = ProjectStatus.idle
    user_goal: str
    
    plan: PlanState = Field(default_factory=PlanState)
    story: StoryState = Field(default_factory=StoryState)
    storyboard: StoryboardState = Field(default_factory=StoryboardState)
    assets: List[AssetState] = Field(default_factory=list)
    timeline: TimelineState = Field(default_factory=TimelineState)
    tasks: List[TaskState] = Field(default_factory=list)
    errors: List[ErrorState] = Field(default_factory=list)
    metadata: MetadataState = Field(default_factory=MetadataState)

    # Studio 前端对齐字段
    story_groups: List[StoryGroup] = Field(default_factory=list)
    chat_history: List[ChatMessage] = Field(default_factory=list)

