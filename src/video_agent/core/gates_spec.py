"""制片规格向导家族（R4b 自 prompt_gates.py 切出）：维度提取/候选解析/向导拼装/规格落盘。
被测试 patch 的符号（_channel_groups/skill_spec_dimensions/gate_mode）经 _pg 模块属性引用，
patch prompt_gates 模块即可生效。"""
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.video_agent.config import settings
from src.video_agent.core import prompt_gates as _pg
from src.video_agent.state.provider_prefs import SPEC_PARAM_UNCONFIRMED_MARKERS
from src.video_agent.core.prompt_gates import (
    _SPEC_PARAM_LINES,

    SPEC_COLLECT_PAUSED_MSG,
    SPEC_COLLECT_PAUSED_MSG_NO_SUMMARY,
    SPEC_DOC_PAUSED_MSG,
    _SPEC_CONFIRM_INTENT_RE,
    _SPEC_DUR_SEL_RE,
    _SPEC_IMG_SEL_RE,
    _SPEC_SUGGESTED_RE,
    _SPEC_VID_SEL_RE,
    _SPEC_WRITE_ENUM_RE,
    _SPEC_WRITE_VERB_RE,
    is_spec_doc_name,
    spec_review_options,
    text_mentions_spec_doc,
)


# 硬参数维度黑名单（6666 二轮：出图/出视频渠道、分辨率、分镜最大时长
# 由顶部「全局设置」唯一提供，规格向导与规格文档均不再承载；总时长等
# 创作性「时长」维度不在黑名单内）
_HARD_PARAM_DIM_HINTS = (
    "分辨率", "分镜最大时长", "单镜头最大时长", "单镜头时长",
    "出图", "出视频", "图像生成", "视频生成", "模型偏好", "渠道",
)


_PLACEHOLDER_DIM_VALUE = "（待定）"


def _is_hard_param_dim(dim: str) -> bool:
    return any(h in str(dim or "") for h in _HARD_PARAM_DIM_HINTS)


def _clean_dim_token(token: str) -> str:
    return re.sub(r"[（(][^（）()]*[）)]", "", str(token or "")).strip(" \t-*")


def _dedupe(items) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def skill_spec_dimensions(skill_name: str) -> List[str]:
    """客观提取 Skill 规格编写步骤声明的维度清单（10.12-G1：不改 skill）。

    优先解析「建议条目：…」整段（去括号注解后按 /、，、；切分，不截断）；
    无建议条目时回退解析括号枚举；硬参数维度（渠道/分辨率/分镜最大时长）
    由全局设置提供，一律剔除；提取失败返回空列表（平台不替 Skill 造维度）。
    """
    try:
        from src.video_agent.skill_runtime.registry import resolve_entry

        entry = resolve_entry(skill_name)
        content = entry.content if entry else ""
    except Exception:
        content = ""
    for line in str(content or "").splitlines():
        if not text_mentions_spec_doc(line):
            continue
        if not _SPEC_WRITE_VERB_RE.search(line):
            continue
        m = _SPEC_SUGGESTED_RE.search(line)
        if m:
            dims = [
                _clean_dim_token(x)
                for x in re.split(r"[、，,;；/]+", m.group(1))
            ]
            return _dedupe(d for d in dims if not _is_hard_param_dim(d))
        m = _SPEC_WRITE_ENUM_RE.search(line)
        if not m:
            continue
        dims = [d.strip() for d in re.split(r"[、，,;；]", m.group(1)) if d.strip()]
        return _dedupe(d for d in dims if not _is_hard_param_dim(d))
    return []


def parse_dim_selections(user_text: str, dims: List[str]) -> Dict[str, str]:
    """解析用户回应里「维度：值」形式的软维度选择（向导逐行回传，兼容自由表述）。"""
    out: Dict[str, str] = {}
    text = str(user_text or "")
    for dim in dims or []:
        m = re.search(re.escape(dim) + r"\s*[:：]\s*([^；;\n]+)", text)
        if m:
            v = m.group(1).strip()
            if (
                v and len(v) <= 40
                and v != _PLACEHOLDER_DIM_VALUE
                and not any(k in v for k in SPEC_PARAM_UNCONFIRMED_MARKERS)
            ):
                out[dim] = v
    return out


def spec_unconfirmed_params(content: str) -> List[str]:
    """规格文档中「待确认」的制作参数名列表（行缺失或行内含待确认标记）。"""
    out: List[str] = []
    for name, pat in _SPEC_PARAM_LINES:
        m = pat.search(content or "")
        if not m or any(k in m.group(0) for k in SPEC_PARAM_UNCONFIRMED_MARKERS):
            out.append(name)
    return out


def _spec_doc_content(state: Dict[str, Any]) -> str:
    for doc in (state.get("documents") or []):
        if isinstance(doc, dict) and is_spec_doc_name(str(doc.get("name") or "")):
            return str(doc.get("content") or "")
    return ""


def state_has_spec_doc(state: Dict[str, Any]) -> bool:
    """工作台是否已存在规格文档（6666 事故：收集闸仅在无规格文档时触发）。"""
    return any(
        isinstance(d, dict) and is_spec_doc_name(str(d.get("name") or ""))
        for d in (state.get("documents") or [])
    )


# 渠道选项组标题：含「出图/出视频 + 渠道/厂商/模型」关键词，前端 ConfirmPicker
# 据此渲染厂商+模型级联下拉（实时拉 API 配置，选中回传「厂商名 / 模型名」）
_CHANNEL_GROUP_IMAGE = "出图渠道（API 厂商/模型）"


_CHANNEL_GROUP_VIDEO = "出视频渠道（API 厂商/模型）"


def _channel_groups() -> List[Dict[str, Any]]:
    """出图/出视频渠道选项组（组内选项仅为占位：前端渲染为厂商+模型下拉）。
    供应商配置加载失败时静默返回空（不阻断参数向导）。"""
    try:
        from src.video_agent.web import provider_config

        providers = provider_config.load_merged_providers()
    except Exception:
        return []
    has_img = any((p.get("image_models") or []) for p in providers)
    has_vid = any((p.get("video_models") or []) for p in providers)
    out: List[Dict[str, Any]] = []
    if has_img:
        out.append({
            "label": "出图渠道：下拉选择厂商+模型",
            "description": "在上方下拉框直接选择（实时读取 API 配置）",
            "group": _CHANNEL_GROUP_IMAGE,
        })
    if has_vid:
        out.append({
            "label": "出视频渠道：下拉选择厂商+模型",
            "description": "在上方下拉框直接选择（实时读取 API 配置）",
            "group": _CHANNEL_GROUP_VIDEO,
        })
    return out


def _current_skill_of(state: Optional[Dict[str, Any]]) -> str:
    """状态里的当前 Skill 名（usedSkills 末位），无则空串。"""
    used = ((state or {}).get("usedSkills") or [])
    return str(used[-1] or "") if used else ""


def _spec_dim_unresolved(content: str, dim: str) -> bool:
    """规格文档里某软维度是否未定稿（行缺失/值空/含待确认标记，兼容加粗行）。

    向导渲染的客观闸门（9999 二轮：拆解阶段暂停卡混回规格向导）：
    维度已在规格里定稿就不再渲染，不依赖 spec_collected 一次性标记的
    消费时序——标记被规格审阅暂停消费后，后续任何暂停都重弹向导。
    """
    pat = re.compile(
        r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?" + re.escape(dim) + r"(?:\*\*)?\s*[:：]\s*(.*)$"
    )
    m = pat.search(content or "")
    if not m:
        return True
    val = m.group(1).strip().strip("*").strip()
    if not val or val == _PLACEHOLDER_DIM_VALUE:
        return True
    return any(k in val for k in SPEC_PARAM_UNCONFIRMED_MARKERS)


def spec_doc_finalized(state: Dict[str, Any]) -> bool:
    """规格文档已存在且 Skill 软维度全部定稿（8888 二轮客观闸门）。

    用于规格拒收接管路径：规格已定稿时模型的冗余手写只需拒收警告，
    不得接管暂停卡（否则拆解阶段又被换回「确认规格」卡）。"""
    content = _spec_doc_content(state)
    if not content.strip():
        return False
    for dim in _pg.skill_spec_dimensions(_current_skill_of(state)):
        if _spec_dim_unresolved(content, dim):
            return False
    return True


def build_spec_param_options(
    spec_content: str, state: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """规格交互候选项向导（6666 二轮：出图/出视频渠道、图片分辨率、
    视频分辨率、分镜最大时长由顶部「全局设置」唯一提供，向导不再渲染）。

    只渲染 Skill 规格步骤声明的软维度（4444：维度来自 Skill，平台不预设）；
    规格文档已存在时只渲染未定稿维度（9999 二轮：客观状态闸门）；
    每个维度至少渲染一个入口——候选 >=2 渲染候选卡，候选不足时渲染占位卡
    + 组内「其它（自定义输入）」，保证「模型不能增删维度」。
    选项 label 采用「键：值」格式（前端向导按 group 分页，发送时逐行拼接，
    chat_service 据此机械存档/拼装，不依赖模型自觉）。全部无需交互时返回空。
    """
    opts: List[Dict[str, Any]] = []
    dims = _pg.skill_spec_dimensions(_current_skill_of(state))
    cands = ((state or {}).get("interaction") or {}).get("spec_soft_candidates") or {}
    has_content = bool(str(spec_content or "").strip())
    rendered_dims: List[str] = []
    for dim in dims:
        # 规格文档里已定稿的维度不再渲染（收集阶段无文档时全量渲染）
        if has_content and not _spec_dim_unresolved(spec_content, dim):
            continue
        vals = [str(v).strip() for v in (cands.get(dim) or []) if str(v or "").strip()]
        if vals:
            for v in vals[:4]:
                opts.append({
                    "label": f"{dim}：{v}",
                    # 814G4：卡片文字不重复维度名（维度名已在页头/问题行），
                    # 说明文字逐项差异化白话（防整组说明雷同成天书）
                    "display": v,
                    "description": f"若选此项，成片将按「{v}」制作",
                    "group": dim,
                })
        if len(vals) < 2:
            # 候选不足仍渲染该维度（占位卡 + 自定义输入），不允许悄悄隐藏
            opts.append({
                "label": f"{dim}：{_PLACEHOLDER_DIM_VALUE}",
                "display": _PLACEHOLDER_DIM_VALUE,
                "description": "点「其它（自定义输入）」填写；不填则由模型按剧本拟定",
                "group": dim,
            })
        rendered_dims.append(dim)
    if not opts:
        return "", []
    msg = (
        "以下规格维度尚待您选定：" + "、".join(rendered_dims)
        + "。请逐项选择或自定义输入后发送（直接点选即可），"
        "系统将拼装规格，随后按当前 Skill 流程推进。"
    )
    return msg, opts


def _consume_spec_collected(state: Dict[str, Any]) -> bool:
    """消费 spec_collected 标记（6666 事故：收集向导已回应过，规格写入后的
    暂停不再重复弹向导）；返回是否命中并清除。"""
    inter = state.get("interaction")
    if isinstance(inter, dict) and inter.get("spec_collected"):
        inter.pop("spec_collected", None)
        return True
    return False


def merge_spec_param_wizard(
    state: Dict[str, Any], message: str, options: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], bool]:
    """制作参数未选定时，把候选项向导合并进任意来源的暂停卡（1111 事故：
    模型自发暂停的选项 label 是自造文案如「1K（更快）」，不可机械落盘）。

    与向导同 group 的模型选项被替换为标准「键：值」格式（保证
    apply_spec_param_selections 可解析）；其余选项保留。原暂停文案非空时
    保留（系统永不没收模型的暂停，含文案）；空文案才用向导说明。规格文档
    不存在或参数已定稿时原样返回。返回 (文案, 选项, 是否合并了向导)。
    """
    content = _spec_doc_content(state)
    if not content.strip():
        return message, options or [], False
    if _consume_spec_collected(state):
        # 收集向导已交互过：模型自发暂停原样保留，不重复合并向导（6666 事故）
        return message, options or [], False
    msg, wizard = build_spec_param_options(content, state)
    if not wizard:
        return message, options or [], False
    wizard_groups = {w["group"] for w in wizard}
    kept = [
        o for o in (options or [])
        if isinstance(o, dict) and o.get("group") not in wizard_groups
    ]
    final_msg = message if str(message or "").strip() else msg
    return final_msg, wizard + kept, True


def spec_pause_card(state: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """规格文档写入后的暂停卡：收集向导已交互过时沿用常规审阅暂停卡；
    否则升级为 Skill 软维度候选项向导（6666 二轮：不再含渠道/分辨率/时长）。
    审阅卡下一步选项客观具体（8888 二轮）。"""
    if _consume_spec_collected(state):
        return SPEC_DOC_PAUSED_MSG, spec_review_options(state)
    msg, opts = build_spec_param_options(_spec_doc_content(state), state)
    if opts:
        return msg, opts
    return SPEC_DOC_PAUSED_MSG, spec_review_options(state)


def spec_collect_card(state: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """script_analyze 后的规格收集向导（6666 事故：交互收集必须在规格文档
    写入之前；只渲染 Skill 声明的软维度）。
    0817 B20：总结内嵌仅当当前 Skill 声明总结展示（流程归位）。"""
    summary = str(((state or {}).get("analysis") or {}).get("summary") or "").strip()
    used = (state or {}).get("usedSkills") or []
    skill_name = str(used[-1] or "") if used else ""
    if _pg.skill_declares_summary(skill_name):
        msg = SPEC_COLLECT_PAUSED_MSG.format(summary=summary or "（见剧本分析要点）")
    else:
        msg = SPEC_COLLECT_PAUSED_MSG_NO_SUMMARY
    _m, opts = build_spec_param_options("", state)
    return msg, opts


def apply_spec_param_selections(
    content: str, user_text: str, allow_confirm_intent: bool = True,
) -> Tuple[str, List[str]]:
    """把用户回应里的制作参数选择机械写回规格文档，返回 (新正文, 已定稿项)。

    - 用户明确给出某参数值（向导逐行回传或自由表述）→ 覆盖该行并去掉待确认标记；
    - 参数仍缺值但用户表达了确认意图（确认成片规格/继续…）且
      allow_confirm_intent=True（仅当上一轮暂停确为规格暂停时，1111 事故：
      总结暂停的「确认」不能误定稿规格）→ 按文档当前展示值定稿；
    - 调整类反馈 → 不动，交给模型处理。
    """
    if not content:
        return content, []
    text = str(user_text or "")
    confirm_intent = allow_confirm_intent and bool(_SPEC_CONFIRM_INTENT_RE.search(text))
    applied: List[str] = []

    m = _SPEC_IMG_SEL_RE.search(text)
    img_val = f"{next(g for g in m.groups() if g)}K" if m and any(m.groups()) else ""
    m = _SPEC_VID_SEL_RE.search(text)
    vid_val = f"{next(g for g in m.groups() if g).lower()}p" if m and any(m.groups()) else ""
    m = _SPEC_DUR_SEL_RE.search(text)
    dur_val = f"{next(g for g in m.groups() if g)} 秒" if m and any(m.groups()) else ""

    new_content = content
    for name, pat in _SPEC_PARAM_LINES:
        lm = pat.search(new_content)
        if not lm:
            continue
        line = lm.group(0)
        if not any(k in line for k in SPEC_PARAM_UNCONFIRMED_MARKERS):
            continue
        if name == "图片分辨率":
            val = img_val
        elif name == "视频分辨率":
            val = vid_val
        else:
            val = dur_val
        if val:
            bullet = "- " if line.lstrip().startswith(("-", "*")) else ""
            new_line = f"{bullet}{name}：{val}"
            new_content = new_content[:lm.start()] + new_line + new_content[lm.end():]
            applied.append(f"{name} {val}")
        elif confirm_intent:
            # 用户确认规格整体 → 当前展示值即定稿值，只去掉待确认标记
            cleaned = line
            for k in SPEC_PARAM_UNCONFIRMED_MARKERS:
                cleaned = cleaned.replace(k, "")
            cleaned = re.sub(r"[（(]\s*[）)]", "", cleaned)
            cleaned = cleaned.rstrip(" \t")
            new_content = new_content[:lm.start()] + cleaned + new_content[lm.end():]
            applied.append(f"{name}（按展示值定稿）")
    return new_content, applied


def assemble_spec_doc(
    skill_name: str,
    selections: Dict[str, str],
    model_filled: Optional[Dict[str, str]] = None,
) -> str:
    """按「Skill 维度」机械拼装键值清单规格文档（方案乙；6666 二轮：
    出图/出视频渠道、图片分辨率、视频分辨率、分镜最大时长由顶部
    「全局设置」唯一提供，不再写入规格文档）。

    选定值优先；未选维度用模型自填值；都没有则该行不出现（下游按
    Skill 章节默认值兜底）。结构确定、无剧本分析等杂项——膨胀在结构上不可能。
    """
    lines = ["# 最终成片规格 Final_Video_Spec", ""]
    model_filled = model_filled or {}
    for dim in _pg.skill_spec_dimensions(skill_name):
        v = str(selections.get(dim) or model_filled.get(dim) or "").strip()
        if v:
            lines.append(f"- {dim}：{v}")
    return "\n".join(lines) + "\n"


# 平台层维度说明补注已停用（814G4：说明文字改为逐项差异化白话，
# 维度含义由页头/问题行承载；保留空表防外部引用报错）
_DIM_DESCRIPTION_OVERRIDES: Dict[str, str] = {}
