"""
提示词结构校验（Prompt Gate）— 写入即校验，按模式区分处置。

语义基线（与 prompts/gates/messages.md 一致）：流程闸对用户只警告不拦人；
结构闸 strict 下拒收重写。指令约束（system prompt / Skill 注入）是「贴告示」，
遵循是概率性的；本模块做客观可查的结构校验：
- strict：校验未通过时该次写入被闸机拒收，校验意见结构化回喂模型修正重写；
- warn：校验未通过时写入按用户要求照常生效，校验意见作为警告随回复返回，
  让用户在知情前提下自行决定是否采纳；
- off：完全关闭。
用户明确坚持时可签发覆盖放行（硬伤降为警告，见 guard_pipeline 覆盖分支）；
指令优先级声明见 shared/iron_rules_header.md（单一表述源）。

设计原则：
- 只查客观标记（字符级可判定），不做主观质量评判，避免误伤合法提示词；
- 全部复用现有字段（prompt / refAssets / timbre），不引入新字段体系；
- 仅在 Skill 流程激活时启用（由调用方按 injected_skill / gate_enabled 决定），
  日常微调流程不受影响；
- 模式：strict = 拒收重写（校验未通过拦下写入）、warn = 照常执行 + 返回警告
  （默认）、off = 完全关闭。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from src.video_agent.config import settings
from src.video_agent.core.spec_rules import find_spec_doc
# v3 language 声明读取：registry 顶层不依赖 core，无环；
# 经模块属性访问保住测试 patch 目标（monkeypatch registry.skill_language 即生效）
from src.video_agent.skill_runtime import registry
from src.video_agent.state.models import (
    ALL_CATEGORIES,
    CAT_AUDIO_ITEMS,
    CAT_KEY_ELEMENTS,
    CAT_SHOTS,
)
from src.video_agent.utils.prompts import load_prompt_section

# 闸机规则注册表数据层在 core/gate_registry.py：纯数据 + 归一函数，
# 无判定逻辑；承重壳 re-export 保持既有引用路径不变（宪法 §12 登记壳，coupling_registry
# R13 登记；gate_registry 顶层无依赖，不触 prompt_gates→gates_inputs 导入顺序约束）。
from src.video_agent.core.gate_registry import (
    LAYER_PLATFORM, LAYER_SKILL, LAYER_SESSION,
    GateRuleMeta, GATE_RULES, RULE_ALIASES, normalize_rule_id,
)

# 硬性下限（字符数）：低于即打回。取保守值只拦「明显敷衍」——
# 平台固定地板，不可被 Skill 调整（C1a 裁决 2026-08-31：技能级闸层删除）。
_SHOT_PROMPT_MIN_CHARS = 80
_ELEMENT_PROMPT_MIN_CHARS = 50

# 语言闸（中文输入环境下正文必须中文书写）：
# 中文字符占非空白字符的最低比例。正文中文 + 英文专业术语/包装符的合规提示词
# 中文占比通常在 40% 以上；整段英文（仅对白是中文）会低于该阈值。
# 平台固定地板；英文锁定只经用户规格选择 / Skill language 声明轴（见
# resolve_prompt_language），不再经 gates 键调整。
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


# ---------- 闸机豁免（指令优先级声明见 shared/iron_rules_header.md） ----------

# 闸机豁免作用域枚举：只认前端「本次放行」按钮携带的 scope
#（豁免唯一权威入口 = GateWarnings 按钮随消息携带 gate_overrides）。
GATE_STRUCTURE = "structure"            # 提示词结构闸（字数/语言/时长/字幕/音频/镜头语言）
GATE_FLOW_PAUSE = "flow_pause"          # 流程暂停兜底闸（总结/规格暂停卡）：仅 scope=all 豁免，
# 「跳过概念图」等特定意图不涵盖（用户只是不想等图，不是不要交互分界）

# 一次性放行作用域枚举——前端按钮/后端消费/trace 记录三端引用同一语义。
GATE_OVERRIDE_SCOPE_ALL = "all"                          # 本轮闸机全部豁免（单次生效）
GATE_OVERRIDE_SCOPE_FLOW = "flow"                        # 流程门禁豁免（用户坚持全速推进）


def override_covers(scope: Any, gate: str) -> bool:
    """覆盖作用域是否涵盖指定闸。

    兼容旧布尔语义：True 等价 "all"；False/空串不涵盖任何闸。
    """
    if scope is True:
        scope = "all"
    if not scope:
        return False
    if scope == "all":
        return True
    return scope == gate


# 用户坚持全速推进（scope=all）时，系统暂停兜底卡豁免注入的正文提示
FLOW_PAUSE_OVERRIDE_WARNING = (
    "已按你的要求全速推进：本轮未弹出流程暂停确认卡（总结/规格审阅），"
    "已写入的内容照常生效；如需补看或调整，随时告诉我。"
)


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


def text_mentions_spec_doc(text: str) -> bool:
    """文本是否提及规格文档（与 is_spec_doc_name 同一份名称特征源）。

规格向导客观流程检测的判据——Skill 正文提及规格文档名
    即视为其流程含规格编写环节。
    """
    n = str(text or "").lower().replace(" ", "").replace("-", "_")
    return any(h in n for h in _SPEC_NAME_HINTS)


# ---------- 剧本原料闸----------
# 剧本闸家族实现体在 core/gates_script.py；
# 本文件尾部 re-export 保持既有引用路径不变（登记壳，见尾块注释）。


def has_spec_document(raw_state: Dict[str, Any]) -> bool:
    """项目里是否已有规格文档（Skill 步骤2 的产出物，如 制片规格.md）。

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


_SPEC_LANG_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?输出语言(?:\*\*)?\s*[:：]\s*(.+)$")

# 语言闸硬拒稳定信号（前缀供调用方稳定判别）
LANG_EN_HARD_PREFIX = "提示词正文几乎全是英文"

def spec_output_language(raw_state: Optional[Dict[str, Any]]) -> str:
    """规格文档里用户选定的「输出语言」维度值（未选/无规格返回空串）。"""
    if not raw_state:
        return ""
    doc = find_spec_doc(raw_state)
    if doc is None:
        return ""
    m = _SPEC_LANG_LINE_RE.search(str(doc.get("content") or ""))
    return m.group(1).strip().strip("*").strip() if m else ""


def resolve_prompt_language(
    raw_state: Optional[Dict[str, Any]],
    skill_name: str = "",
) -> str:
    """ 语言单一事实源裁决：用户选择（规格输出语言）> Skill 声明
    （v3 language.prompt=en）> 平台默认（中文）。
    注入句与语言闸读同一结果，by construction 不可能再打架。
    （C1a 裁决 2026-08-31：gates 键 cjk_min_ratio 调整轴退役，
    英文锁定只经本裁决的用户选择/声明两轴）。"""
    sel = spec_output_language(raw_state)
    if sel:
        has_cn = "中" in sel
        has_en = ("英" in sel) or ("双语" in sel)
        if has_cn and has_en:
            return "中英双语"
        if has_en and not has_cn:
            return "英文"
        return "中文"
    try:
        wanted = skill_name or registry.fallback_skill_from_state(
            raw_state if isinstance(raw_state, dict) else None)
        if wanted and str(
            (registry.skill_language(wanted) or {}).get("prompt") or ""
        ) == "en":
            return "英文"
    except Exception:
        pass  # 声明读取失败回落现状判定（不误拦）
    return "中文"


def validate_prompt_write(
    prompt: str,
    kind: str,
    raw_state: Dict[str, Any] | None = None,
) -> Tuple[bool, List[str], List[str]]:
    """校验一条待写入的生成提示词（平台固定地板：字数 + 语言闸）。

    Args:
        prompt: 待写入的提示词全文
        kind: 目标类别 keyElement | shot | audio（audio 不校验）
        raw_state: 当前工作台状态（音色参考软提醒用；None 时跳过软提醒）

    Returns:
        (ok, hard_errors, soft_warnings)
        ok=False 的处置由调用方按闸机模式决定（见 guard_pipeline）：
        strict 下拒收本次写入并把 hard_errors 回喂模型修正重写；
        warn（默认）下照常写入并把 hard_errors 作为警告返回给用户。
        指令优先级声明见 shared/iron_rules_header.md（单一表述源）。
        （C1a 裁决 2026-08-31：Skill 可调闸（require_* 与阈值抬高）退役，
        本校验只守平台固定地板。）
    """
    text = (prompt or "").strip()
    hard: List[str] = []
    soft: List[str] = []
    if not text or kind not in ("shot", "keyElement"):
        return True, hard, soft

    # 当前 Skill 归属（与 resolve_prompt_language 同源的 usedSkills 末位兖底）：
    # 类别级语言豁免与音色声明轴都从声明读取，不硬编码探测
    _cur_skill = ""
    try:
        _cur_skill = registry.fallback_skill_from_state(
            raw_state if isinstance(raw_state, dict) else None)
    except Exception:
        pass
    # 语言单一事实源接入用户选择（规格输出语言 > Skill 声明）；
    # 英文/中英双语关闭语言闸，中文选择恢复平台地板
    cjk_min_ratio = _CJK_MIN_RATIO
    _lang = resolve_prompt_language(raw_state)
    if _lang in ("英文", "中英双语"):
        cjk_min_ratio = 0.0
    # 类别级语言闸豁免（任务#8 ①）：Skill 声明 language.prompt_en_categories
    # 含当前类别时，仅该类别放宽为英文；其余类别维持中文地板
    # （豁免只按声明类别生效，防泛化）
    try:
        if (
            _cur_skill
            and kind in registry.skill_prompt_en_categories(_cur_skill)
        ):
            cjk_min_ratio = 0.0
    except Exception:
        pass  # 声明读取失败回落现状判定（不误拦）

    # 语言闸（shot / keyElement 通用）：中文输入环境下正文应以中文书写，
    # 仅专业技术术语可保留英文（平台固定地板）
    total_chars = len(_WS_RE.sub("", text))
    cjk_chars = len(_CJK_RE.findall(text))
    if total_chars and cjk_chars / total_chars < cjk_min_ratio:
        hard.append(
            f"{LANG_EN_HARD_PREFIX}：请改为中文正文（主体描述/动作表演/场景环境/"
            "镜头语言叙述用中文，仅专业风格/光影/构图/渲染技术术语可保留英文原词）后重新写入"
        )

    if kind == "shot":
        if len(text) < _SHOT_PROMPT_MIN_CHARS:
            hard.append(
                f"分镜视频提示词过短（{len(text)} 字），请补全画面主体/镜头语言/"
                "声音层等必要描述后重新写入"
            )
        # 软提醒：有对白且存在音色参考——音色在场优先跟随 Skill 声明轴
        # （requires_inputs.features 含 voice_reference，任务#8 ④）；
        # 未声明者回落状态探测（零预设，不回潮硬编码唯探测）
        _voice_declared = False
        try:
            _voice_declared = bool(
                _cur_skill
                and registry.skill_declares_feature(_cur_skill, "voice_reference")
            )
        except Exception:
            pass
        if (
            raw_state is not None
            and _DIALOGUE_RE.search(text)
            and (_voice_declared or has_voice_reference(raw_state))
            and "音色参考" not in text
        ):
            soft.append(
                "该镜头含对白且项目已有音色参考音频，建议在提示词中写明哪个角色使用哪个音色参考，"
                "并在草稿 refAssets/timbre 中绑定对应音频，以保证跨镜头声音一致"
            )
    else:  # keyElement
        if len(text) < _ELEMENT_PROMPT_MIN_CHARS:
            hard.append(
                f"关键元素提示词过短（{len(text)} 字），请补全主体身份/特征细节/"
                "氛围基调等必要描述后重新写入"
            )

    ok = not hard
    return ok, hard, soft


def format_gate_errors(errors: List[str]) -> str:
    """把校验意见格式化为随回复展示的拦截文案（本次写入已被拒绝）"""
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "提示词结构校验未通过，本次写入已被闸机拦截：\n"
        f"{lines}\n"
        "请按上述原因逐条修正后重新写入（生成质量与流程纪律由系统强制；"
        "如确需坚持当前写法，请明确告知用户并说明理由）。"
    )


def storyboard_is_empty(raw_state: Dict[str, Any]) -> bool:
    """故事板是否完全为空（无任何分组）：用于判定「首次搭建」批次"""
    return not any(
        raw_state.get(cat)
        for cat in ALL_CATEGORIES
    )


def present_structure_kinds(raw_state: Dict[str, Any]) -> List[str]:
    """故事板现存的分组类别（审阅卡文案用）。"""
    kinds: List[str] = []
    if raw_state.get(CAT_KEY_ELEMENTS):
        kinds.append("keyElement")
    if raw_state.get(CAT_SHOTS):
        kinds.append("shot")
    if raw_state.get(CAT_AUDIO_ITEMS):
        kinds.append("audio")
    return kinds


def storyboard_stage_complete(raw_state: Dict[str, Any], skill_name: str = "") -> bool:
    """ 故事板阶段完成（暂停点归位 Skill 阶段边界）：关键元素+分镜均非空；
    音频仅当 Skill 声明音频拆解（available_tools 含 storyboard_audio）才要求。"""
    if not (raw_state.get(CAT_KEY_ELEMENTS) or []) or not (raw_state.get(CAT_SHOTS) or []):
        return False
    need_audio = False
    try:
        from src.video_agent.skill_runtime.registry import resolve_entry
        entry = resolve_entry(skill_name) if skill_name else None
        need_audio = bool(
            entry and "storyboard_audio" in (getattr(entry, "available_tools", None) or [])
        )
    except Exception:
        need_audio = False
    return bool(raw_state.get(CAT_AUDIO_ITEMS) or []) if need_audio else True


def flow_auto_continue(raw_state: Dict[str, Any]) -> bool:
    """ 一条龙指令（模型解读用户意图后发出；仅本条消息生效，任务开始即清）。"""
    return bool((raw_state.get("interaction") or {}).get("auto_continue"))


def clear_flow_directive(raw_state: Dict[str, Any]) -> bool:
    """任务开始清除上一任务残留的一条龙标记（按消息生效语义）；返回是否清除。"""
    inter = raw_state.get("interaction")
    if inter and inter.get("auto_continue"):
        inter["auto_continue"] = False
        return True
    return False


def storyboard_pending(raw_state: Dict[str, Any]) -> bool:
    """故事板结构是否正处于「等待用户确认」窗口（仅供提示，不再拦截写入）"""
    interaction = raw_state.get("interaction") or {}
    return bool(interaction.get("storyboard_pending"))


def drafts_confirmed(raw_state: Dict[str, Any], drafts: List[Dict[str, Any]]) -> bool:
    """目标草稿是否全部已经用户确认（tag == 已确认）。空列表返回 False。

    确认状态的完整闭环：提示词写入时 tag 重置为 Agent（重写即作废），
    用户回应暂停时晋升为已确认，或模型按用户明确指示调 confirm_draft 落点。
    """
    if not drafts:
        return False
    return all(str(d.get("tag") or "").strip() == "已确认" for d in drafts)


# ---------- 阶段探测驱动的工具裁剪（混合形态第一层：工具可见性边界） ----------

# 故事板结构工具集（无规格文档阶段不下发；三个拆解
# 执行器与提示词编写执行器同入名单——越阶入口正是它们，
# 可见性软层；C1b 裁决 2026-08-31 阶段前置硬闸退役）
STORYBOARD_STAGE_TOOLS = frozenset({
    "storyboard_create_group", "storyboard_patch_draft", "storyboard_add_draft",
    "storyboard_delete_group", "storyboard_confirm_draft", "storyboard_media_to_chat",
    "read_draft",
    "storyboard_key_elements", "storyboard_shots", "storyboard_audio",
    "write_media_prompt",
})
# 草稿生成工具集（故事板结构就绪前不下发）。image_generate 不入裁剪集：
# 其单张应急轨（mode='single'）任意阶段可见（应急出图覆盖空项目场景）；
# 批量轨由 gen_confirm/tool_risk 闸在执行时按 mode 兜底拦截。
GENERATION_STAGE_TOOLS = frozenset({"generate_video"})


def stage_tool_restrictions(raw_state: Dict[str, Any]) -> tuple:
    """按制作阶段的客观状态计算本轮应裁剪的工具集与说明文案。

    返回 (excluded: frozenset, note: str)。检测信号全部客观可查：
    - 无规格文档 → 故事板结构工具 + 生成工具都不下发（先写规格）；
    - 有规格但故事板为空 → 生成工具不下发（先建结构）；
    - 生成工具裁剪不含 image_generate（其单张应急轨任意阶段可见）；
    - 其他阶段 → 不追加裁剪。
    裁剪只是第一层（软）：文本动作轨不受影响，由既有闸机做第二层兜底。
    """
    if not has_spec_document(raw_state):
        from src.video_agent.skill_runtime.registry import spec_wizard_active

        if spec_wizard_active(_current_skill_of(raw_state)):
            return (
                STORYBOARD_STAGE_TOOLS | GENERATION_STAGE_TOOLS,
                "【当前阶段工具边界】成片规格尚未定稿：故事板与视频生成工具暂未开放。"
                "image_generate 仅可用单张应急出图（mode='single'），批量轨需待结构就位。"
                "规格文档将由系统按向导选定自动拼装，请等待用户完成参数选定与规格审阅。",
            )
        return (
            STORYBOARD_STAGE_TOOLS | GENERATION_STAGE_TOOLS,
            "【当前阶段工具边界】成片规格尚未定稿：故事板与视频生成工具暂未开放。"
            "image_generate 仅可用单张应急出图（mode='single'），批量轨需待结构就位。"
            "请先用 document_write 写入 制片规格.md（暂停点以当前 Skill『何时暂停』为准），"
            "规格就位后系统会自动开放后续工具。",
        )
    has_groups = any(
        raw_state.get(cat)
        for cat in ALL_CATEGORIES
    )
    if not has_groups:
        return (
            GENERATION_STAGE_TOOLS,
            "【当前阶段工具边界】故事板结构尚未建立：视频生成工具暂未开放。"
            "image_generate 仅可用单张应急出图（mode='single'），批量轨需待结构就位。"
            "请先搭建关键元素/分镜/音频分组，结构就位后系统会自动开放生成工具。",
        )
    return frozenset(), ""


# 闸机文案/卡片族实现体迁 gates_cards.py，re-export 保持既有引用路径
#（宪法 §12 登记壳；壳到期制登记：长期保留·架构承重——round_end_policies/
# agent_loop/chat_consume 等经 prompt_gates.* 引用，迁移需全量改引用）
from src.video_agent.core.gates_cards import (
    _GATE_MSG_FILE,
    _gate_msg,
    _gate_json,
    STRUCTURE_INLINE_PROMPT_MAX,
    _STORYBOARD_STRUCTURE_PAUSED,
    STORYBOARD_STRUCTURE_PAUSED_MSG,
    STORYBOARD_STRUCTURE_OPTIONS,
    _SHOT_STRUCTURE_PAUSED,
    SHOT_STRUCTURE_PAUSED_MSG,
    SHOT_STRUCTURE_OPTIONS,
    _STRUCTURE_KIND_ALIAS,
    normalize_structure_kind,
    structure_paused_confirmation,
    SPEC_DOC_OPTIONS,
    spec_review_options,
    SPEC_COLLECT_PAUSED_MSG,
    SPEC_COLLECT_PAUSED_MSG_NO_SUMMARY,
    SPEC_COLLECT_KIND,
    SPEC_DOC_PAUSED_MSG,
    _SUMMARY_QUOTE_CHARS,
    _norm_summary_text,
    summary_already_visible,
    _SPEC_PARAM_LINES,
    _SPEC_IMG_SEL_RE,
    _SPEC_VID_SEL_RE,
    _SPEC_DUR_SEL_RE,
    _SPEC_CONFIRM_INTENT_RE,
    parse_hard_selections,
    _SPEC_WRITE_ENUM_RE,
    _SPEC_WRITE_VERB_RE,
    _SPEC_SUGGESTED_RE,
    DRAFTS_REVIEW_MSG,
    DRAFTS_REVIEW_OPTIONS,
    drafts_review_card,
    GENERATION_CONFIRM_GATE_ERROR,
    GENERATION_CONFIRM_GATE_BLOCKED,
    TOOL_RISK_BLOCKED_MSG,
    current_flow_step,
    system_continue_option,
    is_flow_continue_value,
    flow_continue_note,
)

# 规格向导家族实现体在 gates_spec.py，此处 re-export 保持既有引用不变
from src.video_agent.core.gates_spec import (
    _CHANNEL_GROUP_IMAGE,
    _CHANNEL_GROUP_VIDEO,
    _DIM_DESCRIPTION_OVERRIDES,
    _HARD_PARAM_DIM_HINTS,
    _PLACEHOLDER_DIM_VALUE,
    _channel_groups,
    _clean_dim_token,
    _consume_spec_collected,
    _current_skill_of,
    _dedupe,
    _is_hard_param_dim,
    _spec_dim_unresolved,
    _spec_doc_content,
    apply_spec_param_selections,
    assemble_spec_doc,
    build_spec_param_options,
    merge_spec_param_wizard,
    parse_dim_selections,
    skill_spec_dimensions,
    spec_collect_card,
    spec_doc_finalized,
    spec_pause_card,
    spec_unconfirmed_params,
    state_has_spec_doc,
)

# 剧本原料闸家族实现体在 gates_script.py，此处 re-export 保持既有引用不变
# （宪法 §12 登记壳；壳到期制登记：长期保留·架构承重，消费方含 planner/registry
# 经 prompt_gates.* 属性访问，迁移需全量改引用并同步 test patch 目标）
from src.video_agent.core.gates_script import (
    SCRIPT_MODEL_NOTE,
    SCRIPT_UPLOAD_ACK,
    script_present,
    script_remind_card,
    script_short_circuit_eligible,
    script_upload_ack_intent,
    script_waive_intent,
    text_mentions_script,
)
