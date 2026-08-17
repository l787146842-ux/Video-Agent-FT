"""闸机文案/卡片族（九轮 B3b 自 prompt_gates.py 切出，R4b 拆分模式延续）。

闸机文案外置加载（_gate_msg/_gate_json，prompts/gates/messages.md 单一事实源）
+ 全部用户可见文案常量与卡片组装（规格闸/结构暂停卡/规格审阅选项/草稿审阅卡/
生成确认闸/镜头顺序闸）。prompt_gates 尾部 re-export 保持既有引用路径不变
（宪法 §12 登记壳；零行为变更，代码逐字迁移）。
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS
from src.video_agent.utils.prompts import load_prompt_section

# ---------- 闸机文案外置（宪法 §2.3；814R2 恢复） ----------
#
# prompts/gates/messages.md 是闸机文案单一事实源；代码内置文案仅作分节
# 缺失时的兜底（行为不回退）。回喂模型与展示用户用同一源，防两套说辞。
_GATE_MSG_FILE = "gates/messages.md"


def _gate_msg(section: str, fallback: str) -> str:
    """文案分节加载：messages.md 优先，缺失回落内置兜底"""
    return load_prompt_section(_GATE_MSG_FILE, section) or fallback


def _gate_json(section: str, fallback: Any) -> Any:
    """JSON 分节加载（暂停卡 message/options）；解析失败回落内置兜底"""
    raw = load_prompt_section(_GATE_MSG_FILE, section)
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


SPEC_GATE_ERROR = _gate_msg("SPEC_GATE", (
    "流程警告：规格文档尚未写入。建议先调用 document_write 写入规格文档"
    "（标题、类型、画幅、时长、视觉风格、语言、模型偏好等制作参数）并请用户审阅；"
    "本次故事板结构已按用户要求照常搭建，规格文档仍建议补写。"
))

# 结构搭建阶段内联提示词的容忍上限（字符）：保留兼容常量，
# 当前策略下不再剥离内联提示词，详细内容随建卡一并写入
STRUCTURE_INLINE_PROMPT_MAX = 40

STORYBOARD_PENDING_GATE_ERROR = _gate_msg("STORYBOARD_PENDING", (
    "流程警告：故事板结构尚未经用户确认。按 Skill 流程建议先请用户审阅拆分方案再写提示词；"
    "本次提示词已按用户要求照常写入，请同时在回复中提示用户审阅左侧故事板。"
))

_STORYBOARD_STRUCTURE_PAUSED = _gate_json("STORYBOARD_STRUCTURE_PAUSED", {
    "message": (
        "关键元素拆分已建立，请审阅左侧故事板的元素拆分结果（数量/命名/描述）；"
        "确认无误后按当前 Skill 流程推进下一阶段。"
    ),
    "options": [
        {
            "label": "确认关键元素拆解，继续编写元素生图提示词草案",
            "description": "元素拆分无误，下一步为各关键元素编写生图提示词草案",
        },
        {"label": "调整关键元素拆分", "description": "告诉我需要增删改的元素"},
    ],
})
STORYBOARD_STRUCTURE_PAUSED_MSG = str(_STORYBOARD_STRUCTURE_PAUSED.get("message", ""))

STORYBOARD_STRUCTURE_OPTIONS = list(_STORYBOARD_STRUCTURE_PAUSED.get("options") or [])

# 分镜拆解完成后的暂停文案（结构 → 提示词 分界）：
# 结构阶段只建骨架、不写详细提示词，确认卡片必须引导用户审阅拆分方案，
# 而不是声称提示词已写好或直接引导生成（8888 事故：拆完分镜即引导「确认草案，开始生成视频」）；
# 下一步文案不写死具体阶段（S1：不同 Skill 的下一步不同，以各自流程为准）
_SHOT_STRUCTURE_PAUSED = _gate_json("SHOT_STRUCTURE_PAUSED", {
    "message": (
        "分镜拆解已完成，请在左侧故事板审阅分镜拆分方案（镜头数量/时间轴/镜头语言）；"
        "确认无误后按当前 Skill 流程推进下一阶段。"
    ),
    "options": [
        {
            "label": "确认分镜拆分方案，继续编写视频提示词草案",
            "description": "分镜拆分无误，下一步为各分镜编写视频提示词草案",
        },
        {"label": "调整分镜拆分", "description": "告诉我需要增删改的镜头"},
    ],
})
SHOT_STRUCTURE_PAUSED_MSG = str(_SHOT_STRUCTURE_PAUSED.get("message", ""))

SHOT_STRUCTURE_OPTIONS = list(_SHOT_STRUCTURE_PAUSED.get("options") or [])

_STRUCTURE_KIND_ALIAS = {
    "keyelement": "keyElement", "keyelements": "keyElement",
    "shot": "shot", CAT_SHOTS: "shot",
    "audio": "audio", "audioitems": "audio",
}


def normalize_structure_kind(kind: str) -> str:
    """分组类别归一化：keyElement | shot | audio | ''"""
    return _STRUCTURE_KIND_ALIAS.get(str(kind or "").strip().lower(), "")


def structure_paused_confirmation(kinds) -> Tuple[str, List[Dict[str, str]]]:
    """按本批搭建的结构类别返回（暂停文案, 候选选项）。

    含 shot → 分镜拆分审阅文案；否则 → 关键元素拆分审阅文案。
    文案由系统按客观状态生成，杜绝模型虚报「提示词已写好/开始生成」；
    下一步不写死具体阶段，以当前 Skill 流程为准（S1）。"""
    norm = {normalize_structure_kind(k) for k in (kinds or set())}
    if "shot" in norm:
        return SHOT_STRUCTURE_PAUSED_MSG, list(SHOT_STRUCTURE_OPTIONS)
    return STORYBOARD_STRUCTURE_PAUSED_MSG, list(STORYBOARD_STRUCTURE_OPTIONS)

# 规格文档写入后的引导选项（8888 二轮：下一步客观具体，不再「按流程继续」黑盒）
SPEC_DOC_OPTIONS = _gate_json("SPEC_DOC_OPTIONS", [
    {
        "label": "确认成片规格，按流程继续",
        "description": "规格内容无误，按当前 Skill 流程推进下一阶段",
    },
    {"label": "调整成片规格", "description": "告诉我需要修改的规格条目"},
])


def spec_review_options(state: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """规格审阅卡的下一步选项（0817 B22 中性化：平台不点名下一步，
    一律「按当前 Skill 流程推进」；流程排序意见归 Skill）。"""
    return list(SPEC_DOC_OPTIONS)

# script_analyze 后的规格收集暂停卡（6666 事故：原「确认总结」闸被用户判定多余——
# 规格交互本身就是暂停点；改为解析完成后直接进入规格收集向导）。
# 4444 方案乙：收集完成后规格文档由系统机械拼装，模型不再手写。
# 8888 二轮：总结直接内嵌表述（不再「见上」）；删除开发者视角的
# 「按 Skill 声明」与全局设置解释句（用户审定）。
SPEC_COLLECT_PAUSED_MSG = (
    "剧本读完了。一句话故事总结：{summary}\n"
    "接下来我为这部片子拼装一份制片规格，请逐项选定以下维度"
    "（点选或自定义输入；不选的由我按剧本拟定后给您过目）。"
    "选完发给我，自动拼装规格并请您审阅。"
)

SPEC_COLLECT_KIND = "collect"

# 0817 B20：未声明总结展示的 Skill 用无总结版（流程归位，平台不全局化）
SPEC_COLLECT_PAUSED_MSG_NO_SUMMARY = (
    "剧本读完了。\n"
    "接下来我为这部片子拼装一份制片规格，请逐项选定以下维度"
    "（点选或自定义输入；不选的由我按剧本拟定后给您过目）。"
    "选完发给我，自动拼装规格并请您审阅。"
)

# 规格文档拼装/写入后的系统级暂停文案（5555 事故：模型幻觉已暂停、实际直冲拆解）：
# 模型同批未自发 workflow_pause/request_confirmation 时，由执行层注入此文案；
# 下一步不写死具体阶段（启用条件按规格流程客观特征自动检测，2222 二轮；后续阶段以各自流程为准）；
# 模型自填项必须逐条过目（888 事故：风格类参数模型拍板用户不知情）
SPEC_DOC_PAUSED_MSG = (
    "制片规格已按您的选定拼装完成，请审阅规格条目；未选维度由模型根据剧本拟定自填，请逐条过目，"
    "如需调整直接告诉我。确认后按当前 Skill 流程推进下一阶段。"
)

# ---------- 一句话总结展示去重（9999 事故：正文出现两遍总结） ----------
# 模型自己展示总结时常改写引号/标点（“启示” vs "启示"），裸子串判重失效，
# 系统兜底又拼一份 → 两段重复。归一化后判重：去引号/加粗符/空白再比对，
# 另以开头 24 字容错末尾措辞微调。
_SUMMARY_QUOTE_CHARS = "“”‘’\"'`*_ \t\r\n\u3000"


def _norm_summary_text(text: str) -> str:
    t = str(text or "")
    for ch in _SUMMARY_QUOTE_CHARS:
        t = t.replace(ch, "")
    return t


def summary_already_visible(visible: str, summary: str) -> bool:
    """判定可见正文是否已展示过该总结（引号/加粗/空白不敏感）。

    summary 为空时返回 True（没有可拼的内容，调用方直接跳过）。
    """
    ns = _norm_summary_text(summary)
    if not ns:
        return True
    nv = _norm_summary_text(visible)
    if ns in nv:
        return True
    head = ns[:24]
    return bool(head) and head in nv


# ---------- 规格制作参数待确认兜底（9999 事故：三项参数标着「待确认」就放行） ----------
# Skill 要求图片分辨率/视频分辨率/分镜最大时长必须在规格交互中给候选项由
# 用户选定；笨模型会写「待确认」占位就暂停。系统兜底：检测未确认项 →
# 暂停卡升级为候选项向导，用户回应时机械落盘（chat_service 消费）。
from src.video_agent.state.provider_prefs import SPEC_PARAM_UNCONFIRMED_MARKERS  # noqa: E402

_SPEC_PARAM_LINES: Tuple[Tuple[str, re.Pattern], ...] = (
    ("图片分辨率", re.compile(r"(?im)^\s*(?:[-*]\s*)?(?:图片|图像|出图)分辨率\s*[:：].*$")),
    ("视频分辨率", re.compile(r"(?im)^\s*(?:[-*]\s*)?(?:视频|出视频)分辨率\s*[:：].*$")),
    ("分镜最大时长", re.compile(r"(?im)^\s*(?:[-*]\s*)?(?:分镜|单镜头|镜头)?最大时长\s*[:：].*$")),
)

# 用户回应里的选择解析（向导回传格式为逐行「键：值」，也兼容自由表述）
_SPEC_IMG_SEL_RE = re.compile(r"(?im)(?:图片|图像|出图)分辨率\s*[:：]\s*([124])\s*K|(?<![0-9A-Za-z])([124])K(?![A-Za-z])")
_SPEC_VID_SEL_RE = re.compile(r"(?im)(?:视频|出视频)分辨率\s*[:：]\s*(480|720|1080)\s*p|(?<![0-9])(480|720|1080)p", re.IGNORECASE)
_SPEC_DUR_SEL_RE = re.compile(r"(?im)(?:分镜|单镜头)?最大时长\s*[:：]\s*(\d{1,2})\s*秒?(?:/镜头)?|(\d{1,2})\s*秒(?:/镜头)?")
_SPEC_CONFIRM_INTENT_RE = re.compile(r"确认|没问题|无误|可以|同意|继续|开始|OK|ok|好的")


def parse_hard_selections(user_text: str) -> Dict[str, str]:
    """解析用户回应里的三项硬参数选择，键用规格文档行键（4444 方案乙存档用）。"""
    out: Dict[str, str] = {}
    text = str(user_text or "")
    m = _SPEC_IMG_SEL_RE.search(text)
    if m and any(m.groups()):
        out["图片分辨率"] = f"{next(g for g in m.groups() if g)}K"
    m = _SPEC_VID_SEL_RE.search(text)
    if m and any(m.groups()):
        out["视频分辨率"] = f"{next(g for g in m.groups() if g).lower()}p"
    m = _SPEC_DUR_SEL_RE.search(text)
    if m and any(m.groups()):
        out["分镜最大时长"] = f"{next(g for g in m.groups() if g)} 秒"
    return out


# ---------- 软制作参数（4444 复盘：维度来自 Skill，平台不预设） ----------
# 向导的软维度 = Skill 规格编写步骤客观声明的维度（如「AI-短剧」画幅比例/
# 目标时长/影像风格基调/输出语言）；候选由内层模型按剧本逐维出题，落
# interaction.spec_soft_candidates；用户不选则放行、模型自填（不拦人）。
# 平台固定六维及「声音风格/目标观众」文案已于 4444 二轮整体删除。
_SPEC_WRITE_ENUM_RE = re.compile(r"[（(]([^（）()]+)[）)]")
_SPEC_WRITE_VERB_RE = re.compile(r"写入|编写|初始化|拟定")
# 规格维度优先解析「建议条目：…」整段（去掉括号注解后按 /、，、；切分）
_SPEC_SUGGESTED_RE = re.compile(r"建议条目\s*[:：]\s*([^）)；。\n]+)")










































# ---------- 规格文档系统拼装（4444 方案乙：模型不手写规格） ----------


# 4444（C3/P4）：提示词草案写入后 Skill 要求暂停审阅，模型该停没停时
# 层 9 兜底注入（与规格审阅卡同构；10.7「Skill 暂停点 + 层 9 兜底缺一不可」）
DRAFTS_REVIEW_MSG = (
    "提示词草案已写入，请在左侧故事板审阅草案内容；"
    "确认后我将按全局设置中的生成渠道触发生成。"
)
DRAFTS_REVIEW_OPTIONS = [
    {"label": "确认提示词草案，开始生成概念图",
     "description": "将目标草稿标记为已确认并触发生成"},
    {"label": "先调整提示词", "description": "告诉我需要修改的草稿与修改意见"},
]


def drafts_review_card() -> Tuple[str, List[Dict[str, str]]]:
    """提示词草案审阅暂停卡（层 9 兜底，4444）。"""
    return DRAFTS_REVIEW_MSG, list(DRAFTS_REVIEW_OPTIONS)


GENERATION_CONFIRM_GATE_ERROR = _gate_msg("GENERATION_CONFIRM", (
    "流程警告：目标草稿的 Prompt Draft 尚未经用户审阅确认（tag 非「已确认」）。"
    "按 Skill 流程建议先展示草案并等待确认；本次生成已按用户要求照常触发，"
    "请同时在回复中提示用户审阅草稿。"
))

# 4444：模型自发跳确认（本轮用户消息无跳过指令）→ 拒收而非放行。
# 「只警告不拦人」保护的是用户意志；模型违反 Skill 暂停语义不属用户意志。
GENERATION_CONFIRM_GATE_BLOCKED = _gate_msg("GENERATION_CONFIRM_BLOCKED", (
    "流程拦截：目标草稿的 Prompt Draft 尚未经用户审阅确认。请先展示草案并调用"
    "暂停工具请求用户审阅；仅当用户在本次消息中明确要求「直接生成/不用确认」"
    "时才可直接触发生成。"
))

SHOT_SEQUENCE_GATE_ERROR = _gate_msg("SHOT_SEQUENCE", (
    "流程警告：关键元素还没有任何概念图（生成或上传）。按 Skill 流程建议先让元素概念图就绪"
    "再编制分镜提示词（镜头可参考元素图像）；本次分镜提示词已按用户要求照常写入，"
    "若后续生成视频需要参考图，请先补足元素图像。"
))
