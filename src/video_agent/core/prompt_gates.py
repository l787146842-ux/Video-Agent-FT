"""
提示词结构校验（Prompt Gate）— 写入即校验、不合格照写并附警告。

指令约束（system prompt / Skill 注入）是「贴告示」，遵循是概率性的；
本模块做客观可查的结构校验，但按用户要求**永不拦截**：
校验未通过时写入照常生效，同时把校验意见作为警告随回复返回，
让用户在知情前提下自行决定是否采纳。用户指令永远优先于流程。

设计原则：
- 只查客观标记（字符级可判定），不做主观质量评判，避免误伤合法提示词；
- 全部复用现有字段（prompt / refAssets / timbre），不引入新字段体系；
- 仅在 Skill 流程激活时启用（由调用方按 injected_skill / gate_enabled 决定），
  日常微调、mock 流程不受影响；
- 模式：strict/warn = 照常执行 + 返回警告（默认）、off = 完全关闭。
"""
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.video_agent.config import settings
from src.video_agent.state.models import (
    ALL_CATEGORIES,
    CAT_AUDIO_ITEMS,
    CAT_KEY_ELEMENTS,
)
from src.video_agent.utils.prompts import load_prompt_section

# ---------- 闸机规则注册表（Policy-as-Data，宪法 §2.3；814R2 恢复） ----------

LAYER_PLATFORM = "platform"
LAYER_SKILL = "skill"
LAYER_SESSION = "session"


@dataclass(frozen=True)
class GateRuleMeta:
    """闸机规则元信息（注册表条目）：稳定 rule_id + 层归属 + 中文描述"""
    rule_id: str
    layer: str
    description: str


# 规则注册表：平台层为硬边界（manifest 无权关闭，仅可经用户一次性申诉放行）；
# Skill 层为内容结构/流程规则（manifest 可关/放宽/加严；流程闸只警告不拦人，4444）。
GATE_RULES: Dict[str, GateRuleMeta] = {
    r.rule_id: r for r in (
        GateRuleMeta("platform.prompt_write", LAYER_PLATFORM,
                     "提示词写入统一判定入口（结构闸 + 流程闸组合）"),
        GateRuleMeta("platform.shot_min_chars", LAYER_PLATFORM,
                     "分镜提示词最短字数地板（防敷衍，不可被 Skill 降低）"),
        GateRuleMeta("platform.element_min_chars", LAYER_PLATFORM,
                     "关键元素提示词最短字数地板（防敷衍，不可被 Skill 降低）"),
        GateRuleMeta("platform.gen_confirm", LAYER_PLATFORM,
                     "生成确认闸：未经用户确认的 Prompt Draft 不触发生成"),
        GateRuleMeta("skill.require_duration", LAYER_SKILL,
                     "分镜提示词须写明镜头总时长"),
        GateRuleMeta("skill.require_subtitle", LAYER_SKILL,
                     "分镜提示词须含负面约束 no subtitles"),
        GateRuleMeta("skill.require_camera_language", LAYER_SKILL,
                     "分镜提示词须含镜头语言（景别/角度/运动）"),
        GateRuleMeta("skill.require_audio_layer", LAYER_SKILL,
                     "分镜提示词须含音频层（对白/音效/音乐或 no music）"),
        GateRuleMeta("skill.cjk_min_ratio", LAYER_SKILL,
                     "提示词正文中文占比下限（0 = 关闭该检查）"),
        GateRuleMeta("skill.shot_min_chars", LAYER_SKILL,
                     "分镜提示词最短字数（可被 manifest 抬高，不低于平台地板）"),
        GateRuleMeta("skill.element_min_chars", LAYER_SKILL,
                     "关键元素提示词最短字数（可被 manifest 抬高，不低于平台地板）"),
        GateRuleMeta("skill.require_at_ref", LAYER_SKILL,
                     "分镜提示词须含 @元素引用（加严规则，默认关闭）"),
        GateRuleMeta("skill.flow.spec_gate", LAYER_SKILL,
                     "规格文档前置闸：未写规格时附警告（只警告不拦人）"),
        GateRuleMeta("skill.flow.element_image", LAYER_SKILL,
                     "元素概念图前置闸：元素无图时附警告（只警告不拦人，4444）"),
        GateRuleMeta("skill.flow.storyboard_pending", LAYER_SKILL,
                     "故事板待确认窗口闸：结构未确认时附警告（只警告不拦人，4444）"),
        GateRuleMeta("skill.script_required", LAYER_SKILL,
                     "剧本原料闸（814H9）：需剧本 Skill 原料缺失时反复提醒上传；"
                     "执行侧拦 agent 越阶结构操作，不拦用户；豁免/坚持旁路"),
    )
}


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

# 时长语义解析（P1-4）：数字 + 秒/s/sec/seconds（可带「时长/镜头总时长」前缀）
_DURATION_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:秒|s|sec|seconds)", re.IGNORECASE
)
# 字幕负面约束同义词（P1-4）：任一命中即视为已声明「字幕后期添加」
_SUBTITLE_NEGATIONS = (
    "no subtitles",
    "无字幕",
    "不加字幕",
    "后期加字幕",
    "字幕后期添加",
    "字幕后期",
    "subtitles added later",
    "subtitles later",
)

# Skill 可配置闸机规则（W20/S1）：文档内可选声明块，优先级 skill_manifest > gate_rules；
# 业务闸开关默认全关——引擎不预设任何 Skill 的提示词规范（S1 清偿），
# 需要这些结构检查的 Skill 在自己的 manifest gates 里声明开启
_GATE_RULES_BLOCK_RE = re.compile(
    r"```(?:json|js)?\s*gate_rules\s*\n(.*?)```", re.S | re.I
)
_DEFAULT_GATE_RULES: Dict[str, Any] = {
    "shot_min_chars": _SHOT_PROMPT_MIN_CHARS,
    "element_min_chars": _ELEMENT_PROMPT_MIN_CHARS,
    "cjk_min_ratio": _CJK_MIN_RATIO,
    "require_duration": False,
    "require_subtitle": False,
    "require_camera_language": False,
    "require_audio_layer": False,
    # @引用（888 事故）：声明开启后分镜提示词写入时系统按 sceneRefs 客观补印，
    # 不出题给模型；未声明的 Skill 一律不动（验收跟着技能声明走）
    "require_at_ref": False,
    "subtitle_synonyms": list(_SUBTITLE_NEGATIONS),
    "camera_markers": list(_CAMERA_MARKERS),
    "audio_markers": list(_AUDIO_MARKERS),
}


def parse_gate_rules(content: str) -> Dict[str, Any]:
    """从 Skill 文档解析闸机规则（声明块：skill_manifest 优先，旧 gate_rules 兼容）。

    未声明 / 格式非法 / 类型不合法时回落默认规则；只接受白名单键，
    防止用户文档意外破坏结构防护（长度/语言等基础阈值不可被关到负值）。
    """
    rules = dict(_DEFAULT_GATE_RULES)
    if not content:
        return rules
    m = _GATE_RULES_BLOCK_RE.search(content)
    if m:
        try:
            data = json.loads(m.group(1))
        except Exception:
            data = None
        if isinstance(data, dict):
            for key, default in _DEFAULT_GATE_RULES.items():
                val = data.get(key, default)
                if isinstance(default, bool):
                    if isinstance(val, (bool, int)):
                        rules[key] = bool(val)
                elif isinstance(default, int):
                    if isinstance(val, (int, float)) and val > 0:
                        rules[key] = int(val)
                elif isinstance(default, float):
                    # 允许 0：cjk_min_ratio=0 等效关闭语言闸（英文锁定 Skill，S1）
                    if isinstance(val, (int, float)) and 0 <= val <= 1:
                        rules[key] = float(val)
                elif isinstance(default, list):
                    if isinstance(val, list) and all(isinstance(x, str) for x in val):
                        rules[key] = [x for x in val if x]
    # skill_manifest gates 覆盖（manifest 是平台行为声明的唯一源，冲突键优先于旧块）
    try:
        from src.video_agent.web.skill_docs import parse_skill_manifest

        manifest = parse_skill_manifest(content)
    except Exception:
        manifest = None
    if manifest:
        for key, val in (manifest.get("gates") or {}).items():
            if key in _DEFAULT_GATE_RULES:
                rules[key] = val
    return rules

# 对话包装符：{台词}（Seedance 口头对话格式）
_DIALOGUE_RE = re.compile(r"\{[^{}\n]{2,}\}")

# 规格文档名称特征（归一化后包含即命中；Skill 步骤2 的产出物，
# 进入故事板阶段的强制前置）
_SPEC_NAME_HINTS = ("final_video_spec", "finalvideospec", "video_spec", "规格")


def gate_mode() -> str:
    """当前闸机模式：strict / warn / off"""
    return (settings.prompt_gate_mode or "strict").strip().lower()


# ---------- 用户坚持覆盖（用户第一 > 规格文档铁律 > Skill/系统默认） ----------

# 用户坚持覆盖（M1 作用域升级）：不再全局降级，按意图映射到具体闸门。
# 返回值（作用域）：""=未命中 / "element_image"=仅要求跳过元素概念图前置 /
# "all"=泛化权威表达（全部闸门降为警告）。特定意图优先于泛化表达：
# 「我坚持要跳过概念图」只放行元素图闸，结构校验闸保持严格。
GATE_STRUCTURE = "structure"            # 提示词结构闸（字数/语言/时长/字幕/音频/镜头语言）
GATE_ELEMENT_IMAGE = "element_image"    # 元素概念图前置闸
GATE_FLOW_PAUSE = "flow_pause"          # 流程暂停兜底闸（总结/规格暂停卡）：仅 scope=all 豁免，
# 「跳过概念图」等特定意图不涵盖（用户只是不想等图，不是不要交互分界）

# 特定意图：跳过元素概念图前置（只降级 GATE_ELEMENT_IMAGE）
_USER_INSIST_IMAGE_PATTERNS = tuple(
    re.compile(p) for p in (
        r"跳过(出图|元素图|概念图|前置)",
        r"不(用|要|生成)(出图|图片|概念图|元素图|图)",
        r"不(用)?等图",
        r"忽略前置",
    )
)
# 泛化权威表达（降级全部闸门）
_USER_INSIST_GENERAL_PATTERNS = tuple(
    re.compile(p) for p in (
        # 「坚持」裸词仅在非程度副词修饰时命中（「很/太/真/非常…坚持」属描述性文本）
        r"(?<![很太真非有特十])(?<!非常)(?<!特别)(?<!有点)(?<!有些)坚持",
        r"强制(跳过|执行|写入|继续|生成|放行|开启)",
        r"按我说的|按我要求|按我的要求|听我的",
        # 「绕过」需带流程类宾语或「直接绕过」（防「绕过木星」类剧情描述误触发）
        r"绕过(流程|闸机|前置|校验|检查|限制|确认|它)|直接绕过",
        r"无视(规则|流程|闸机|警告|前置|校验|限制)",
        r"直接(写|编写|填)",
    )
)


def user_insists_override(user_text: str) -> str:
    """当前用户消息是否明确坚持跳过流程前置；返回覆盖作用域（空串=未命中）。

    特定意图（跳过图）优先：只降级其提及的闸，结构校验等其余闸保持严格。
    """
    t = (user_text or "").strip().lower()
    if not t:
        return ""
    if any(p.search(t) for p in _USER_INSIST_IMAGE_PATTERNS):
        return GATE_ELEMENT_IMAGE
    if any(p.search(t) for p in _USER_INSIST_GENERAL_PATTERNS):
        return "all"
    return ""


def override_covers(scope: Any, gate: str) -> bool:
    """覆盖作用域是否涵盖指定闸（M1）。

    兼容旧布尔语义：True 等价 "all"；False/空串不涵盖任何闸。
    """
    if scope is True:
        scope = "all"
    if not scope:
        return False
    if scope == "all":
        return True
    return scope == gate


# 元素概念图前置被用户覆盖后的正文提示（必须让用户知道如何恢复默认）
ELEMENT_IMAGE_OVERRIDE_WARNING = (
    "已按你的要求跳过「元素概念图前置」，分镜提示词已直接写入，"
    "并已把该覆盖记录到「执行铁律.md」文档；"
    "如需恢复默认流程（先出元素概念图），可在文档面板修改执行铁律文档，或直接让我帮你改回来。"
)

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

    2222 二轮：规格向导客观流程检测的判据——Skill 正文提及规格文档名
    即视为其流程含规格编写环节。
    """
    n = str(text or "").lower().replace(" ", "").replace("-", "_")
    return any(h in n for h in _SPEC_NAME_HINTS)


# ---------- 剧本原料闸（814H9；宪法 13.5 确定性三问收归系统） ----------
#
# 「剧本是否已交」可从客观数据算出（uploadedDocs/analysis）、可机器一眼判定、
# 无创作空间 → 收归系统：缺失时提醒/短路/拦越阶，不再出题给模型（1111 事故）。

_SCRIPT_FEATURE_RE = re.compile(
    r"(上传剧本|剧本文件|读取并分析[^\n]{0,12}剧本|script_analyze|分析用户上传的[^\n]{0,10}文件)"
)


def text_mentions_script(text: str) -> bool:
    """Skill 正文客观特征：流程含「上传/分析剧本」环节（script_required 客观检测判据，
    与 spec_wizard_active 同模式；manifest flow.script_required 显式声明优先）。"""
    return bool(_SCRIPT_FEATURE_RE.search(str(text or "")))


def script_present(state: Dict[str, Any]) -> bool:
    """原料已交的客观判定：有上传文档，或剧本分析摘要已存在。"""
    if (state or {}).get("uploadedDocs"):
        return True
    ana = (state or {}).get("analysis") or {}
    return bool(str(ana.get("summary") or "").strip())


# 豁免意图（用户明确不要剧本/拒绝提醒）：与提醒卡选项「确认从零原创」同语义源
_SCRIPT_WAIVE_RE = re.compile(
    r"(从零|原创|无需剧本|不要剧本|不用剧本|没有剧本也|自行创作|你编|即兴|别提醒|不要提醒|直接继续|直接推进)"
)


def script_waive_intent(text: str) -> bool:
    """用户消息是否表达「无剧本豁免」意图（Context≠Consent：只认显式话术）。

    B2/F16：提醒卡选项携带 value（waive_script），点击即机械消费——意图识别
    不再依赖正则猜话术（正则仅作手工输入的兜底）。"""
    t = str(text or "").strip()
    if t == "waive_script":
        return True
    return bool(_SCRIPT_WAIVE_RE.search(t))


# 推进意图（短路触发条件之一）：用户在推进任务而非提问
_SCRIPT_PROGRESS_RE = re.compile(
    r"(上传|剧本|开始|继续|做|生成|拆解|分析|准备|好了|有|确认|执行)"
)
_SCRIPT_QUESTION_RE = re.compile(r"[？?]|什么|为什么|怎么|如何|你是谁|介绍|能不能|可以吗")


def script_short_circuit_eligible(text: str) -> bool:
    """S7 零思考直出准入：含推进意图 且 非提问 且 非长文本粘贴（>500 字视为原料在消息里）。

    提问类消息落回正常 LLM（回复末尾由层 9 附提醒），避免用催传卡答非所问（P2 用户意志优先）。
    """
    t = str(text or "")
    if len(t) > 500:
        return False
    if _SCRIPT_QUESTION_RE.search(t):
        return False
    return bool(_SCRIPT_PROGRESS_RE.search(t))


def script_remind_card() -> Tuple[str, List[Dict[str, Any]]]:
    """剧本缺失提醒卡（层 9 兜底；文案外置 messages.md §SCRIPT_REMIND_CARD）。"""
    data = _gate_json("SCRIPT_REMIND_CARD", {
        "message": "这个 Skill 的创作以剧本为原料，当前还没收到剧本文件。请先上传剧本或粘贴剧本文字。",
        "options": [
            {"label": "确认从零原创（无需剧本）", "description": "记账豁免，不再提醒", "value": "waive_script"},
            {"label": "我去上传/粘贴剧本", "description": "原料一到自动开工", "value": "upload_script"},
        ],
    })
    return str(data.get("message") or ""), list(data.get("options") or [])


SCRIPT_MODEL_NOTE = _gate_msg(
    "SCRIPT_MODEL_NOTE",
    "剧本未提供。本轮先引导用户上传或粘贴剧本，不做规格收集、拆解结构等下游操作。",
)

SCRIPT_UPLOAD_ACK = _gate_msg(
    "SCRIPT_UPLOAD_ACK",
    "好的，我等你发送剧本。原料一到立刻开始分析与设计。",
)

# 提醒卡「我去上传/粘贴剧本」选项的回执语义：秒回等待句，不再重复弹卡。
# 首锚限定：只认「点选项/明确回应去上传」的话术；「有，我现在上传剧本」这类
# 推进话术仍走提醒卡分支（剧本实际未到，须提醒）。
_SCRIPT_UPLOAD_ACK_RE = re.compile(r"^(我去上传|好的，?我去|马上去|这就去)")


def script_upload_ack_intent(text: str) -> bool:
    """用户回应了「我去上传」类话术 → 回等待回执而非再弹提醒卡。

    B2/F16：提醒卡选项 value=upload_script 点击即机械消费；正则仅作手工输入兜底。"""
    if str(text or "").strip() == "upload_script":
        return True
    return bool(_SCRIPT_UPLOAD_ACK_RE.search(str(text or "")))


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


def shot_references_missing_element_images(
    raw_state: Dict[str, Any],
    group: Optional[Dict[str, Any]] = None,
    scene_refs: Optional[List[Any]] = None,
) -> bool:
    """分镜 sceneRefs 引用了无图关键元素时返回 True（引用感知，P1-4）。

    group 优先取其 sceneRefs；新建分组场景可显式传 scene_refs。
    无 sceneRefs / 未引用任何关键元素 → False（不误伤无关分镜）。
    """
    refs: List[Any] = []
    if group is not None and isinstance(group, dict):
        refs = group.get("sceneRefs") or []
    if not refs and scene_refs is not None:
        refs = scene_refs
    if not refs:
        return False
    ke_groups = raw_state.get(CAT_KEY_ELEMENTS) or []
    for ref in refs:
        if not isinstance(ref, str):
            continue
        for ke in ke_groups:
            if not isinstance(ke, dict):
                continue
            # sceneRefs 兼容关键元素 ID（ke-xxx）与标题两种写法
            if str(ke.get("id") or "") != ref and str(ke.get("title") or "") != ref:
                continue
            drafts = ke.get("drafts") or []
            if not any(
                str(d.get("imgUrl") or "").strip()
                for d in drafts if isinstance(d, dict)
            ):
                return True
            break
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


def autofill_shot_duration(
    prompt: str,
    kind: str,
    group: Optional[Dict[str, Any]],
    rules: Optional[Dict[str, Any]] = None,
) -> str:
    """分镜提示词时长自动补全（888 事故：模型漏写时长 → 整批 12 条被结构闸拒绝
    → 纠正重试仍漏 → 零进展熔断）。

    提示词未写明镜头时长且所属分镜组的 duration 字段可用时，在末尾追加
    「镜头总时长：X」——生视频模型只认提示词正文，客观补印比拒绝重写
    更可靠；其余情况原样返回。
    """
    if kind != "shot" or not str(prompt or "").strip() or not group:
        return prompt
    gate = rules or _DEFAULT_GATE_RULES
    if not gate.get("require_duration", True):
        return prompt
    text = str(prompt)
    if _DURATION_RE.search(text.lower()):
        return text
    duration = str(group.get("duration") or "").strip()
    if not duration:
        return text
    return text.rstrip() + f"\n镜头总时长：{duration}"


def autofill_at_refs(
    prompt: str,
    kind: str,
    group: Optional[Dict[str, Any]],
    raw_state: Dict[str, Any] | None = None,
    rules: Optional[Dict[str, Any]] = None,
) -> str:
    """分镜提示词 @引用系统自动补写（888 事故：规则注入到位但模型没写，
    8 条提示词一条 @ 都没有）。

    确定性任务收归系统（三问判别法：答案能从 sceneRefs 算出来、对错机器可判）：
    分镜组引用的关键元素标题是明摆着的数据，缺失时客观补印一行，
    不指望模型自觉；未声明 require_at_ref 的 Skill 原样返回，不误伤。
    """
    if kind != "shot" or not str(prompt or "").strip() or not group:
        return prompt
    gate = rules or _DEFAULT_GATE_RULES
    if not gate.get("require_at_ref", False):
        return prompt
    refs = group.get("sceneRefs") or []
    if not refs:
        return prompt
    ke_groups = (raw_state or {}).get("keyElements") or []
    titles: List[str] = []
    for ref in refs:
        r = str(ref or "").strip()
        if not r:
            continue
        hit = next(
            (k for k in ke_groups
             if isinstance(k, dict) and (k.get("id") == r or k.get("title") == r)),
            None,
        )
        t = str((hit or {}).get("title") or r).strip()
        if t and t not in titles:
            titles.append(t)
    missing = [t for t in titles if f"@{t}" not in str(prompt)]
    if not missing:
        return prompt
    return str(prompt).rstrip() + "\n出场元素：" + "、".join(f"@{t}" for t in missing)


def validate_prompt_write(
    prompt: str,
    kind: str,
    raw_state: Dict[str, Any] | None = None,
    rules: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, List[str], List[str]]:
    """校验一条待写入的生成提示词。

    Args:
        prompt: 待写入的提示词全文
        kind: 目标类别 keyElement | shot | audio（audio 不校验）
        raw_state: 当前工作台状态（音色参考软提醒用；None 时跳过软提醒）
        rules: Skill 可配置规则（parse_gate_rules 产出；None 用默认规则）

    Returns:
        (ok, hard_errors, soft_warnings)
        ok=False 时调用方照常写入并把 hard_errors 作为警告返回给用户，
        不再拦截（用户指令优先于流程）。
    """
    text = (prompt or "").strip()
    hard: List[str] = []
    soft: List[str] = []
    if not text or kind not in ("shot", "keyElement"):
        return True, hard, soft

    lower = text.lower()
    gate = rules or _DEFAULT_GATE_RULES
    shot_min_chars = int(gate.get("shot_min_chars", _SHOT_PROMPT_MIN_CHARS))
    element_min_chars = int(gate.get("element_min_chars", _ELEMENT_PROMPT_MIN_CHARS))
    cjk_min_ratio = float(gate.get("cjk_min_ratio", _CJK_MIN_RATIO))

    # 语言闸（shot / keyElement 通用）：中文输入环境下正文应以中文书写，
    # 仅专业技术术语可保留英文。阈值可由 manifest gates.cjk_min_ratio 调整
    # （英文锁定的 Skill 声明极低阈值即等效关闭；S1：文案不再冒用 Skill 名义）
    total_chars = len(_WS_RE.sub("", text))
    cjk_chars = len(_CJK_RE.findall(text))
    if total_chars and cjk_chars / total_chars < cjk_min_ratio:
        hard.append(
            "提示词正文几乎全是英文：请改为中文正文（主体描述/动作表演/场景环境/"
            "镜头语言叙述用中文，仅专业风格/光影/构图/渲染技术术语可保留英文原词）后重新写入"
        )

    if kind == "shot":
        if len(text) < shot_min_chars:
            hard.append(
                f"分镜视频提示词过短（{len(text)} 字），请补全画面主体/镜头语言/"
                "声音层等必要描述后重新写入"
            )
        if gate.get("require_duration", False) and not _DURATION_RE.search(lower):
            hard.append(
                "分镜视频提示词缺少镜头时长：须在提示词中写明本镜头总时长"
                "（如「镜头总时长：15秒」「15s」「15 秒」，与分镜结构的时长字段一致），"
                "生视频模型无法从其他渠道得知镜头时长"
            )
        if gate.get("require_subtitle", False):
            subtitle_synonyms = gate.get("subtitle_synonyms") or _SUBTITLE_NEGATIONS
            if not any(n in lower for n in subtitle_synonyms):
                hard.append(
                    "分镜视频提示词缺少字幕负面约束（字幕在后期添加，须显式声明），"
                    "可用「no subtitles」「无字幕」「不加字幕」「后期加字幕」等任一写法"
                )
        if gate.get("require_audio_layer", False):
            audio_markers = gate.get("audio_markers") or _AUDIO_MARKERS
            if not any(m in text or m in lower for m in audio_markers):
                hard.append(
                    "分镜视频提示词缺少音频层：须含对话 {…} / 音效 <…> / 音乐 (…) 之一，"
                    "或明确写「no music」"
                )
        if gate.get("require_camera_language", False):
            camera_markers = gate.get("camera_markers") or _CAMERA_MARKERS
            if not any(m in text or m in lower for m in camera_markers):
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
        # 仅作软提醒，不再升级为拦截（调用方照常写入并附警告）
        if raw_state is not None and element_images_missing(raw_state):
            soft.append(
                "关键元素目前还没有任何概念图（生成或上传），按 Skill 流程应先暂停引导用户"
                "生成/上传元素图像，就绪后再编制分镜提示词（镜头要参考元素图像）"
            )
    else:  # keyElement
        if len(text) < element_min_chars:
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
    "shot": "shot", "shots": "shot",
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
    """规格审阅卡的下一步选项（8888 二轮）：按故事板客观状态递推，
    用户一眼知道确认后做什么；结构已越过分拆阶段时回落通用选项。"""
    raw = state or {}
    if not raw.get("keyElements"):
        return [
            {
                "label": "确认规格，开始拆解关键元素",
                "description": "规格无误，下一步提取剧本中的角色/场景/关键道具",
            },
            {"label": "我还要修改规格", "description": "告诉我需要修改的规格条目"},
        ]
    if not raw.get("shots"):
        return [
            {
                "label": "确认规格，开始拆解分镜",
                "description": "规格无误，下一步基于关键元素拆分镜头列表",
            },
            {"label": "我还要修改规格", "description": "告诉我需要修改的规格条目"},
        ]
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

# 硬参数维度黑名单（6666 二轮：出图/出视频渠道、分辨率、分镜最大时长
# 由顶部「全局设置」唯一提供，规格向导与规格文档均不再承载；总时长等
# 创作性「时长」维度不在黑名单内）
_HARD_PARAM_DIM_HINTS = (
    "分辨率", "分镜最大时长", "单镜头最大时长", "单镜头时长",
    "出图", "出视频", "图像生成", "视频生成", "模型偏好", "渠道",
)
_PLACEHOLDER_DIM_VALUE = "（待定）"

# 平台层维度说明补注已停用（814G4：说明文字改为逐项差异化白话，
# 维度含义由页头/问题行承载；保留空表防外部引用报错）
_DIM_DESCRIPTION_OVERRIDES: Dict[str, str] = {}


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
    for dim in skill_spec_dimensions(_current_skill_of(state)):
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
    dims = skill_spec_dimensions(_current_skill_of(state))
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
        "系统将拼装规格并开始拆分关键元素。"
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
    写入之前；只渲染 Skill 声明的软维度）。总结内嵌表述（8888 二轮）。"""
    summary = str(((state or {}).get("analysis") or {}).get("summary") or "").strip()
    msg = SPEC_COLLECT_PAUSED_MSG.format(summary=summary or "（见剧本分析要点）")
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


# ---------- 规格文档系统拼装（4444 方案乙：模型不手写规格） ----------

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
    for dim in skill_spec_dimensions(skill_name):
        v = str(selections.get(dim) or model_filled.get(dim) or "").strip()
        if v:
            lines.append(f"- {dim}：{v}")
    return "\n".join(lines) + "\n"

# 4444（C3/P4）：提示词草案写入后 Skill 要求暂停审阅，模型该停没停时
# 层 9 兜底注入（与规格审阅卡同构；10.7「Skill 暂停点 + 层 9 兜底缺一不可」）
DRAFTS_REVIEW_MSG = (
    "提示词草案已写入，请在左侧故事板审阅草案内容；"
    "确认后我将按规格文档设定的供应商触发生成。"
)
DRAFTS_REVIEW_OPTIONS = [
    {"label": "确认提示词草案，开始生成概念图",
     "description": "将目标草稿标记为已确认并触发生成"},
    {"label": "先调整提示词", "description": "告诉我需要修改的草稿与修改意见"},
]


def drafts_review_card() -> Tuple[str, List[Dict[str, str]]]:
    """提示词草案审阅暂停卡（层 9 兜底，4444）。"""
    return DRAFTS_REVIEW_MSG, list(DRAFTS_REVIEW_OPTIONS)


KEY_ELEMENT_FIRST_GATE_ERROR = _gate_msg("KEY_ELEMENT_FIRST", (
    "流程警告：首次搭建故事板通常应先拆分关键元素（角色/场景/道具）并请用户审阅，"
    "再创建分镜与音频；本次分镜/音频已按用户要求照常创建，请同时提示用户审阅拆分完整性。"
))


def storyboard_is_empty(raw_state: Dict[str, Any]) -> bool:
    """故事板是否完全为空（无任何分组）：用于判定「首次搭建」批次"""
    return not any(
        raw_state.get(cat)
        for cat in ALL_CATEGORIES
    )


def storyboard_pending(raw_state: Dict[str, Any]) -> bool:
    """故事板结构是否正处于「等待用户确认」窗口（仅供提示，不再拦截写入）"""
    interaction = raw_state.get("interaction") or {}
    return bool(interaction.get("storyboard_pending"))


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
        from src.video_agent.skill_runtime.registry import spec_wizard_active

        if spec_wizard_active(_current_skill_of(raw_state)):
            return (
                STORYBOARD_STAGE_TOOLS | GENERATION_STAGE_TOOLS,
                "【当前阶段工具边界】成片规格尚未定稿：故事板与生成类工具暂未开放。"
                "规格文档将由系统按向导选定自动拼装，请等待用户完成参数选定与规格审阅。",
            )
        return (
            STORYBOARD_STAGE_TOOLS | GENERATION_STAGE_TOOLS,
            "【当前阶段工具边界】成片规格尚未定稿：故事板与生成类工具暂未开放。"
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
            "【当前阶段工具边界】故事板结构尚未建立：生成类工具暂未开放。"
            "请先搭建关键元素/分镜/音频分组，结构就位后系统会自动开放生成工具。",
        )
    return frozenset(), ""

SHOT_SEQUENCE_GATE_ERROR = _gate_msg("SHOT_SEQUENCE", (
    "流程警告：关键元素还没有任何概念图（生成或上传）。按 Skill 流程建议先让元素概念图就绪"
    "再编制分镜提示词（镜头可参考元素图像）；本次分镜提示词已按用户要求照常写入，"
    "若后续生成视频需要参考图，请先补足元素图像。"
))
