"""确认选项兜底归组（防笨模型：选项未带 group 时按维度启发式补分组）。

背景：规格向导的分页卡片依赖选项的 group 字段（每维度一页）。提示词虽要求
模型给选项打 group 标签，但指令遵循弱的模型（如故障 fallback 到的备用模型）
会输出一堆无 group 的选项，前端只能退化成普通单选卡，用户体验断裂。

本模块在选项送达前端前做客观兜底：
- 仅当选项**全部**无 group 时才归组（模型已标注的绝不改动）；
- 选项数少于 MIN_OPTIONS_FOR_WIZARD 时一律不归组：阶段确认卡片只有 2~4 个选项，
  绝不能被误造成分页向导；规格收集场景恒为多维度×候选 ≥5 个选项；
- 按维度关键词把选项分到 画幅/时长/视觉风格/声音与语言/出图渠道/出视频渠道/
  图片分辨率/视频分辨率/分镜最大时长/其它；
- 渠道识别只认「出图/出视频/渠道/API」类明确字样与本项目**真实已配置**的
  供应商/模型名，不拿「图像生成/视频生成」这类动词短语猜渠道；
- 系统注入维度（出图/出视频渠道、图片/视频分辨率）由全局设置注入、不入规格
  文档，归组时并成单一「系统注入（不入规格文档）」组标签（R12）；
- 归出 ≥2 个组标签才启用分组（否则保持普通选项卡，避免无意义的单页向导）；
- 本模块不定义分页顺序，向导分页顺序由前端决定（R12 删除 DIMENSION_ORDER）。
"""
import re
from typing import Any, Dict, List, Tuple

from loguru import logger

from src.video_agent.core.ports import provider_config_port

# 分页向导的最小选项数：阶段确认卡片（确认/调整）只有 2~4 个选项，
# 不得被误造成向导；规格向导场景恒为 ≥5 个选项（多维度×候选）
MIN_OPTIONS_FOR_WIZARD = 5

# 系统注入维度：渠道/分辨率硬参数由全局设置注入、不入规格文档（R12），
# 归组时并入单一组标签，与承载全局决策参数的规格维度区分开
SYSTEM_INJECTED_DIMENSIONS = frozenset({"出图API与模型", "出视频API与模型", "图片分辨率", "视频分辨率"})
SYSTEM_INJECTED_GROUP = "系统注入（不入规格文档）"

_ASPECT_RE = re.compile(r"\b\d{1,2}\s*:\s*\d{1,2}\b")
_DURATION_RE = re.compile(r"\d+\s*(秒|min|mins|minutes?|小时|分钟)")
# 分辨率档位：图片用 1K/2K/4K，视频用 480p/720p/1080p
_IMAGE_RES_RE = re.compile(r"\b[124]K\b", re.IGNORECASE)
_VIDEO_RES_RE = re.compile(r"\b(480|720|1080)p\b", re.IGNORECASE)
# 分镜最大时长类字样（必须先于通用时长判定，否则会被归到总时长维度）
_SHOT_MAX_DURATION_HINTS = ("最大时长", "单镜头", "分镜时长", "镜头时长", "每镜头")

_DIMENSION_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "画幅": ("横屏", "竖屏", "横版", "竖版", "方形", "画幅", "宽银幕"),
    "时长": ("时长", "总时长", "片长"),
    "视觉风格": (
        "风格", "写实", "科幻", "赛博", "动漫", "动画", "水墨", "胶片",
        "黑色电影", "黑色幽默", "复古", "梦幻", "暗黑", "蒸汽", "极简",
    ),
    "声音与语言": (
        "旁白", "配音", "语言", "中文", "英文", "日语", "粤语",
        "音效", "音乐", "无声", "音色",
    ),
}
# 渠道类明确字样（不拿「图像生成/视频生成」这类动词短语单独猜渠道，
# 会把「编写图像生成提示词」这类阶段确认选项误判成渠道维度）
_CHANNEL_HINTS_IMAGE = ("出图", "生图渠道", "图像生成渠道", "出图API")
_CHANNEL_HINTS_VIDEO = ("出视频", "生视频渠道", "视频生成渠道", "出视频API")


def _channel_dim_from_hints(text: str) -> str:
    """渠道类字样归类：有明确出图/出视频方向直接定维度；
    只出现通用「渠道/API」字样时再看伴随的图/视频方向词；无方向返回空串。"""
    if any(k in text for k in _CHANNEL_HINTS_VIDEO):
        return "出视频API与模型"
    if any(k in text for k in _CHANNEL_HINTS_IMAGE):
        return "出图API与模型"
    if "渠道" in text or "API" in text:
        if "视频" in text:
            return "出视频API与模型"
        if "图像" in text or "图片" in text:
            return "出图API与模型"
    return ""


def _configured_names(kind: str) -> List[str]:
    """本项目已配置的供应商显示名与模型名（kind=image/video；
    经 provider_config 端口读取，读取失败返回空）。"""
    try:
        names: List[str] = []
        key = "image_models" if kind == "image" else "video_models"
        for p in provider_config_port().load_merged_providers():
            if not p.get("enabled", True):
                continue
            nm = str(p.get("name") or "").strip()
            if nm:
                names.append(nm)
            for m in p.get(key) or []:
                if str(m or "").strip():
                    names.append(str(m).strip())
        return names
    except Exception:
        return []


def classify_option(
    label: str,
    description: str = "",
    image_names: List[str] | None = None,
    video_names: List[str] | None = None,
) -> str:
    """单个选项 → 维度名；无法归类返回「其它」。"""
    text = f"{label} {description}"
    if _ASPECT_RE.search(label):
        return "画幅"
    # 分镜最大时长先于通用时长判定（「单镜头 12 秒」不能归到总时长）
    if any(h in text for h in _SHOT_MAX_DURATION_HINTS):
        return "分镜最大时长"
    if _DURATION_RE.search(label):
        return "时长"
    # 分辨率：方向词优先，无方向词时按档位默认（p 类属视频，K 类属图片）
    if any(h in text for h in ("图片分辨率", "图像分辨率", "出图分辨率", "生图分辨率")):
        return "图片分辨率"
    if any(h in text for h in ("视频分辨率", "出视频分辨率")):
        return "视频分辨率"
    if _VIDEO_RES_RE.search(label):
        return "视频分辨率"
    if _IMAGE_RES_RE.search(label):
        return "图片分辨率"
    dim = _channel_dim_from_hints(text)
    if dim:
        return dim
    # 渠道名/模型名精确命中（仅查真实配置，不凭空猜测）
    for nm in video_names or []:
        if len(nm) >= 3 and nm.lower() in text.lower():
            return "出视频API与模型"
    for nm in image_names or []:
        if len(nm) >= 3 and nm.lower() in text.lower():
            return "出图API与模型"
    for dim, kws in _DIMENSION_KEYWORDS.items():
        if any(k in text for k in kws):
            return dim
    return "其它"


def fill_option_groups(options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """确认选项兜底归组：全部无 group 时按维度启发式补分组；否则原样返回。

    选项数低于 MIN_OPTIONS_FOR_WIZARD 时一律不归组：阶段确认卡片（2~4 项）
    绝不能被误造成分页向导。系统注入维度（SYSTEM_INJECTED_DIMENSIONS）并入
    单一组标签「系统注入（不入规格文档）」；归出的组标签不足 2 个时同样
    保持普通选项卡形态。
    """
    if not options or any(str(o.get("group") or "").strip() for o in options):
        return options
    if len(options) < MIN_OPTIONS_FOR_WIZARD:
        return options
    image_names = _configured_names("image")
    video_names = _configured_names("video")
    groups = set()
    for o in options:
        dim = classify_option(
            str(o.get("label") or ""), str(o.get("description") or ""),
            image_names, video_names,
        )
        # R12：系统注入维度并成同一组标签（不入规格文档的硬参数单独成页）
        group = SYSTEM_INJECTED_GROUP if dim in SYSTEM_INJECTED_DIMENSIONS else dim
        o["group"] = group
        groups.add(group)
    # 撤回判定按写入后的组标签计数：多维度场景仍归组、单一标签场景仍撤回
    if len(groups) < 2:
        for o in options:
            o.pop("group", None)
        return options
    logger.info(
        f"[ConfirmOptions] 选项未携带 group 标签，已按维度兜底归组："
        f"{len(options)} 个选项 → {len(groups)} 个维度"
    )
    return options
