"""制片规格偏好解析（规格文档 → 生成渠道/分辨率/时长）。

规格文档（Final_Video_Spec.md 等）是用户确认后落盘的结构化键值清单，
本模块是「规格偏好」的单一事实源：执行器与 provider_config 都从这里取
渠道/分辨率/分镜最大时长，避免各处自行解析产生两套说辞。
"""
import re
from typing import Any, Dict, Optional, Tuple

from src.video_agent.web.provider_config import spec_media_preference

# 规格文档中「未确认占位」标记（9999 事故：三项参数标着「待确认」就放行）。
# prompt_gates.spec_unconfirmed_params / apply_spec_selections 与解析正则同源消费。
SPEC_PARAM_UNCONFIRMED_MARKERS: Tuple[str, ...] = ("待确认", "待定", "未确认", "TBD")


def resolve_spec_media_preference(
    raw_state: Dict[str, Any],
    providers: list,
    kind: str = "image",
) -> Tuple[str, str]:
    """解析规格文档声明的生成渠道 (provider_id, model)。

    优先级：
    1. 规格文档中的「图像生成/视频生成」偏好（spec_media_preference）；
    2. 回退第一个可用的非 mock 供应商（按 kind 取 image_models / video_models）。
    规格声明了渠道但对应供应商已禁用/不存在时，回退到可用供应商。
    返回 (provider_id, model)，均无命中返回 ("", "")。
    """
    pid, model = spec_media_preference(raw_state, kind)
    if pid:
        for p in providers or []:
            if str(p.get("id") or "") == pid and p.get("enabled", True):
                if not model:
                    models = _models_of(p, kind)
                    model = models[0] if models else ""
                return pid, model
    for p in providers or []:
        if not p.get("enabled", True):
            continue
        if (p.get("protocol") or "") == "mock":
            continue
        models = _models_of(p, kind)
        if models:
            return str(p.get("id") or ""), models[0]
    return "", ""


def resolve_spec_production_params(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    """从规格文档解析制作参数。

    规格文档为精简键值清单（每行「键：值」），本函数只取执行器/生成管线
    关心的三个键：
    - image_resolution：图片分辨率（如 1K/2K/4K）
    - video_resolution：视频分辨率（如 480p/720p/1080p）
    - shot_max_duration：分镜最大时长（秒，解析「N 秒/Ns」）
    未命中返回空 dict（调用方按 Skill/系统默认兜底）。
    """
    for doc in raw_state.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        if not str(doc.get("content") or "").strip():
            continue
        from src.video_agent.core.prompt_gates import is_spec_doc_name

        if not is_spec_doc_name(str(doc.get("name") or "")):
            continue
        params = _parse_spec_params(str(doc.get("content") or ""))
        if params:
            return params
    return {}


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:秒|s)", re.I)


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
        elif key in ("分镜最大时长", "分镜最大时长(单镜头秒数上限)", "shotmaxduration"):
            m = _DURATION_RE.search(val)
            if m:
                out["shot_max_duration"] = float(m.group(1))
    return out


def _models_of(p: Dict[str, Any], kind: str) -> list:
    key = "image_models" if kind == "image" else "video_models"
    models = [m for m in (p.get(key) or []) if m]
    if models:
        return models
    # 供应商未分渠道时用 chat_models 兜底（与 first_available_* 语义一致）
    return [m for m in (p.get("chat_models") or []) if m]
