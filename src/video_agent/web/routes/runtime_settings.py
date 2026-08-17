"""
运行时设置 API：全局生成默认 + 模型 fallback 开关热切换（不重启生效），
持久化 data/runtime_settings.json。

语义（用户定义）：
- model_fallback_enabled 开：模型联不通 / 出不了图视频时，自动换同模型的其他 API 厂商；
  关：联不通直接按上游报错。
- default_* 系列：全局出图/出视频渠道与分辨率默认值，新建草稿补印与 Agent 生成回退链共用；
- chat_image_enabled：聊天框出图开关（关 = Agent 在对话中不主动触发生图）；
- max_shot_duration：Agent 自拆分镜的单镜最大时长（秒）。
"""
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from src.video_agent.config import settings
from src.video_agent.utils.paths import PROJECT_ROOT

router = APIRouter()

RUNTIME_SETTINGS_FILE = PROJECT_ROOT / "data" / "runtime_settings.json"

# 可热更新的运行时设置键 → 类型转换（定点突破 frozen Settings，仅限本域）
_BOOL_KEYS = ("model_fallback_enabled", "chat_image_enabled")
_STR_KEYS = (
    "default_image_provider_id", "default_image_model",
    "default_video_provider_id", "default_video_model",
    "default_image_resolution", "default_video_resolution",
)
_INT_KEYS = ("max_shot_duration",)
# 0817 B24：剧本注入上限（字符）热更新键，独立钳制区间（不与秒数共用 clamp）
_CHAR_LIMIT_KEYS = ("script_inject_limit",)
# 814H7：推理档位键（""=默认/原生，low/medium/high 透传 reasoning_effort）
_THINKING_KEYS = ("executor_thinking_level", "aux_thinking_level")
_THINKING_VALUES = ("", "low", "medium", "high")


class RuntimeSettingsUpdate(BaseModel):
    model_fallback_enabled: Optional[bool] = None
    chat_image_enabled: Optional[bool] = None
    default_image_provider_id: Optional[str] = None
    default_image_model: Optional[str] = None
    default_video_provider_id: Optional[str] = None
    default_video_model: Optional[str] = None
    default_image_resolution: Optional[str] = None
    default_video_resolution: Optional[str] = None
    max_shot_duration: Optional[int] = None
    # 0817 B24：剧本正文注入上限（字符）
    script_inject_limit: Optional[int] = None
    # 814H7：推理档位（""=默认/原生）
    executor_thinking_level: Optional[str] = None
    aux_thinking_level: Optional[str] = None
    # B8：模型分层策略表（编排/生成/摘要/执行器四角色；空 = 跟随主模型）
    model_policy: Optional[Dict[str, Any]] = None


def _current_dict() -> Dict[str, Any]:
    from src.video_agent.core import model_policy as mp

    return {
        "model_fallback_enabled": settings.model_fallback_enabled,
        "chat_image_enabled": settings.chat_image_enabled,
        "default_image_provider_id": settings.default_image_provider_id,
        "default_image_model": settings.default_image_model,
        "default_video_provider_id": settings.default_video_provider_id,
        "default_video_model": settings.default_video_model,
        "default_image_resolution": settings.default_image_resolution,
        "default_video_resolution": settings.default_video_resolution,
        "max_shot_duration": settings.max_shot_duration,
        "script_inject_limit": settings.script_inject_limit,
        "executor_thinking_level": settings.executor_thinking_level,
        "aux_thinking_level": settings.aux_thinking_level,
        "model_policy": mp.current_policy(),
    }


@router.get("/settings/runtime")
async def get_runtime_settings():
    """读取当前运行时设置（全局设置页 + 顶栏开关状态）"""
    return _current_dict()


@router.put("/settings/runtime")
async def put_runtime_settings(body: RuntimeSettingsUpdate):
    """热更新运行时设置：内存即时生效 + 落盘持久化（仅应用请求中提供的字段）"""
    payload = body.model_dump(exclude_none=True)
    applied: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in _BOOL_KEYS:
            value = bool(value)
        elif key in _INT_KEYS:
            try:
                value = max(1, min(int(value), 60))
            except (TypeError, ValueError):
                continue
        elif key in _CHAR_LIMIT_KEYS:
            try:
                value = max(1000, min(int(value), 200000))
            except (TypeError, ValueError):
                continue
        elif key in _STR_KEYS:
            value = str(value or "").strip()
        elif key in _THINKING_KEYS:
            value = str(value or "").strip().lower()
            if value not in _THINKING_VALUES:
                value = ""
        elif key == "model_policy":
            # B8：策略表结构白名单清洗（4 角色 × 3 键）
            from src.video_agent.core import model_policy as mp

            value = mp.normalize_policy(value)
        else:
            continue
        object.__setattr__(settings, key, value)
        applied[key] = value
    if applied:
        logger.info(f"[RuntimeSettings] 热更新 => {applied}")
    try:
        data = {}
        if RUNTIME_SETTINGS_FILE.exists():
            data = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
        data.update(applied)
        RUNTIME_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_SETTINGS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # 落盘失败不影响内存生效
        logger.warning(f"[RuntimeSettings] 持久化失败（内存已生效）: {e}")
    return _current_dict()


def load_runtime_settings() -> None:
    """启动时应用持久化覆盖（lifespan 调用；文件缺失/损坏静默回落默认）"""
    try:
        if not RUNTIME_SETTINGS_FILE.exists():
            return
        data = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
        for key in _BOOL_KEYS:
            if key in data:
                object.__setattr__(settings, key, bool(data[key]))
        for key in _STR_KEYS:
            if key in data:
                object.__setattr__(settings, key, str(data[key] or ""))
        for key in _INT_KEYS:
            if key in data:
                try:
                    object.__setattr__(settings, key, max(1, min(int(data[key]), 60)))
                except (TypeError, ValueError) as _e:
                    logger.debug("[runtime_settings] 忽略异常: {}", _e)
        for key in _CHAR_LIMIT_KEYS:
            if key in data:
                try:
                    object.__setattr__(settings, key, max(1000, min(int(data[key]), 200000)))
                except (TypeError, ValueError) as _e:
                    logger.debug("[runtime_settings] 忽略异常: {}", _e)
        for key in _THINKING_KEYS:
            if key in data:
                v = str(data[key] or "").strip().lower()
                object.__setattr__(settings, key, v if v in _THINKING_VALUES else "")
        if "model_policy" in data:
            from src.video_agent.core import model_policy as mp

            object.__setattr__(settings, "model_policy", mp.normalize_policy(data["model_policy"]))
    except Exception as e:
        logger.warning(f"[RuntimeSettings] 启动加载失败，使用默认值: {e}")
