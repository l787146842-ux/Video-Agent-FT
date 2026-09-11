"""
运行时设置 API：全局生成默认 + 模型 fallback 开关热切换（不重启生效），
持久化 data/runtime_settings.json。

语义（用户定义）：
- model_fallback_enabled 开：模型联不通 / 出不了图视频时，自动换同模型的其他 API 厂商；
  关：联不通直接按上游报错。
- default_* 系列：全局出图/出视频渠道与分辨率默认值，新建草稿补印与 Agent 生成回退链共用；
- chat_image_enabled：聊天框出图开关（关 = Agent 在对话中不主动触发生图）；
- skills_disabled：被停用的 Skill slug 列表（批5，对齐外部标杆 卡片开关；空 = 全启用）；
- execution_preference：执行偏好三档（管花钱生成是否先弹确认卡；
  2026-08-30 用户裁决，Skill 系统修复批 B）；
- execution_mode：执行模式四档（管流程推进的暂停策略；2026-09-06 用户裁决，对齐批）；
- max_shot_duration：Agent 自拆分镜的单镜最大时长（秒）。
- llm_max_tokens：单次 LLM 输出 token 上限（Q3 步数上限退役后，跑飞兜底改为
  输出 token 截断 + 模型自决；对齐 dsh DEFAULT_MAX_TOKENS=256k）。
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from src.video_agent.config import (
    EXECUTION_MODE_VALUES,
    EXECUTION_PREFERENCE_VALUES,
    normalize_exec_mode,
    normalize_exec_pref,
    settings,
)
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
# 单次 LLM 输出 token 上限（Q3 步数上限退役后的跑飞兜底）：独立钳制区间，
# adapter 每次调用实时读 settings.llm_max_tokens，热更新后即刻生效
_LLM_MAX_TOKENS_KEYS = ("llm_max_tokens",)
# Skill 启停开关（批5/对齐外部标杆 卡片开关）：存被停用 Skill 的 slug 列表；
# 目录过滤/ list_skills 同源消费（宪法 §六：可调参数归 config.settings，
# 写入点归本既有热更新通道，不另开旁路存储）
_LIST_KEYS = ("skills_disabled",)
# 剧本注入上限（字符）热更新键，独立钳制区间（不与秒数共用 clamp）
_CHAR_LIMIT_KEYS = ("script_inject_limit",)
# 推理档位旧键名（退役：仅作存量迁移用，API 表面已移除；
# config 字段保留作 env 覆写，语义归模型分层策略 summary/executor 行）
_THINKING_KEYS = ("executor_thinking_level", "aux_thinking_level")
_THINKING_VALUES = ("", "low", "medium", "high")
# 执行偏好三档（2026-08-30 用户裁决）：枚举白名单与清洗口归 config 单一事实源；
# 非法值拒收（保持当前档），存量配置缺键/脏值回落默认档（行为与现状一致）
_EXEC_PREF_KEYS = ("execution_preference",)
# 执行模式四档（2026-09-06 用户裁决，对齐批）：同上口径
_EXEC_MODE_KEYS = ("execution_mode",)


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
    # 单次 LLM 输出 token 上限（非法/超界值钳制后生效）
    llm_max_tokens: Optional[int] = None
    # 被停用的 Skill slug 列表（批5；空列表 = 全部启用）
    skills_disabled: Optional[List[str]] = None
    # 剧本正文注入上限（字符）
    script_inject_limit: Optional[int] = None
    # 执行偏好三档（非法值拒收；缺省 = 不变更）
    execution_preference: Optional[str] = None
    # 执行模式四档（非法值拒收；缺省 = 不变更）
    execution_mode: Optional[str] = None
    # 模型分层策略表（编排/生成/摘要/子代理四角色；空 = 跟随主模型；
    # 推理档位可独立于供应商设置；旧「推理档位」卡两键已退役）
    model_policy: Optional[Dict[str, Any]] = None


class PolicyRow(BaseModel):
    """模型分层策略单行（normalize_policy 白名单三键）"""
    provider: str = ""
    model: str = ""
    thinking_level: str = ""


class RuntimeSettings(BaseModel):
    """运行时设置读形态（GET/PUT 响应同形；字段恒下发，契约层必填）"""
    model_fallback_enabled: bool
    chat_image_enabled: bool
    default_image_provider_id: str
    default_image_model: str
    default_video_provider_id: str
    default_video_model: str
    default_image_resolution: str
    default_video_resolution: str
    max_shot_duration: int
    llm_max_tokens: int
    skills_disabled: List[str]
    script_inject_limit: int
    execution_preference: str
    execution_mode: str
    model_policy: Dict[str, PolicyRow]


def _sanitize_slug_list(value: Any) -> Optional[List[str]]:
    """Skill slug 列表清洗（开关写入唯一规整口）：非列表拒收；
    逐项转非空字符串、去重保序、限长防滥用。"""
    if not isinstance(value, list):
        return None
    out: List[str] = []
    for item in value:
        s = str(item or "").strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= 200:
            break
    return out


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
        "llm_max_tokens": settings.llm_max_tokens,
        "skills_disabled": list(settings.skills_disabled or []),
        "script_inject_limit": settings.script_inject_limit,
        # 执行偏好恒下发（清洗后口径，脏值自动回落默认档）
        "execution_preference": normalize_exec_pref(settings.execution_preference),
        # 执行模式恒下发（同上口径）
        "execution_mode": normalize_exec_mode(settings.execution_mode),
        # 推理档位两键退役（归模型分层策略），GET 不再下发
        "model_policy": mp.current_policy(),
    }


@router.get("/settings/runtime", response_model=RuntimeSettings)
async def get_runtime_settings():
    """读取当前运行时设置（全局设置页 + 顶栏开关状态）"""
    return _current_dict()


@router.put("/settings/runtime", response_model=RuntimeSettings)
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
        elif key in _LLM_MAX_TOKENS_KEYS:
            try:
                value = max(1024, min(int(value), 1048576))
            except (TypeError, ValueError):
                continue
        elif key in _CHAR_LIMIT_KEYS:
            try:
                value = max(1000, min(int(value), 200000))
            except (TypeError, ValueError):
                continue
        elif key in _STR_KEYS:
            value = str(value or "").strip()
        elif key in _LIST_KEYS:
            value = _sanitize_slug_list(value)
            if value is None:
                continue
        elif key in _EXEC_PREF_KEYS:
            v = str(value or "").strip().lower()
            if v not in EXECUTION_PREFERENCE_VALUES:
                continue  # 非法值拒收（保持当前档）
            value = v
        elif key in _EXEC_MODE_KEYS:
            v = str(value or "").strip().lower()
            if v not in EXECUTION_MODE_VALUES:
                continue  # 非法值拒收（保持当前档）
            value = v
        elif key == "model_policy":
            # 策略表结构白名单清洗（4 角色 × 3 键）
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
        for key in _LIST_KEYS:
            if key in data:
                value = _sanitize_slug_list(data[key])
                if value is not None:
                    object.__setattr__(settings, key, value)
        for key in _EXEC_PREF_KEYS:
            # 合法值应用；非法/脏值自然回落 config 默认档（行为与现状一致）
            if key in data:
                v = str(data[key] or "").strip().lower()
                if v in EXECUTION_PREFERENCE_VALUES:
                    object.__setattr__(settings, key, v)
        for key in _EXEC_MODE_KEYS:
            # 合法值应用；非法/脏值自然回落 config 默认档（行为与现状一致）
            if key in data:
                v = str(data[key] or "").strip().lower()
                if v in EXECUTION_MODE_VALUES:
                    object.__setattr__(settings, key, v)
        for key in _INT_KEYS:
            if key in data:
                try:
                    object.__setattr__(settings, key, max(1, min(int(data[key]), 60)))
                except (TypeError, ValueError) as _e:
                    logger.debug("[runtime_settings] 忽略异常: {}", _e)
        for key in _LLM_MAX_TOKENS_KEYS:
            if key in data:
                try:
                    object.__setattr__(settings, key, max(1024, min(int(data[key]), 1048576)))
                except (TypeError, ValueError) as _e:
                    logger.debug("[runtime_settings] 忽略异常: {}", _e)
        for key in _CHAR_LIMIT_KEYS:
            if key in data:
                try:
                    object.__setattr__(settings, key, max(1000, min(int(data[key]), 200000)))
                except (TypeError, ValueError) as _e:
                    logger.debug("[runtime_settings] 忽略异常: {}", _e)
        # 「推理档位」卡退役——存量值（文件旧键 / env 覆写）
        # 一次性迁入 model_policy 的 subagent/summary 行；两旧键从文件清除。
        from src.video_agent.core import model_policy as mp

        pol = mp.normalize_policy(
            data["model_policy"] if "model_policy" in data
            else (getattr(settings, "model_policy", None) or {}))
        migrated = False
        for role, legacy_key, env_val in (
            ("subagent", "executor_thinking_level", settings.executor_thinking_level),
            ("summary", "aux_thinking_level", settings.aux_thinking_level),
        ):
            legacy = str(data.get(legacy_key) or "").strip().lower()
            if legacy not in _THINKING_VALUES:
                legacy = ""
            legacy = legacy or str(env_val or "").strip().lower()
            if legacy and legacy in _THINKING_VALUES:
                entry = pol.setdefault(role, {})
                if not entry.get("thinking_level"):
                    entry["thinking_level"] = legacy
                    migrated = True
        object.__setattr__(settings, "model_policy", pol)
        if migrated:
            try:
                data["model_policy"] = pol
                for legacy_key in _THINKING_KEYS:
                    data.pop(legacy_key, None)
                RUNTIME_SETTINGS_FILE.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info("[RuntimeSettings] 推理档位存量值已迁入模型分层策略")
            except Exception as e:
                logger.warning(f"[RuntimeSettings] 迁移落盘失败（内存已生效）: {e}")
    except Exception as e:
        logger.warning(f"[RuntimeSettings] 启动加载失败，使用默认值: {e}")
