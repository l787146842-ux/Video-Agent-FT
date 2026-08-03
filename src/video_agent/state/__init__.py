"""
state 包统一导出。

外部模块应从本包导入状态相关类型，而非直接引用 models.py / models_pipeline.py：
    from src.video_agent.state import StateManager, CAT_SHOTS, ProjectState
"""
from .manager import StateManager
from .models import (
    # 常量
    CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS,
    ALL_CATEGORIES, ALL_CATEGORIES_TUPLE,
    # 枚举
    ProjectStatus, Phase, StepStatus, StoryStatus, ShotType,
    # 模型
    ProjectState, KeyElementGroup, ShotGroup, AudioGroup,
    # 工厂
    build_draft_dict, DRAFT_DEFAULT_FIELDS,
)
from .models_pipeline import (
    AssetType, AssetStatus, AudioCategory,
    TimelineStatus, TaskType, TaskStatus, ErrorLevel,
    AssetState, Clip, Track, TimelineState,
    TaskOutput, TaskState, ErrorState,
    MetadataModelConfig, MetadataPreferences, MetadataCostTracking, MetadataState,
)

__all__ = [
    "StateManager",
    "CAT_KEY_ELEMENTS", "CAT_SHOTS", "CAT_AUDIO_ITEMS",
    "ALL_CATEGORIES", "ALL_CATEGORIES_TUPLE",
    "ProjectStatus", "Phase", "StepStatus", "StoryStatus", "ShotType",
    "ProjectState", "KeyElementGroup", "ShotGroup", "AudioGroup",
    "build_draft_dict", "DRAFT_DEFAULT_FIELDS",
    "AssetType", "AssetStatus", "AudioCategory",
    "TimelineStatus", "TaskType", "TaskStatus", "ErrorLevel",
    "AssetState", "Clip", "Track", "TimelineState",
    "TaskOutput", "TaskState", "ErrorState",
    "MetadataModelConfig", "MetadataPreferences", "MetadataCostTracking", "MetadataState",
]