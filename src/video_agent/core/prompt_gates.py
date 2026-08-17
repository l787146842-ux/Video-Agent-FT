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
from src.video_agent.core.spec_rules import find_spec_doc
from src.video_agent.state.models import (
    ALL_CATEGORIES,
    CAT_AUDIO_ITEMS,
    CAT_KEY_ELEMENTS,
    CAT_SHOTS,
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

# 五轮 S3/#13：一次性放行作用域枚举——前端按钮/后端消费/trace 记录三端引用同一语义。
# 值与上方闸域常量同源（P1 单一表述源：ELEMENT_IMAGE 即 GATE_ELEMENT_IMAGE 别名），
# 此前 planner 消费逻辑「非 all 即 element_image」的隐式映射只有两处代码可懂。
GATE_OVERRIDE_SCOPE_ALL = "all"                          # 本轮闸机全部豁免（单次生效）
GATE_OVERRIDE_SCOPE_ELEMENT_IMAGE = GATE_ELEMENT_IMAGE   # 仅元素概念图前置闸豁免
GATE_OVERRIDE_SCOPE_FLOW = "flow"                        # 流程门禁豁免（用户坚持全速推进）

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


# ---------- 剧本原料闸（814H9）----------
# 五轮 S5：剧本闸家族实现体切出至 core/gates_script.py（文件瘦身）；
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
    ke_groups = (raw_state or {}).get(CAT_KEY_ELEMENTS) or []
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


_SPEC_LANG_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?输出语言(?:\*\*)?\s*[:：]\s*(.+)$")

# 0817 B17：语言闸硬拒稳定信号（exec_media_writer 据此批内即时纠正，
# 不再走「整批写完再拦 → 整工具重做」的高成本路径）
LANG_EN_HARD_PREFIX = "提示词正文几乎全是英文"


def spec_output_language(raw_state: Optional[Dict[str, Any]]) -> str:
    """0817：规格文档里用户选定的「输出语言」维度值（未选/无规格返回空串）。"""
    if not raw_state:
        return ""
    doc = find_spec_doc(raw_state)
    if doc is None:
        return ""
    m = _SPEC_LANG_LINE_RE.search(str(doc.get("content") or ""))
    return m.group(1).strip().strip("*").strip() if m else ""


def resolve_prompt_language(
    raw_state: Optional[Dict[str, Any]],
    skill_rules: Optional[Dict[str, Any]] = None,
) -> str:
    """0817 语言单一事实源裁决：用户选择（规格输出语言）> Skill 声明
    （cjk_min_ratio<=0 = 英文锁定）> 平台默认（中文）。
    注入句与语言闸读同一结果，by construction 不可能再打架（C1 延伸）。"""
    sel = spec_output_language(raw_state)
    if sel:
        has_cn = "中" in sel
        has_en = ("英" in sel) or ("双语" in sel)
        if has_cn and has_en:
            return "中英双语"
        if has_en and not has_cn:
            return "英文"
        return "中文"
    gate = skill_rules or {}
    try:
        if float(gate.get("cjk_min_ratio", _CJK_MIN_RATIO)) <= 0:
            return "英文"
    except (TypeError, ValueError):
        pass
    return "中文"


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
    # 0817：语言单一事实源接入用户选择（规格输出语言 > Skill 声明）；
    # 英文/中英双语关闭语言闸，中文选择在 Skill 英文锁定时恢复平台地板
    _lang = resolve_prompt_language(raw_state, gate)
    if _lang in ("英文", "中英双语"):
        cjk_min_ratio = 0.0
    elif cjk_min_ratio <= 0:
        cjk_min_ratio = float(_CJK_MIN_RATIO)

    # 语言闸（shot / keyElement 通用）：中文输入环境下正文应以中文书写，
    # 仅专业技术术语可保留英文。阈值可由 manifest gates.cjk_min_ratio 调整
    # （英文锁定的 Skill 声明极低阈值即等效关闭；S1：文案不再冒用 Skill 名义）
    total_chars = len(_WS_RE.sub("", text))
    cjk_chars = len(_CJK_RE.findall(text))
    if total_chars and cjk_chars / total_chars < cjk_min_ratio:
        hard.append(
            f"{LANG_EN_HARD_PREFIX}：请改为中文正文（主体描述/动作表演/场景环境/"
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


def storyboard_is_empty(raw_state: Dict[str, Any]) -> bool:
    """故事板是否完全为空（无任何分组）：用于判定「首次搭建」批次"""
    return not any(
        raw_state.get(cat)
        for cat in ALL_CATEGORIES
    )


def present_structure_kinds(raw_state: Dict[str, Any]) -> List[str]:
    """0817：故事板现存的分组类别（审阅卡文案用）。"""
    kinds: List[str] = []
    if raw_state.get(CAT_KEY_ELEMENTS):
        kinds.append("keyElement")
    if raw_state.get(CAT_SHOTS):
        kinds.append("shot")
    if raw_state.get(CAT_AUDIO_ITEMS):
        kinds.append("audio")
    return kinds


def storyboard_stage_complete(raw_state: Dict[str, Any], skill_name: str = "") -> bool:
    """0817 故事板阶段完成（暂停点归位 Skill 阶段边界）：关键元素+分镜均非空；
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
    """0817 一条龙指令（模型解读用户意图后发出；仅本条消息生效，任务开始即清）。"""
    return bool((raw_state.get("interaction") or {}).get("auto_continue"))


def clear_flow_directive(raw_state: Dict[str, Any]) -> bool:
    """0817：任务开始清除上一任务残留的一条龙标记（按消息生效语义）；返回是否清除。"""
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


# 九轮 B3b：闸机文案/卡片族实现体迁 gates_cards.py，re-export 保持既有引用路径
#（宪法 §12 登记壳；壳到期制登记：长期保留·架构承重——round_end_policies/
# agent_loop/chat_consume 等经 prompt_gates.* 引用，迁移需全量改引用）
from src.video_agent.core.gates_cards import (
    _GATE_MSG_FILE,
    _gate_msg,
    _gate_json,
    SPEC_GATE_ERROR,
    STRUCTURE_INLINE_PROMPT_MAX,
    STORYBOARD_PENDING_GATE_ERROR,
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
    SHOT_SEQUENCE_GATE_ERROR,
)

# R4b：规格向导家族实现体在 gates_spec.py，此处 re-export 保持既有引用不变
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

# 五轮 S5：剧本原料闸家族实现体在 gates_script.py，此处 re-export 保持既有引用不变
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
