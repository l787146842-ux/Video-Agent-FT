"""
提示词结构闸机（Prompt Gate）— 写入即校验的硬保障 + 策略分层引擎（批次2）。

指令约束（system prompt / Skill 注入）是「贴告示」，遵循是概率性的；
本模块是「装闸机」：提示词写入草稿时按客观可查的结构规则校验，
不合格直接打回（工具返回错误），模型在下一轮自行补全重写（自愈闭环），
对齐外来工作流平台「结构化工具强制参数」的执行力度。

策略分层（地板模型，对齐 policy-as-data + deny-overrides 范式）：
- 平台层 platform.*：硬编码安全闸（生成确认/阶段硬边界/防虚报等，
  不在本模块评估），manifest 无权关闭；
- Skill 层 skill.*：内容结构规则，由选中 Skill 的 manifest 合成
  （可关/可放宽/可加严；字数阈值只可抬高不可低于平台地板）；
- 会话层：用户「本次放行」一次性豁免（调用方传入 overrides）。

设计原则：
- 只查客观标记（字符级可判定），不做主观质量评判，避免误伤合法提示词；
- 全部复用现有字段（prompt / refAssets / timbre），不引入新字段体系；
- 仅在 Skill 流程激活时启用（由调用方按 injected_skill / gate_enabled 决定），
  日常微调、mock 流程不受影响；
- 模式：strict = 硬拒绝（默认）/ warn = 照存但带回警告 / off = 关闭。
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state.models import (
    ALL_CATEGORIES,
    CAT_AUDIO_ITEMS,
    CAT_KEY_ELEMENTS,
)
from src.video_agent.utils.prompts import load_prompt_section

# 镜头语言客观标记（提示词里出现任一即视为含摄像机层）。
# 批次7 精化：删除单字「推/拉」（「推测」「拉长」等会误命中），
# 保留复合词与英文术语
_CAMERA_MARKERS = (
    "镜头", "景别", "特写", "全景", "中景", "近景", "远景", "俯瞰", "仰角", "跟拍",
    "推镜", "拉镜", "推入", "推出", "拉远", "拉近", "缓推", "横移", "环绕", "手持",
    "摇镜", "摇摄", "甩镜",
    "shot", "camera", "close-up", "wide", "medium", "pan", "orbit",
    "tracking", "push-in", "pull-back", "crane", "angle",
)

# 音频层关键词（批次7 精化：包装符改为成对检测，见 _has_audio_layer）
_AUDIO_KEYWORDS = ("no music", "no背景音乐", "音效", "旁白", "bgm", "ost")

# 硬性下限（字符数）：低于即打回。取保守值只拦「明显敷衍」，
# 不与 Skill 的质量要求（≥200 字）混同——质量由指令约束兜底，闸机只管结构。
# 这两个值同时是平台地板：manifest 只可抬高最短字数要求，不可低于此值。
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

# 批次7 精化：音效包装符改成对检测（单个裸 `<` 不再视为音频层，防误判）
_SFX_PAIR_RE = re.compile(r"<[^<>\n]{1,}>")


def _has_audio_layer(text: str, lower: str) -> bool:
    """音频层客观检测（批次7）：{…} 对白包装符 / <…> 成对音效包装符 / 关键词之一"""
    if _DIALOGUE_RE.search(text):
        return True
    if _SFX_PAIR_RE.search(text):
        return True
    return any(k in text or k in lower for k in _AUDIO_KEYWORDS)

# @元素引用标记（require_at_ref 加严规则用）
_AT_REF_RE = re.compile(r"@\S+")

# ---------- 策略分层引擎（批次2：policy-as-data + deny-overrides） ----------

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
# Skill 层为内容结构规则（manifest 可关/放宽/加严）。
GATE_RULES: Dict[str, GateRuleMeta] = {
    r.rule_id: r for r in (
        # --- 平台层（本模块评估部分；其余平台闸如生成确认/阶段硬边界在执行器层） ---
        GateRuleMeta("platform.shot_min_chars", LAYER_PLATFORM,
                     "分镜提示词最短字数地板（防敷衍，不可被 Skill 降低）"),
        GateRuleMeta("platform.element_min_chars", LAYER_PLATFORM,
                     "关键元素提示词最短字数地板（防敷衍，不可被 Skill 降低）"),
        # --- Skill 层 ---
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
                     "规格文档前置闸：未写 Final_Video_Spec.md 不得搭建故事板结构"),
    )
}

# manifest 允许触碰的键（skill 层）；不在表内的键一律静默忽略，
# 尤其 platform.* 相关键（地板模型强制不变量：只能加强或持平，不能削弱）
_MANIFEST_GATE_KEYS = {
    "require_duration", "require_subtitle", "require_camera_language",
    "require_audio_layer", "cjk_min_ratio", "require_at_ref",
    "shot_min_chars", "element_min_chars",
}
_MANIFEST_FLOW_KEYS = {"spec_gate", "spec_wizard"}
_MANIFEST_PAUSE_KEYS = {"stage_pause"}


@dataclass
class GatePolicy:
    """生效闸机策略 = 平台规则(固定) ⊕ Skill 规则(manifest 合成) ⊖ 会话豁免(调用方传入)。

    默认值取现行全局规则，无 manifest 的 Skill 行为与历史逐字节一致。"""
    skill_name: str = ""
    require_duration: bool = True
    require_subtitle: bool = True
    require_camera_language: bool = True
    require_audio_layer: bool = True
    cjk_min_ratio: float = 0.15
    shot_min_chars: int = _SHOT_PROMPT_MIN_CHARS
    element_min_chars: int = _ELEMENT_PROMPT_MIN_CHARS
    require_at_ref: bool = False
    spec_gate: bool = True
    # 声明性字段（仅解析登记，无运行时行为）
    spec_wizard: bool = False
    stage_pause: bool = False

    def rule_enabled(self, rule_id: str) -> bool:
        """规则是否在当前策略下启用（spec_gate 属流程闸，同样可查）"""
        key = rule_id.split(".", 1)[1]
        if key == "flow.spec_gate":
            return self.spec_gate
        return bool(getattr(self, key, False)) if isinstance(getattr(self, key, False), bool) else True

    def describe_rule(self, rule_id: str) -> str:
        meta = GATE_RULES.get(rule_id)
        return meta.description if meta else rule_id

    def to_dict(self) -> Dict[str, Any]:
        """调试/前端策略概览用"""
        return {
            "skill_name": self.skill_name,
            "rules": {
                rid: self.rule_enabled(rid)
                for rid in GATE_RULES if rid.startswith("skill.")
            },
            "shot_min_chars": self.shot_min_chars,
            "element_min_chars": self.element_min_chars,
            "cjk_min_ratio": self.cjk_min_ratio,
        }


DEFAULT_POLICY = GatePolicy()


def compose_policy(manifest: Optional[Dict[str, Any]], skill_name: str = "") -> GatePolicy:
    """从 Skill manifest 合成生效策略（deny-overrides：平台层不可触碰）。

    - manifest 试图触碰平台层/未知键 → 静默忽略 + warning 日志；
    - 字数类阈值低于平台地板 → 夹取到地板；
    - cjk_min_ratio=0 → 关闭中文占比检查（如宣言式概念短片）；
    - require_at_ref=true → 加严（如未来科幻真人电影）。
    """
    pol = GatePolicy(skill_name=skill_name)
    if not isinstance(manifest, dict) or not manifest:
        return pol
    gates = manifest.get("gates")
    if isinstance(gates, dict):
        for key, val in gates.items():
            if key not in _MANIFEST_GATE_KEYS:
                logger.warning(f"[GatePolicy] manifest 键 {key!r} 不在 skill 层可配置范围，已忽略"
                               f"（平台硬边界不可削弱；Skill「{skill_name}」）")
                continue
            if key in ("shot_min_chars", "element_min_chars"):
                try:
                    iv = int(val)
                except (TypeError, ValueError):
                    continue
                floor = _SHOT_PROMPT_MIN_CHARS if key == "shot_min_chars" else _ELEMENT_PROMPT_MIN_CHARS
                if iv < floor:
                    logger.warning(f"[GatePolicy] manifest {key}={iv} 低于平台地板 {floor}，已夹取（Skill「{skill_name}」）")
                    iv = floor
                setattr(pol, key, iv)
            elif key == "cjk_min_ratio":
                try:
                    pol.cjk_min_ratio = max(0.0, float(val))
                except (TypeError, ValueError):
                    pass
            else:
                setattr(pol, key, bool(val))
    flow = manifest.get("flow")
    if isinstance(flow, dict):
        for key, val in flow.items():
            if key not in _MANIFEST_FLOW_KEYS:
                logger.warning(f"[GatePolicy] manifest flow 键 {key!r} 不可配置，已忽略（Skill「{skill_name}」）")
                continue
            setattr(pol, key if key != "spec_gate" else "spec_gate", bool(val))
    pause = manifest.get("pause")
    if isinstance(pause, dict):
        for key, val in pause.items():
            if key not in _MANIFEST_PAUSE_KEYS:
                logger.warning(f"[GatePolicy] manifest pause 键 {key!r} 不可配置，已忽略（Skill「{skill_name}」）")
                continue
            setattr(pol, key, bool(val))
    return pol


@dataclass
class GateVerdict:
    """单条闸机判定（结构化，双轨共用，前端可见化/审计的数据源）"""
    rule_id: str
    layer: str
    ok: bool
    message: str = ""
    appealed: bool = False   # 被用户一次性申诉放行

    def to_dict(self) -> Dict[str, Any]:
        meta = GATE_RULES.get(self.rule_id)
        return {
            "rule_id": self.rule_id,
            "layer": self.layer,
            "description": meta.description if meta else "",
            "ok": self.ok,
            "message": self.message,
            "appealed": self.appealed,
            # skill 层规则可申诉；平台层同样可放行（用户显式意志）但每次单独点、单次生效
            "appealable": True,
        }

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
    policy: GatePolicy | None = None,
    overrides: List[str] | None = None,
) -> Tuple[bool, List[str], List[str]]:
    """校验一条待写入的生成提示词（兼容签名，返回 (ok, hard_errors, soft_warnings)）。

    内部委托 evaluate_prompt_write（策略引擎）；policy=None → 默认策略，
    行为与历史版本逐字节一致；overrides 为本次写入的一次性豁免 rule_id 列表。
    """
    ok, hard, soft, _verdicts = evaluate_prompt_write(
        prompt, kind, raw_state, policy=policy, overrides=overrides)
    return ok, hard, soft


def evaluate_prompt_write(
    prompt: str,
    kind: str,
    raw_state: Dict[str, Any] | None = None,
    policy: GatePolicy | None = None,
    overrides: List[str] | None = None,
) -> Tuple[bool, List[str], List[str], List[GateVerdict]]:
    """策略引擎驱动的提示词写入校验（双轨共用唯一实现，批次2）。

    Args:
        prompt: 待写入的提示词全文
        kind: 目标类别 keyElement | shot | audio（audio 不校验）
        raw_state: 当前工作台状态（音色参考软提醒用；None 时跳过软提醒）
        policy: 生效策略（None → 默认策略 = 现行全局规则）
        overrides: 用户一次性申诉放行的 rule_id 列表（会话层豁免）

    Returns:
        (ok, hard_errors, soft_warnings, verdicts)。hard_errors 文案与
        历史版本一致（回喂模型）；verdicts 为结构化判定（前端可见化/审计）。
    """
    pol = policy or DEFAULT_POLICY
    exempted = set(overrides or [])
    text = (prompt or "").strip()
    hard: List[str] = []
    soft: List[str] = []
    verdicts: List[GateVerdict] = []
    if not text or kind not in ("shot", "keyElement"):
        return True, hard, soft, verdicts

    lower = text.lower()

    def _fire(rule_id: str, message: str) -> None:
        """记录一条不合规判定；被会话层豁免时改为放行判定（留痕）"""
        if rule_id in exempted:
            verdicts.append(GateVerdict(
                rule_id=rule_id, layer=LAYER_SKILL, ok=True,
                message=message, appealed=True))
            return
        hard.append(message)
        verdicts.append(GateVerdict(
            rule_id=rule_id, layer=LAYER_SKILL, ok=False, message=message))

    # 语言闸（shot / keyElement 通用）：正文必须中文书写，仅专业技术术语可保留英文。
    # 外文 Skill 的「写成英语描述」类表述与最高优先级条款冲突时，以最高优先级为准；
    # manifest 可将 cjk_min_ratio 置 0 关闭本检查（如宣言式概念短片）。
    if pol.cjk_min_ratio > 0:
        total_chars = len(_WS_RE.sub("", text))
        cjk_chars = len(_CJK_RE.findall(text))
        if total_chars and cjk_chars / total_chars < pol.cjk_min_ratio:
            _fire("skill.cjk_min_ratio",
                  "提示词正文必须用中文书写（Skill 最高优先级条款）：主体描述/动作表演/场景环境/"
                  "镜头语言叙述都用中文，仅专业风格/光影/构图/渲染技术术语可保留英文原词；"
                  "当前提示词正文几乎全是英文，请改写为中文正文后重新写入")

    if kind == "shot":
        if len(text) < pol.shot_min_chars:
            _fire("skill.shot_min_chars",
                  f"分镜视频提示词过短（{len(text)} 字），请按 Skill「提示词写法」完整描述"
                  "（摄像机 → 主体 → 空间 → 音频），不得敷衍压缩")
        if pol.require_duration and "时长" not in text and "duration" not in lower:
            _fire("skill.require_duration",
                  "分镜视频提示词缺少镜头时长：须在提示词中写明本镜头总时长"
                  "（如「镜头总时长：15秒」，与分镜结构的时长字段一致），"
                  "生视频模型无法从其他渠道得知镜头时长")
        if pol.require_subtitle and "no subtitles" not in lower:
            _fire("skill.require_subtitle",
                  "分镜视频提示词缺少负面约束「no subtitles」（字幕在后期添加，Skill 要求必须包含）")
        if pol.require_audio_layer and not _has_audio_layer(text, lower):
            _fire("skill.require_audio_layer",
                  "分镜视频提示词缺少音频层：须含对话 {…} / 音效 <…> / 音乐 (…) 之一，"
                  "或明确写「no music」（Skill 要求几乎总是包含）")
        if pol.require_camera_language and not any(m in text or m in lower for m in _CAMERA_MARKERS):
            _fire("skill.require_camera_language",
                  "分镜视频提示词缺少镜头语言：须写明景别/角度/运动（如 缓慢推入、环绕、cut to new angle）")
        # 加严规则（manifest require_at_ref，如未来科幻真人电影）：镜头须 @ 引用关键元素
        if pol.require_at_ref and not _AT_REF_RE.search(text):
            _fire("skill.require_at_ref",
                  "分镜视频提示词缺少 @元素引用：本 Skill 要求镜头引用的关键元素用 @Element_标题 "
                  "写入（系统生成时自动把对应元素概念图作为参考图注入），请补齐后重写")
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
        if len(text) < pol.element_min_chars:
            _fire("skill.element_min_chars",
                  f"关键元素提示词过短（{len(text)} 字），请按 Skill「提示词写法」给出完整的"
                  "主体身份/特征细节/氛围基调描述")

    ok = not hard
    return ok, hard, soft, verdicts


def format_gate_errors(errors: List[str]) -> str:
    """把硬拒绝原因格式化为给模型的工具错误文案（引导其补齐重写）"""
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "提示词结构校验未通过（闸机拦截，本次写入被拒绝）：\n"
        f"{lines}\n"
        "请严格按所选 Skill 的「提示词写法」章节补齐上述缺失后，重新调用工具写入完整提示词。"
    )


# ---------- 闸机系统文案外置（批次5：prompts/gates/messages.md 为单一事实源） ----------
# 代码只留内置兜底（文件缺失/分节缺失时行为不变）；文案修改一律改外置文件。
_GATE_MSG_FILE = "gates/messages.md"


def _gate_msg(section: str, fallback: str) -> str:
    """加载闸机文案分节，缺失时回落内置兜底"""
    try:
        return load_prompt_section(_GATE_MSG_FILE, section) or fallback
    except Exception:
        return fallback


def _gate_json(section: str) -> Any:
    try:
        raw = load_prompt_section(_GATE_MSG_FILE, section)
        return json.loads(raw) if raw else None
    except Exception:
        return None


SPEC_GATE_ERROR = _gate_msg("SPEC_GATE", (
    "流程闸机拦截：最终视频规格文档尚未写入。按 Skill 流程，必须先基于用户确认的规格方案"
    "调用 document_write 写入 Final_Video_Spec.md（标题、类型、画幅、时长、视觉风格、语言、"
    "模型偏好），并暂停请用户审阅；规格文档就绪前严禁开始搭建故事板结构。"
))

# 结构搭建阶段内联提示词的容忍上限（字符）：超过即视为「详细生成提示词」，
# 属于步骤4 的产出，结构搭建（步骤3）阶段只建 title/desc/roughDesc 骨架
STRUCTURE_INLINE_PROMPT_MAX = 40

STORYBOARD_PENDING_GATE_ERROR = _gate_msg("STORYBOARD_PENDING", (
    "流程闸机拦截：故事板结构刚建立，正在等待用户审阅确认（确认/调整）。按 Skill 流程，"
    "必须在用户确认故事板后才开始编写提示词草案（步骤4）。请先暂停等待用户回应，"
    "不要在本轮继续写提示词。本次写入已被拒绝。"
))

# 结构暂停文案与选项：从 STRUCTURE_PAUSED 分节（JSON）加载；
# 结构阶段只建骨架、不写详细提示词，确认卡片必须引导用户审阅拆分方案，
# 而不是声称提示词已写好或直接引导生成（8888 事故：拆完分镜即引导「确认草案，开始生成视频」）
_STRUCTURE_PAUSED = _gate_json("STRUCTURE_PAUSED") or {}

STORYBOARD_STRUCTURE_PAUSED_MSG = (_STRUCTURE_PAUSED.get("keyElement") or {}).get("message") or (
    "关键元素拆分已建立，请审阅左侧故事板的元素拆分结果（数量/命名/描述），"
    "选择接下来的推进方式；确认后我先为各关键元素编写生图提示词草案，再继续后续拆分。"
)

STORYBOARD_STRUCTURE_OPTIONS = (_STRUCTURE_PAUSED.get("keyElement") or {}).get("options") or [
    {
        "label": "确认关键元素拆解，开始为关键元素编写提示词",
        "description": "元素拆分无误，下一步为各元素编写生图提示词草案（概念图在提示词确认后再生成）",
    },
    {"label": "调整关键元素拆分", "description": "告诉我需要增删改的元素"},
]

SHOT_STRUCTURE_PAUSED_MSG = (_STRUCTURE_PAUSED.get("shot") or {}).get("message") or (
    "分镜拆解已完成，请在左侧故事板审阅分镜拆分方案（镜头数量/时间轴/镜头语言）；"
    "详细的视频提示词草案尚未编写，确认拆分方案后我再为每个分镜编写视频生成提示词草案。"
)

SHOT_STRUCTURE_OPTIONS = (_STRUCTURE_PAUSED.get("shot") or {}).get("options") or [
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
SPEC_DOC_OPTIONS = _gate_json("SPEC_DOC_OPTIONS") or [
    {
        "label": "确认成片规格，开始拆分关键元素",
        "description": "规格内容无误，下一步按 Skill 拆分关键元素（角色/场景/道具）",
    },
    {"label": "调整成片规格", "description": "告诉我需要修改的规格条目"},
]

KEY_ELEMENT_FIRST_GATE_ERROR = _gate_msg("KEY_ELEMENT_FIRST", (
    "流程闸机拦截：首次搭建故事板必须先拆分关键元素（角色/场景/道具）。"
    "请先只创建 keyElement 分组并暂停请用户确认元素拆分；"
    "用户确认后再创建分镜（shot）与音频（audio）分组。本次分镜/音频分组创建已被拒绝。"
))


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


GENERATION_CONFIRM_GATE_ERROR = _gate_msg("GENERATION_CONFIRM", (
    "流程闸机拦截：目标草稿的 Prompt Draft 尚未经用户审阅确认（tag 非「已确认」）。"
    "按 Skill 流程：先把提示词草案展示给用户并暂停等待审阅；用户确认后再触发生成。"
    "若用户已在当前消息中明确表示确认，可先调用 storyboard_confirm_draft 将目标草稿"
    "标记为「已确认」，再重新触发生成。本次生成已被拒绝。"
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
# 批次4 C1：generate_video legacy FC 工具已移除（与确认闸脱钩），分镜视频生成
# 统一走文本轨 generate_video action（管线完整、有生成确认闸）
GENERATION_STAGE_TOOLS = frozenset({"image_generate"})


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

SHOT_SEQUENCE_GATE_ERROR = _gate_msg("SHOT_SEQUENCE", (
    "流程闸机拦截：关键元素还没有任何概念图（生成或上传），按 Skill 流程分镜提示词必须在"
    "元素图像就绪后才编制（镜头生成要参考元素图像）。请先暂停，引导用户确认生成/上传"
    "关键元素概念图；图像就绪后再回来编写分镜提示词。本次写入已被拒绝。"
))
