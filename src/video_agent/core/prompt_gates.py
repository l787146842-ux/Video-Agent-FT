"""
提示词结构闸机（Prompt Gate）— 写入即校验的硬保障。

指令约束（system prompt / Skill 注入）是「贴告示」，遵循是概率性的；
本模块是「装闸机」：提示词写入草稿时按客观可查的结构规则校验，
不合格直接打回（工具返回错误），模型在下一轮自行补全重写（自愈闭环），
对齐外来工作流平台「结构化工具强制参数」的执行力度。

设计原则：
- 只查客观标记（字符级可判定），不做主观质量评判，避免误伤合法提示词；
- 全部复用现有字段（prompt / refAssets / timbre），不引入新字段体系；
- 仅在 Skill 流程激活时启用（由调用方按 injected_skill / gate_enabled 决定），
  日常微调、mock 流程不受影响；
- 模式：strict = 硬拒绝（默认）/ warn = 照存但带回警告 / off = 关闭。
"""
import re
from typing import Any, Dict, List, Tuple

from src.video_agent.config import settings
from src.video_agent.state.models import (
    ALL_CATEGORIES,
    CAT_AUDIO_ITEMS,
    CAT_KEY_ELEMENTS,
)

# 镜头语言客观标记（提示词里出现任一即视为含摄像机层）
_CAMERA_MARKERS = (
    "镜头", "景别", "特写", "全景", "中景", "近景", "远景", "俯瞰", "仰角", "跟拍",
    "推", "拉", "摇", "横移", "环绕", "手持", "shot", "camera", "close-up", "wide",
    "medium", "pan", "orbit", "tracking", "push-in", "pull-back", "crane", "angle",
)

# 音频层客观标记（音效包装符 / 对话包装符 / 音乐描述 / no music 备注）
_AUDIO_MARKERS = ("<", "{", "no music", "no背景音乐", "音效", "旁白")

# 硬性下限（字符数）：低于即打回。取保守值只拦「明显敷衍」，
# 不与 Skill 的质量要求（≥200 字）混同——质量由指令约束兜底，闸机只管结构。
_SHOT_PROMPT_MIN_CHARS = 80
_ELEMENT_PROMPT_MIN_CHARS = 50

# 语言闸（Skill 最高优先级条款：中文输入环境下正文必须中文书写）：
# 中文字符占非空白字符的最低比例。正文中文 + 英文专业术语/包装符的合规提示词
# 中文占比通常在 40% 以上；整段英文（仅对白是中文）会低于该阈值。
_CJK_MIN_RATIO = 0.15
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WS_RE = re.compile(r"\s")

# 对话包装符：{台词}（Seedance 口头对话格式）
_DIALOGUE_RE = re.compile(r"\{[^{}\n]{2,}\}")

# 规格文档名称特征（归一化后包含即命中；Skill 步骤2 的产出物，
# 进入故事板阶段的强制前置）
_SPEC_NAME_HINTS = ("final_video_spec", "finalvideospec", "video_spec", "规格")


def gate_mode() -> str:
    """当前闸机模式：strict / warn / off"""
    return (settings.prompt_gate_mode or "strict").strip().lower()


def has_voice_reference(raw_state: Dict[str, Any]) -> bool:
    """项目里是否存在可用作音色参考的音频（音频草稿带音源，或素材库含音频）"""
    for g in raw_state.get(CAT_AUDIO_ITEMS) or []:
        for d in (g.get("drafts") or []):
            if isinstance(d, dict) and (d.get("audioUrl") or "").strip():
                return True
    for a in raw_state.get("assets") or []:
        if isinstance(a, dict) and a.get("type") == "audio" and (a.get("url") or "").strip():
            return True
    return False


def is_spec_doc_name(name: str) -> bool:
    """文档名是否属于规格文档（大小写/空格/连字符不敏感的包含匹配）"""
    n = str(name or "").lower().replace(" ", "").replace("-", "_")
    return any(h in n for h in _SPEC_NAME_HINTS)


def has_spec_document(raw_state: Dict[str, Any]) -> bool:
    """项目里是否已有规格文档（Skill 步骤2 的产出物，如 Final_Video_Spec.md）。

    名称模糊匹配（大小写/空格/连字符不敏感）且正文非空才算数，
    防止模型建一个空文档绕过闸机。
    """
    for d in raw_state.get("documents") or []:
        if not isinstance(d, dict):
            continue
        if not str(d.get("content") or "").strip():
            continue
        if is_spec_doc_name(d.get("name") or ""):
            return True
    return False


def element_images_missing(raw_state: Dict[str, Any]) -> bool:
    """关键元素已建卡但没有任何概念图（生成或上传）时返回 True。

    Skill 流程时序：镜头提示词必须在元素图像就绪后才编制（镜头要参考元素图）。
    关键元素尚未建卡时返回 False（不适用本闸门）。
    """
    ke_drafts = [
        d
        for g in raw_state.get(CAT_KEY_ELEMENTS) or []
        for d in (g.get("drafts") or [])
        if isinstance(d, dict)
    ]
    return bool(ke_drafts) and not any((d.get("imgUrl") or "").strip() for d in ke_drafts)


def resolve_kind_by_draft_id(
    raw_state: Dict[str, Any],
    draft_id: str,
    draft_type: str = "",
    selected_draft_id: str = "",
    selected_type: str = "",
) -> str:
    """按草稿 ID / 编号 / "current" 在状态里反查所属类别：keyElement | shot | audio | ''。

    draft_id 为空时不反查（调用方自行决定是否放行）；"current" 按前端选中草稿
    解析，未选中时回落第一个可用草稿（与 ops.find_draft 兜底语义一致）。
    """
    if not draft_id:
        return ""
    from src.video_agent.state import storyboard_ops as ops
    try:
        found = ops.find_draft(
            raw_state, str(draft_id), str(draft_type or ""),
            selected_draft_id=selected_draft_id, selected_type=selected_type,
        )
    except Exception:
        return ""
    if not found:
        return ""
    group = found[0] if isinstance(found, tuple) else {}
    gid = str((group or {}).get("id", ""))
    if gid.startswith("ke-"):
        return "keyElement"
    if gid.startswith("shot-"):
        return "shot"
    if gid.startswith("audio-"):
        return "audio"
    return ""


def validate_prompt_write(
    prompt: str,
    kind: str,
    raw_state: Dict[str, Any] | None = None,
) -> Tuple[bool, List[str], List[str]]:
    """校验一条待写入的生成提示词。

    Args:
        prompt: 待写入的提示词全文
        kind: 目标类别 keyElement | shot | audio（audio 不校验）
        raw_state: 当前工作台状态（音色参考软提醒用；None 时跳过软提醒）

    Returns:
        (ok, hard_errors, soft_warnings)
        ok=False 且模式为 strict 时，调用方必须拒绝本次写入并把
        hard_errors 带回给模型，让其补齐后重写。
    """
    text = (prompt or "").strip()
    hard: List[str] = []
    soft: List[str] = []
    if not text or kind not in ("shot", "keyElement"):
        return True, hard, soft

    lower = text.lower()

    # 语言闸（shot / keyElement 通用）：正文必须中文书写，仅专业技术术语可保留英文。
    # 外文 Skill 的「写成英语描述」类表述与最高优先级条款冲突时，以最高优先级为准。
    total_chars = len(_WS_RE.sub("", text))
    cjk_chars = len(_CJK_RE.findall(text))
    if total_chars and cjk_chars / total_chars < _CJK_MIN_RATIO:
        hard.append(
            "提示词正文必须用中文书写（Skill 最高优先级条款）：主体描述/动作表演/场景环境/"
            "镜头语言叙述都用中文，仅专业风格/光影/构图/渲染技术术语可保留英文原词；"
            "当前提示词正文几乎全是英文，请改写为中文正文后重新写入"
        )

    if kind == "shot":
        if len(text) < _SHOT_PROMPT_MIN_CHARS:
            hard.append(
                f"分镜视频提示词过短（{len(text)} 字），请按 Skill「提示词写法」完整描述"
                "（摄像机 → 主体 → 空间 → 音频），不得敷衍压缩"
            )
        if "时长" not in text and "duration" not in lower:
            hard.append(
                "分镜视频提示词缺少镜头时长：须在提示词中写明本镜头总时长"
                "（如「镜头总时长：15秒」，与分镜结构的时长字段一致），"
                "生视频模型无法从其他渠道得知镜头时长"
            )
        if "no subtitles" not in lower:
            hard.append("分镜视频提示词缺少负面约束「no subtitles」（字幕在后期添加，Skill 要求必须包含）")
        if not any(m in text or m in lower for m in _AUDIO_MARKERS):
            hard.append(
                "分镜视频提示词缺少音频层：须含对话 {…} / 音效 <…> / 音乐 (…) 之一，"
                "或明确写「no music」（Skill 要求几乎总是包含）"
            )
        if not any(m in text or m in lower for m in _CAMERA_MARKERS):
            hard.append("分镜视频提示词缺少镜头语言：须写明景别/角度/运动（如 缓慢推入、环绕、cut to new angle）")
        # 软提醒：有对白且项目存在音色参考，但未说明音色参考分配
        if (
            raw_state is not None
            and _DIALOGUE_RE.search(text)
            and has_voice_reference(raw_state)
            and "音色参考" not in text
        ):
            soft.append(
                "该镜头含对白且项目已有音色参考音频，建议在提示词中写明哪个角色使用哪个音色参考，"
                "并在草稿 refAssets/timbre 中绑定对应音频，以保证跨镜头声音一致"
            )
        # 软提醒（流程时序）：关键元素还没有任何图像（生成/上传）就写分镜提示词——
        # 按 Skill 流程应先引导用户出图/上传元素图像，镜头需参考元素图像；
        # strict 模式下由调用方凭 element_images_missing() 升级为硬拒绝
        if raw_state is not None and element_images_missing(raw_state):
            soft.append(
                "关键元素目前还没有任何概念图（生成或上传），按 Skill 流程应先暂停引导用户"
                "生成/上传元素图像，就绪后再编制分镜提示词（镜头要参考元素图像）"
            )
    else:  # keyElement
        if len(text) < _ELEMENT_PROMPT_MIN_CHARS:
            hard.append(
                f"关键元素提示词过短（{len(text)} 字），请按 Skill「提示词写法」给出完整的"
                "主体身份/特征细节/氛围基调描述"
            )

    ok = not hard
    return ok, hard, soft


def format_gate_errors(errors: List[str]) -> str:
    """把硬拒绝原因格式化为给模型的工具错误文案（引导其补齐重写）"""
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "提示词结构校验未通过（闸机拦截，本次写入被拒绝）：\n"
        f"{lines}\n"
        "请严格按所选 Skill 的「提示词写法」章节补齐上述缺失后，重新调用工具写入完整提示词。"
    )


SPEC_GATE_ERROR = (
    "流程闸机拦截：最终视频规格文档尚未写入。按 Skill 流程，必须先基于用户确认的规格方案"
    "调用 document_write 写入 Final_Video_Spec.md（标题、类型、画幅、时长、视觉风格、语言、"
    "模型偏好），并暂停请用户审阅；规格文档就绪前严禁开始搭建故事板结构。"
)

# 结构搭建阶段内联提示词的容忍上限（字符）：超过即视为「详细生成提示词」，
# 属于步骤4 的产出，结构搭建（步骤3）阶段只建 title/desc/roughDesc 骨架
STRUCTURE_INLINE_PROMPT_MAX = 40

STORYBOARD_PENDING_GATE_ERROR = (
    "流程闸机拦截：故事板结构刚建立，正在等待用户审阅确认（确认/调整）。按 Skill 流程，"
    "必须在用户确认故事板后才开始编写提示词草案（步骤4）。请先暂停等待用户回应，"
    "不要在本轮继续写提示词。本次写入已被拒绝。"
)

STORYBOARD_STRUCTURE_PAUSED_MSG = (
    "关键元素拆分已建立，请审阅左侧故事板的元素拆分结果（数量/命名/描述），"
    "选择接下来的推进方式；确认后我先为各关键元素编写生图提示词草案，再继续后续拆分。"
)

STORYBOARD_STRUCTURE_OPTIONS = [
    {
        "label": "确认关键元素拆解，开始为关键元素编写提示词",
        "description": "元素拆分无误，下一步为各元素编写生图提示词草案（概念图在提示词确认后再生成）",
    },
    {"label": "调整关键元素拆分", "description": "告诉我需要增删改的元素"},
]

# 分镜拆解完成后的暂停文案（步骤3 分镜结构 → 步骤4 提示词草案 分界）：
# 结构阶段只建骨架、不写详细提示词，确认卡片必须引导用户审阅拆分方案，
# 而不是声称提示词已写好或直接引导生成（8888 事故：拆完分镜即引导「确认草案，开始生成视频」）
SHOT_STRUCTURE_PAUSED_MSG = (
    "分镜拆解已完成，请在左侧故事板审阅分镜拆分方案（镜头数量/时间轴/镜头语言）；"
    "详细的视频提示词草案尚未编写，确认拆分方案后我再为每个分镜编写视频生成提示词草案。"
)

SHOT_STRUCTURE_OPTIONS = [
    {
        "label": "确认分镜拆分方案，继续编写视频提示词",
        "description": "分镜拆分无误，下一步为每个分镜编写视频生成提示词草案（写完后再请您确认提示词）",
    },
    {"label": "调整分镜拆分", "description": "告诉我需要增删改的镜头"},
]

_STRUCTURE_KIND_ALIAS = {
    "keyelement": "keyElement", "keyelements": "keyElement",
    "shot": "shot", "shots": "shot",
    "audio": "audio", "audioitems": "audio",
}


def normalize_structure_kind(kind: str) -> str:
    """分组类别归一化：keyElement | shot | audio | ''"""
    return _STRUCTURE_KIND_ALIAS.get(str(kind or "").strip().lower(), "")


def structure_paused_confirmation(kinds) -> Tuple[str, List[Dict[str, str]]]:
    """按本批搭建的结构类别返回（暂停文案, 候选选项）。

    含 shot → 分镜拆分审阅文案（下一步编写视频提示词）；
    否则 → 关键元素拆分审阅文案（下一步编写生图提示词）。
    文案由系统按客观状态生成，杜绝模型虚报「提示词已写好/开始生成」。"""
    norm = {normalize_structure_kind(k) for k in (kinds or set())}
    if "shot" in norm:
        return SHOT_STRUCTURE_PAUSED_MSG, list(SHOT_STRUCTURE_OPTIONS)
    return STORYBOARD_STRUCTURE_PAUSED_MSG, list(STORYBOARD_STRUCTURE_OPTIONS)

# 规格文档写入后的引导选项（步骤2→步骤3 分界：确认后开始拆分关键元素）
SPEC_DOC_OPTIONS = [
    {
        "label": "确认成片规格，开始拆分关键元素",
        "description": "规格内容无误，下一步按 Skill 拆分关键元素（角色/场景/道具）",
    },
    {"label": "调整成片规格", "description": "告诉我需要修改的规格条目"},
]

KEY_ELEMENT_FIRST_GATE_ERROR = (
    "流程闸机拦截：首次搭建故事板必须先拆分关键元素（角色/场景/道具）。"
    "请先只创建 keyElement 分组并暂停请用户确认元素拆分；"
    "用户确认后再创建分镜（shot）与音频（audio）分组。本次分镜/音频分组创建已被拒绝。"
)


def storyboard_is_empty(raw_state: Dict[str, Any]) -> bool:
    """故事板是否完全为空（无任何分组）：用于判定「首次搭建」批次"""
    return not any(
        raw_state.get(cat)
        for cat in ALL_CATEGORIES
    )


def storyboard_pending(raw_state: Dict[str, Any]) -> bool:
    """故事板结构是否正处于「等待用户确认」窗口（步骤3→步骤4 的分界）。

    结构首次建立时由执行器置位，用户下一条消息到达时随 awaiting_confirmation
    一起清除；窗口内严禁写入详细提示词，保证分批确认不被合并。
    """
    interaction = raw_state.get("interaction") or {}
    return bool(interaction.get("storyboard_pending"))


GENERATION_CONFIRM_GATE_ERROR = (
    "流程闸机拦截：目标草稿的 Prompt Draft 尚未经用户审阅确认（tag 非「已确认」）。"
    "按 Skill 流程：先把提示词草案展示给用户并暂停等待审阅；用户确认后再触发生成。"
    "若用户已在当前消息中明确表示确认，可先调用 storyboard_confirm_draft 将目标草稿"
    "标记为「已确认」，再重新触发生成。本次生成已被拒绝。"
)


def drafts_confirmed(raw_state: Dict[str, Any], drafts: List[Dict[str, Any]]) -> bool:
    """目标草稿是否全部已经用户确认（tag == 已确认）。空列表返回 False。

    确认状态的完整闭环：提示词写入时 tag 重置为 Agent（重写即作废），
    用户回应暂停时晋升为已确认，或模型按用户明确指示调 confirm_draft 落点。
    """
    if not drafts:
        return False
    return all(str(d.get("tag") or "").strip() == "已确认" for d in drafts)


# ---------- 阶段探测驱动的工具裁剪（混合形态第一层：工具可见性边界） ----------

# 故事板结构工具集（无规格文档阶段不下发）
STORYBOARD_STAGE_TOOLS = frozenset({
    "storyboard_create_group", "storyboard_patch_draft", "storyboard_add_draft",
    "storyboard_delete_group", "storyboard_confirm_draft", "storyboard_media_to_chat",
    "read_draft",
})
# 草稿生成工具集（故事板结构就绪前不下发；对话内直出的 generate_image 不受影响）
GENERATION_STAGE_TOOLS = frozenset({"image_generate", "generate_video"})


def stage_tool_restrictions(raw_state: Dict[str, Any]) -> tuple:
    """按制作阶段的客观状态计算本轮应裁剪的工具集与说明文案。

    返回 (excluded: frozenset, note: str)。检测信号全部客观可查：
    - 无规格文档 → 故事板结构工具 + 生成工具都不下发（先写规格）；
    - 有规格但故事板为空 → 生成工具不下发（先建结构）；
    - 其他阶段 → 不追加裁剪。
    裁剪只是第一层（软）：文本动作轨不受影响，由既有闸机做第二层兑底。
    """
    if not has_spec_document(raw_state):
        return (
            STORYBOARD_STAGE_TOOLS | GENERATION_STAGE_TOOLS,
            "【当前阶段工具边界】成片规格尚未定稿：故事板与生成类工具暂未开放。"
            "请先用 document_write 写入 Final_Video_Spec.md 并暂停请用户审阅，"
            "规格确认后系统会自动开放后续工具。",
        )
    has_groups = any(
        raw_state.get(cat)
        for cat in ALL_CATEGORIES
    )
    if not has_groups:
        return (
            GENERATION_STAGE_TOOLS,
            "【当前阶段工具边界】故事板结构尚未建立：生成类工具暂未开放。"
            "请先搭建关键元素/分镜/音频分组并请用户审阅，结构就绪后系统会自动开放生成工具。",
        )
    return frozenset(), ""

SHOT_SEQUENCE_GATE_ERROR = (
    "流程闸机拦截：关键元素还没有任何概念图（生成或上传），按 Skill 流程分镜提示词必须在"
    "元素图像就绪后才编制（镜头生成要参考元素图像）。请先暂停，引导用户确认生成/上传"
    "关键元素概念图；图像就绪后再回来编写分镜提示词。本次写入已被拒绝。"
)
