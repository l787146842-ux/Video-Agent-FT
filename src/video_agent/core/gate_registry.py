"""闸机规则注册表数据层。

纯数据与归一化函数，无任何判定逻辑；顶层不依赖 core 其他模块（无环）。
prompt_gates 原位留承重壳 re-export 保持既有引用路径不变
（宪法 §12 登记壳；登记见 coupling_registry R13）。

承载：GateRuleMeta 定义 + GATE_RULES 注册表数据 + GATE_MESSAGE_SECTIONS
文案覆盖矩阵 + RULE_ALIASES 别名表 + normalize_rule_id() 归一函数。
判定逻辑（各族校验/audit_verdicts 等）仍在 prompt_gates.py。
"""
from dataclasses import dataclass
from typing import Dict, Tuple

# ---------- 闸机规则注册表（Policy-as-Data，宪法 §2.3） ----------

LAYER_PLATFORM = "platform"
LAYER_SKILL = "skill"
LAYER_SESSION = "session"


@dataclass(frozen=True)
class GateRuleMeta:
    """闸机规则元信息（注册表条目）：稳定 rule_id + 层归属 + 中文描述
    + origin 入册溯源（触发入册的案例/用例简述；找不到依据的写
    「历史存量-待裁决」。任务 #12 批次2 门禁溯源补录，2026-08-26 冻结基线）。"""
    rule_id: str
    layer: str
    description: str
    origin: str


# 规则注册表：平台层为硬边界（manifest 无权关闭，仅可经用户一次性申诉放行）；
# Skill 层为内容结构/流程规则（manifest 可关/放宽/加严；流程闸只警告不拦人）。
GATE_RULES: Dict[str, GateRuleMeta] = {
    r.rule_id: r for r in (
        GateRuleMeta("platform.prompt_write", LAYER_PLATFORM,
                     "提示词写入统一判定入口（结构闸 + 流程闸组合）",
                     "validate_prompt_write 钉死回归（test_prompt_gates/"
                     "test_skill_v3_consumption）+ gate_corpus 黄金语料校准"),
        GateRuleMeta("platform.shot_min_chars", LAYER_PLATFORM,
                     "分镜提示词最短字数地板（防敷衍，不可被 Skill 降低）",
                     "gate_corpus 黄金语料 + test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("platform.element_min_chars", LAYER_PLATFORM,
                     "关键元素提示词最短字数地板（防敷衍，不可被 Skill 降低）",
                     "gate_corpus 黄金语料 + test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("platform.gen_confirm", LAYER_PLATFORM,
                     "生成确认闸：未经用户确认的 Prompt Draft 不触发生成",
                     "test_gen_confirm_gate 钉死；2026-08-21 门禁触发盘点"
                     "有真实拦截记录"),
        GateRuleMeta("platform.tool_risk", LAYER_PLATFORM,
                     "工具风险分级闸（§2.7）：审批分级生效档 approval_tier=confirm"
                     "（high 默认/未注册默认，数据驱动）的工具须经用户显式同意"
                     "方可执行；image_generate 批量轨由 gen_confirm 闸专属覆盖",
                     "宪法 §2.7 风险分级设立；test_tool_risk_gate 钉死"),
        GateRuleMeta("skill.prompt_structure", LAYER_SKILL,
                     "提示词结构总闸（guard_pipeline 合成判定）：字数/语言/时长/"
                     "字幕/音频/镜头语言结构校验的组合签发点",
                     "test_gate_pipeline_wiring 钉死；2026-08-21 门禁触发盘点"
                     "有真实拦截记录"),
        GateRuleMeta("skill.require_duration", LAYER_SKILL,
                     "分镜提示词须写明镜头总时长",
                     "gate_corpus 黄金语料 + test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("skill.require_subtitle", LAYER_SKILL,
                     "分镜提示词须含负面约束 no subtitles",
                     "gate_corpus 黄金语料 + test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("skill.require_camera_language", LAYER_SKILL,
                     "分镜提示词须含镜头语言（景别/角度/运动）",
                     "gate_corpus 黄金语料 + test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("skill.require_audio_layer", LAYER_SKILL,
                     "分镜提示词须含音频层（对白/音效/音乐或 no music）",
                     "gate_corpus 黄金语料 + test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("skill.cjk_min_ratio", LAYER_SKILL,
                     "提示词正文中文占比下限（0 = 关闭该检查）",
                     "test_skill_v3_consumption 语言闸口径钉死（manifest 放宽用例）"),
        GateRuleMeta("skill.shot_min_chars", LAYER_SKILL,
                     "分镜提示词最短字数（可被 manifest 抬高，不低于平台地板）",
                     "gate_corpus 黄金语料 + test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("skill.element_min_chars", LAYER_SKILL,
                     "关键元素提示词最短字数（可被 manifest 抬高，不低于平台地板）",
                     "gate_corpus 黄金语料 + test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("skill.flow.spec_gate", LAYER_SKILL,
                     "规格文档前置闸：未写规格时附警告（只警告不拦人）",
                     "add_spec_gate.py 入册（scripts/archive）；"
                     "2026-08-21 门禁触发盘点有判定记录"),
        GateRuleMeta("skill.flow.storyboard_pending", LAYER_SKILL,
                     "故事板待确认窗口闸：结构未确认时附警告（只警告不拦人）",
                     "GOVERNANCE §13.4 症状归位表暂停语义（只警告不拦人）"),
        GateRuleMeta("skill.gen_asset_binding", LAYER_SKILL,
                     "生成前资产绑定检查：分镜 sceneRefs 引用的关键元素"
                     "无概念图时拦截视频生成（任务#12 E-6 禁令下沉）",
                     "任务#12 E-6 禁令下沉（背景跳画/道具变形）；"
                     "test_gen_asset_binding_gate 钉死"),
        GateRuleMeta("skill.script_required", LAYER_SKILL,
                     "剧本原料闸：需剧本 Skill 原料缺失时反复提醒上传；"
                     "执行侧拦 agent 越阶结构操作，不拦用户；豁免/坚持旁路",
                     "Skill 原料声明（剧本生视频需上传剧本等，frontmatter "
                     "requires_inputs）；gates_script 家族承接"),
        GateRuleMeta("platform.stage_precondition", LAYER_PLATFORM,
                     "阶段前置闸（控制流统一）：工具归属阶段的前置阶段"
                     "未完成时拒收调用（frontmatter 声明依赖图为唯一事实源）；机械强制，"
                     "manifest 无权关闭，仅用户坚持可一次性豁免放行并留痕",
                     "audit-0819e 越阶案例（GOVERNANCE §13.4 症状归位表）；"
                     "test_stage_precondition_gate 阶段 1 钉死"),
    )
}

# rule_id → prompts/gates/messages.md 外置文案分节（宪法 §2.3 文案外置覆盖矩阵）。
# 空元组 = 该闸无固定文案分节：拒因/警告为运行时客观数据组装
# （字数缺口/缺失字段清单等），不走 messages.md 固定分节。
# 覆盖完整性由 tests/unit/test_gate_messages_coverage.py 钉死：
# 键集与 GATE_RULES 一致，且非空分节必须存在于 messages.md。
GATE_MESSAGE_SECTIONS: Dict[str, Tuple[str, ...]] = {
    "platform.prompt_write": (),
    "platform.shot_min_chars": (),
    "platform.element_min_chars": (),
    "platform.gen_confirm": ("GENERATION_CONFIRM", "GENERATION_CONFIRM_BLOCKED"),
    "platform.tool_risk": ("TOOL_RISK_BLOCKED",),
    "platform.stage_precondition": (),
    "skill.prompt_structure": (),
    "skill.require_duration": (),
    "skill.require_subtitle": (),
    "skill.require_camera_language": (),
    "skill.require_audio_layer": (),
    "skill.cjk_min_ratio": (),
    "skill.shot_min_chars": (),
    "skill.element_min_chars": (),
    "skill.flow.spec_gate": ("SPEC_GATE",),
    "skill.flow.storyboard_pending": ("STORYBOARD_PENDING",),
    "skill.gen_asset_binding": ("GEN_ASSET_BINDING_BLOCKED",),
    "skill.script_required": ("SCRIPT_REMIND_CARD", "SCRIPT_MODEL_NOTE",
                              "SCRIPT_UPLOAD_ACK"),
}

# rule_id 别名归一表（旧写法 → 注册表正式条目，单向只读映射），
# 归一后历史口径可并入 skill.prompt_structure。
RULE_ALIASES: Dict[str, str] = {
    "storyboard_prompt_structure": "skill.prompt_structure",
}


def normalize_rule_id(rule_id: str) -> str:
    """把历史 rule_id 单向归一到注册表正式条目（未命中别名表原样返回）。

    三个消费面统一入口：guard_pipeline 发 verdict、audit_gate_triggers
    统计、audit_verdicts/override 留痕。历史 trace 原始值不改写，
    归一只发生在读取/统计侧。
    """
    return RULE_ALIASES.get(str(rule_id or ""), str(rule_id or ""))
