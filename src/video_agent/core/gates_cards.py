"""闸机文案/卡片族。

闸机文案外置加载（_gate_msg/_gate_json，prompts/gates/messages.md 单一事实源）
+ 全部用户可见文案常量与卡片组装（规格闸/结构暂停卡/规格审阅选项/草稿审阅卡/
生成确认闸/镜头顺序闸）。prompt_gates 尾部 re-export 保持既有引用路径不变
（宪法 §12 登记壳）。
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.video_agent.core.gate_registry import PAUSE_MESSAGE_SECTIONS
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS
from src.video_agent.utils.prompts import load_prompt_section

# ---------- 闸机文案外置（宪法 §2.3） ----------
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


# 结构搭建阶段内联提示词的容忍上限（字符）：
# 当前策略下不再剥离内联提示词，详细内容随建卡一并写入
STRUCTURE_INLINE_PROMPT_MAX = 40

# 单一活跃暂停槽位防御断言告警文案（批 B 外置；运维侧可观测告警，
# 非闸机规则条目，登记于 gate_registry.PAUSE_MESSAGE_SECTIONS 暂停/告警文案矩阵）
PAUSE_SLOT_ASSERTION_NOTE = _gate_msg(PAUSE_MESSAGE_SECTIONS["pause_slot_assertion"], (
    "单一活跃暂停槽位冲突：已有未消费的暂停卡时再次发行 workflow_pause，"
    "旧卡作废 + trace 留痕（pause_slot_collision）+ 发行新卡 + 继续等待人工确认，不拒收。"
))

_STORYBOARD_STRUCTURE_PAUSED = _gate_json(
    PAUSE_MESSAGE_SECTIONS["storyboard_structure_paused"], {
    "message": (
        "关键元素拆分已建立，请审阅左侧故事板的元素拆分结果（数量/命名/描述）；"
        "确认无误后按当前 Skill 流程推进下一阶段。"
    ),
    "options": [
        {
            "label": "确认，按当前 Skill 流程推进下一阶段",
            "description": "拆分无误，下一步以当前 Skill 流程为准",
        },
        {"label": "调整关键元素拆分", "description": "告诉我需要增删改的元素"},
    ],
})
STORYBOARD_STRUCTURE_PAUSED_MSG = str(_STORYBOARD_STRUCTURE_PAUSED.get("message", ""))

STORYBOARD_STRUCTURE_OPTIONS = list(_STORYBOARD_STRUCTURE_PAUSED.get("options") or [])

# 分镜拆解完成后的暂停文案（结构 → 提示词 分界）：
# 结构阶段只建骨架、不写详细提示词，确认卡片必须引导用户审阅拆分方案，
# 而不是声称提示词已写好或直接引导生成（拆完分镜即引导「确认草案，开始生成视频」）；
# 下一步文案不写死具体阶段（不同 Skill 的下一步不同，以各自流程为准）
_SHOT_STRUCTURE_PAUSED = _gate_json(
    PAUSE_MESSAGE_SECTIONS["shot_structure_paused"], {
    "message": (
        "分镜拆解已完成，请在左侧故事板审阅分镜拆分方案（镜头数量/时间轴/镜头语言）；"
        "确认无误后按当前 Skill 流程推进下一阶段。"
    ),
    "options": [
        {
            "label": "确认，按当前 Skill 流程推进下一阶段",
            "description": "拆分无误，下一步以当前 Skill 流程为准",
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
    下一步不写死具体阶段，以当前 Skill 流程为准。"""
    norm = {normalize_structure_kind(k) for k in (kinds or set())}
    if "shot" in norm:
        return SHOT_STRUCTURE_PAUSED_MSG, list(SHOT_STRUCTURE_OPTIONS)
    return STORYBOARD_STRUCTURE_PAUSED_MSG, list(STORYBOARD_STRUCTURE_OPTIONS)

# 规格文档相关卡片/文案族（SPEC_DOC_OPTIONS/spec_review_options/
# SPEC_COLLECT_*/SPEC_DOC_PAUSED_MSG）已随用户裁决 2026-08-31 退役删除（D-08 清偿）：
# 规格交互归 Skill 散文 + 模型自主暂停。

# ---------- 一句话总结展示去重（正文出现两遍总结） ----------
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


# ---------- 规格制作参数硬选择解析（parse_hard_selections/_SPEC_*_SEL_RE 等）----------
# 已随用户裁决 2026-08-31 退役删除（D-08 清偿）：规格参数收集归模型自主对话。


# 提示词草案写入后 Skill 要求暂停审阅，模型该停没停时
# 层 9 兜底注入（与结构暂停卡同构同口径：message+options 外置
# messages.md::DRAFTS_REVIEW_PAUSED，登记 PAUSE_MESSAGE_SECTIONS）
_DRAFTS_REVIEW_PAUSED = _gate_json(
    PAUSE_MESSAGE_SECTIONS["drafts_review_paused"], {
    "message": (
        "提示词草案已写入，请在左侧故事板审阅草案内容；"
        "确认后我将按全局设置中的生成渠道触发生成。"
    ),
    "options": [
        # 中性化：平台不点名下一步（生成/生图排序归 Skill）
        {
            "label": "确认提示词草案，按当前 Skill 流程推进",
            "description": "将目标草稿标记为已确认，按当前 Skill 流程推进",
        },
        {"label": "先调整提示词", "description": "告诉我需要修改的草稿与修改意见"},
    ],
})
DRAFTS_REVIEW_MSG = str(_DRAFTS_REVIEW_PAUSED.get("message", ""))

DRAFTS_REVIEW_OPTIONS = list(_DRAFTS_REVIEW_PAUSED.get("options") or [])


def drafts_review_card() -> Tuple[str, List[Dict[str, str]]]:
    """提示词草案审阅暂停卡（层 9 兜底）。"""
    return DRAFTS_REVIEW_MSG, list(DRAFTS_REVIEW_OPTIONS)


GENERATION_CONFIRM_GATE_ERROR = _gate_msg("GENERATION_CONFIRM", (
    "流程警告：目标草稿的 Prompt Draft 尚未经用户审阅确认（tag 非「已确认」）。"
    "本次生成已按用户要求照常触发，请同时在回复中提示用户审阅草稿。"
))

# 模型自发跳确认（本轮用户消息无跳过指令）→ 拒收而非放行。
# 「只警告不拦人」保护的是用户意志；模型违反 Skill 暂停语义不属用户意志。
GENERATION_CONFIRM_GATE_BLOCKED = _gate_msg("GENERATION_CONFIRM_BLOCKED", (
    "流程拦截：目标草稿的 Prompt Draft 尚未经用户审阅确认。请先展示草案并调用"
    "暂停工具请求用户审阅；用户接受暂停卡后重提生成即视为已确认，不会重复拦截。"
    "也可在工作台把目标草稿标「已确认」后再生成。"
))

# 高风险工具确认闸拒因（宪法 §2.7）：消费端 = guard_pipeline.evaluate_tool_risk，
# {{name}} 占位由代码侧 replace 还原；内置兜底与外置分节等值，
# 防外置文案缺失时静默回落两套说辞。
TOOL_RISK_BLOCKED_MSG = _gate_msg("TOOL_RISK_BLOCKED", (
    "高风险工具确认闸拦截：'{{name}}' 为 high 级操作（宪法 §2.7），"
    "未经用户显式同意不得执行。请先用 workflow_pause 向用户说明本次将执行的"
    "操作并请求确认；用户接受暂停卡后重提即视为已确认（本轮内不再拦截）。"
    "也可在工作台确认相关草稿，或由用户点「本次放行」。"
))

# other_high 动作类拒因（批 12 告示牌同源）：暂停卡自动确认仅覆盖
# costly 生成 ∪ 规格文档写入（guard_pipeline.CONSENT_CHARTER 唯一声明），
# 其余 high 的同意路径只有「本次放行」——拒因必须如实指引，不开空头支票
#（1000 事故：通用拒因对非 costly 高危承诺「接受后重提即放行」，闸机不认）。
TOOL_RISK_BLOCKED_OTHER_MSG = _gate_msg("TOOL_RISK_BLOCKED_OTHER", (
    "高风险工具确认闸拦截：'{{name}}' 为 high 级操作（宪法 §2.7），"
    "未经用户显式同意不得执行。这类操作不在暂停卡自动确认范围内"
    "（自动确认仅覆盖生成类与制片规格写入）；如确需执行，请在回复中说明目的，"
    "请用户在工作台点「本次放行」后再重新提交。"
))

# ---------- 下一步机械派生（frontmatter 声明唯一源） ----------
#
# 确认 UI 由系统从即将执行的动作渲染，模型不撰写确认界面；
# 暂停点与下一步是 Skill 工作流声明的属性，下一步 label 机械派生。
# 阶段短名由 frontmatter flow.step_short_titles 声明。
# flow.steps 抄本废除（正文 planner 是唯一流程源），真实数据不再
# 声明 steps，本通道自然退化；消费代码保留兼容内存 manifest（测试同构）。


def _flow_steps_of(skill_name: str) -> Dict[int, str]:
    """frontmatter flow.steps 活读（步骤号→标题）；未声明返回空。"""
    from src.video_agent.skill_runtime.registry import skill_manifest_of

    manifest = skill_manifest_of(str(skill_name or "").strip())
    raw = (((manifest or {}).get("flow") or {}).get("steps")) or {}
    out: Dict[int, str] = {}
    for k, v in raw.items():
        if str(k).isdigit():
            out[int(k)] = str(v or "")
    return out


# step_done_conditions 声明探针注入口：单一实现在 stage_probes
# （本模块被 prompt_gates 导入，反向顶层 import 成环，故注册钩子解耦）。
# 签名：(step_no, state, skill) -> Optional[bool]，None = 未声明回落旧规则。
_STEP_DONE_PROBE: Optional[Callable[[Any, Dict[str, Any], str], Optional[bool]]] = None


def register_step_done_probe(
    fn: Callable[[Any, Dict[str, Any], str], Optional[bool]],
) -> None:
    global _STEP_DONE_PROBE
    _STEP_DONE_PROBE = fn


def current_flow_step(state: Dict[str, Any], skill_name: str) -> int:
    """客观状态推导已完成步数（声明优先：step_done_conditions 已声明的步
    走其阶段客观探针；未声明步回落 v1 硬规则，覆盖 step1-3）。

    step1=分析存档；step2=规格文档存在；step3=故事板阶段完成。
    从 1 起连续判定，首个未完成步即断（依赖序由声明保证）。
    """
    from src.video_agent.core import prompt_gates

    steps = _flow_steps_of(skill_name)
    if not steps:
        return 0
    done = 0
    for n in sorted(steps):
        declared = (
            _STEP_DONE_PROBE(n, state or {}, str(skill_name or ""))
            if _STEP_DONE_PROBE is not None else None
        )
        if declared is not None:
            ok = declared
        elif n == 1:
            ok = bool(((state or {}).get("analysis") or {}).get("summary"))
        elif n == 2:
            ok = prompt_gates.has_spec_document(state or {})
        elif n == 3:
            ok = prompt_gates.storyboard_stage_complete(
                state or {}, str(skill_name or ""))
        else:
            break  # v1 判定边界：step4+ 回落模型选项
        if not ok:
            break
        done = n
    return done


def _flow_short_of(skill_name: str) -> Dict[int, str]:
    """frontmatter flow.step_short_titles 活读（步骤号→短标题）；
    阶段短名按 Skill 声明。"""
    from src.video_agent.skill_runtime.registry import skill_manifest_of

    manifest = skill_manifest_of(str(skill_name or "").strip())
    raw = (((manifest or {}).get("flow") or {}).get("step_short_titles")) or {}
    return {int(k): str(v or "") for k, v in raw.items() if str(k).isdigit()}


def _flow_step_title(steps: Dict[int, str], n: int,
                     short_titles: Optional[Dict[int, str]] = None) -> str:
    """步骤短标题：frontmatter 声明短名优先，回落长标题前 12 字。"""
    title = (short_titles or {}).get(n)
    if title:
        return title
    long_title = str(steps.get(n) or "").strip()
    return long_title[:12] if long_title else ""


def system_continue_option(
    state: Dict[str, Any], skill_name: str,
) -> Optional[Dict[str, str]]:
    """阶段边界系统派生「继续」选项；无 flow 声明/无后继步返回 None。

    value 与 label 同值（人类可读）：前端向导多组拼装发送时把 value 拼进
    用户消息，裸 token（如 flow_continue）会泄进用户气泡——值必须可读，
    后端机械识别走 is_flow_continue_value 行格式判定。
    """
    steps = _flow_steps_of(skill_name)
    if not steps:
        return None
    next_no = current_flow_step(state, skill_name) + 1
    if next_no not in steps:
        return None
    title = _flow_step_title(steps, next_no, _flow_short_of(skill_name))
    if not title:
        return None
    label = f"确认，进入「{title}」"
    return {
        "label": label,
        "description": f"确认当前阶段产出，下一步执行「{title}」",
        "value": label,
        "group": "下一步",
    }


# 系统派生继续选项的行格式（单一事实源：派生与识别同式，防两套说辞）
_FLOW_CONTINUE_LINE_RE = re.compile(r"^确认，进入「[^」]+」$")


def is_flow_continue_value(value: str) -> bool:
    """判定用户点选回应是否命中系统派生继续选项。

    向导多组拼装发送时 pause_response.value 为逐行拼接文本，逐行判定；
    单组直发时 value 即 label，同样命中。
    """
    lines = [ln.strip() for ln in str(value or "").splitlines() if ln.strip()]
    return any(_FLOW_CONTINUE_LINE_RE.match(ln) for ln in lines)


def flow_continue_note(state: Dict[str, Any], skill_name: str) -> str:
    """用户点选系统派生继续选项后回喂模型的机械指令（后续轮次不再猜下一步）。"""
    steps = _flow_steps_of(skill_name)
    if not steps:
        return ""
    next_no = current_flow_step(state, skill_name) + 1
    title = _flow_step_title(steps, next_no, _flow_short_of(skill_name))
    if not title:
        return ""
    return f"用户已确认进入阶段 {next_no}「{title}」，直接执行该阶段；"
