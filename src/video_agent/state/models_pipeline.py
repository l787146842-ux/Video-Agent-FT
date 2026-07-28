"""
CLI / Workflow 生成管线专用模型。

从 models.py 拆分而来（Phase 4），包含：
- 资产管理（AssetState）
- 时间线 / 轨道 / 片段（TimelineState / Track / Clip）
- 任务调度（TaskState / TaskOutput）
- 错误追踪（ErrorState）
- 项目元数据（MetadataState 及子模型）

Studio 前端对齐模型仍保留在 models.py。
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


# =======================
# Pipeline Enums
# =======================

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
# Pipeline Models
# =======================

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
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None
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
    phase: str = ""
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
