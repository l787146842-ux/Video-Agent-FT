"""制作参数单一事实源（顶部「全局设置」→ 渠道/分辨率/时长）。

出图/出视频渠道、图片分辨率、视频分辨率、分镜最大时长由顶部「全局设置」
唯一提供，规格文档只承载 Skill 声明的创作性软维度；本模块是这些硬参数的
单一事实源：执行器与 provider_config 都从这里取，避免各处自行解析。
"""
import re
from typing import Any, Dict, Optional, Tuple

from src.video_agent.config import settings
from src.video_agent.core.provider_config import spec_media_preference

# 规格「未确认占位」标记常量（SPEC_PARAM_UNCONFIRMED_MARKERS）已随用户裁决
# 2026-08-31 退役删除（D-08 清偿：规格向导消费面全部退役）。


def resolve_spec_media_preference(
    raw_state: Dict[str, Any],
    providers: list,
    kind: str = "image",
) -> Tuple[str, str]:
    """解析生成渠道 (provider_id, model)——唯一来源为顶部「全局设置」。

    全局设置未配置，或指向的供应商已禁用/不存在时返回 ("", "")，
    由调用方提示用户配置；绝不自动选第一个可用供应商（防串线）。
    """
    pid, model = spec_media_preference(raw_state, kind)
    if not pid:
        return "", ""
    for p in providers or []:
        if str(p.get("id") or "") == pid and p.get("enabled", True):
            if not model:
                models = _models_of(p, kind)
                model = models[0] if models else ""
            return pid, model
    return "", ""


def resolve_spec_production_params(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    """制作参数单一事实源（顶部「全局设置」）。

    返回执行器/生成管线关心的三个键：
    - image_resolution：图片分辨率（如 1K/2K/4K）
    - video_resolution：视频分辨率（如 480p/720p/1080p）
    - shot_max_duration：分镜最大时长（秒，解析「N 秒/Ns」）
    规格文档不承载这些硬参数。
    """
    return {
        "image_resolution": settings.default_image_resolution,
        "video_resolution": settings.default_video_resolution,
        "shot_max_duration": settings.max_shot_duration,
    }


def extract_production_params(content: str) -> Dict[str, Any]:
    """制作参数单一事实源（全局设置；content 仅保留签名兼容）。"""
    return resolve_spec_production_params({})


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:秒|s)", re.I)


def _fmt_duration(value) -> int:
    """时长解析为整数秒（「12 秒」→ 12；12.0 同样归整，避免「12.0 秒」穿帮）。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return int(f) if f.is_integer() else f


def _parse_spec_params(content: str) -> Dict[str, Any]:
    """按行解析规格键值清单；键名归一化（去空格/冒号变体）。"""
    out: Dict[str, Any] = {}
    for line in content.splitlines():
        line = line.strip().lstrip("-*").strip()
        if not line or "：" not in line and ":" not in line:
            continue
        key, _, val = line.partition("：" if "：" in line else ":")
        key = key.strip().casefold().replace(" ", "")
        val = val.strip()
        if not val:
            continue
        if key in ("图片分辨率", "图像分辨率", "imageresolution"):
            out["image_resolution"] = val
        elif key in ("视频分辨率", "videoresolution"):
            out["video_resolution"] = val
        elif key in ("分镜最大时长", "分镜最大时长(单镜头秒数上限)", "单镜头最大时长", "单镜头时长", "shotmaxduration"):
            m = _DURATION_RE.search(val)
            if m:
                out["shot_max_duration"] = _fmt_duration(m.group(1))
    return out


def _models_of(p: Dict[str, Any], kind: str) -> list:
    key = "image_models" if kind == "image" else "video_models"
    models = [m for m in (p.get(key) or []) if m]
    if models:
        return models
    # 供应商未分渠道时用 chat_models 兜底（与 first_available_* 语义一致）
    return [m for m in (p.get("chat_models") or []) if m]
