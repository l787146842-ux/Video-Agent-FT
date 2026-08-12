"""
运行时设置 API：模型 fallback 开关热切换（不重启生效），持久化 data/runtime_settings.json。

语义（用户定义）：
- 开：模型联不通 / 出不了图视频时，自动换同模型的其他 API 厂商；
- 关：联不通直接按上游报错。
"""
import json

from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from src.video_agent.config import settings
from src.video_agent.utils.paths import PROJECT_ROOT

router = APIRouter()

RUNTIME_SETTINGS_FILE = PROJECT_ROOT / "data" / "runtime_settings.json"


class RuntimeSettingsUpdate(BaseModel):
    model_fallback_enabled: bool


@router.get("/settings/runtime")
async def get_runtime_settings():
    """读取当前运行时设置（顶栏 fallback 开关状态）"""
    return {"model_fallback_enabled": settings.model_fallback_enabled}


@router.put("/settings/runtime")
async def put_runtime_settings(body: RuntimeSettingsUpdate):
    """热切换 fallback 开关：内存即时生效 + 落盘持久化"""
    # Settings 是 frozen dataclass：定点突破不可变约定（仅限运行时设置域）
    object.__setattr__(settings, "model_fallback_enabled", body.model_fallback_enabled)
    logger.info(f"[RuntimeSettings] model_fallback_enabled => {body.model_fallback_enabled}")
    try:
        data = {}
        if RUNTIME_SETTINGS_FILE.exists():
            data = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
        data["model_fallback_enabled"] = body.model_fallback_enabled
        RUNTIME_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_SETTINGS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # 落盘失败不影响内存生效
        logger.warning(f"[RuntimeSettings] 持久化失败（内存已生效）: {e}")
    return {"model_fallback_enabled": settings.model_fallback_enabled}


def load_runtime_settings() -> None:
    """启动时应用持久化覆盖（lifespan 调用；文件缺失/损坏静默回落默认）"""
    try:
        if RUNTIME_SETTINGS_FILE.exists():
            data = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
            if "model_fallback_enabled" in data:
                object.__setattr__(settings, "model_fallback_enabled", bool(data["model_fallback_enabled"]))
    except Exception as e:
        logger.warning(f"[RuntimeSettings] 启动加载失败，使用默认值: {e}")
