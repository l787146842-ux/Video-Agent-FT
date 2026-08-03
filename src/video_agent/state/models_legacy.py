"""
DEPRECATED — CLI 遗留状态模型。

这些模型服务于早期 CLI 管线（story → storyboard → shot 线性流程），
已被 Studio 前端的 KeyElementGroup / ShotGroup / AudioGroup 替代。

保留原因：
- ProjectState.story / ProjectState.plan 字段仍需反序列化旧 state.json
- skills/__init__.py 的 output_mapping 仍引用 story.scenes

新代码请勿使用本模块中的模型。
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# =======================
# Enums（CLI 管线专用）
# =======================

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
# Models（CLI 管线专用）
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
