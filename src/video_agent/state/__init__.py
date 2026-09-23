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
    ProjectStatus,
    # 模型
    ProjectState, KeyElementGroup, ShotGroup, AudioGroup,
    # 工厂
    build_draft_dict, DRAFT_DEFAULT_FIELDS,
    # 媒体类型闭集与唯一推导入口（2026-09-23 批11，事故 4444/P1-5）
    MEDIA_TYPES, AUDIO_TYPE_TO_MEDIA, infer_media_type,
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
    "ProjectStatus",
    "ProjectState", "KeyElementGroup", "ShotGroup", "AudioGroup",
    "build_draft_dict", "DRAFT_DEFAULT_FIELDS",
    "MEDIA_TYPES", "AUDIO_TYPE_TO_MEDIA", "infer_media_type",
    "AssetType", "AssetStatus", "AudioCategory",
    "TimelineStatus", "TaskType", "TaskStatus", "ErrorLevel",
    "AssetState", "Clip", "Track", "TimelineState",
    "TaskOutput", "TaskState", "ErrorState",
    "MetadataModelConfig", "MetadataPreferences", "MetadataCostTracking", "MetadataState",
]