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


# 规则注册表：平台层为硬边界（manifest 无权关闭，仅可经用户一次性申诉放行）。
# C1a 裁决（2026-08-31）：技能级闸层整体删除——Skill 层闸键（结构可调闸/
# 流程警告闸/原料闸/资产绑定闸）全链路退役，结构校验收归 platform.prompt_write
# 固定地板；退休执行体见 C1b 机械工作流层退役批。
GATE_RULES: Dict[str, GateRuleMeta] = {
    r.rule_id: r for r in (
        GateRuleMeta("platform.prompt_write", LAYER_PLATFORM,
                     "提示词写入统一判定入口（结构闸组合签发点：字数地板+语言闸，固定不可调）",
                     "validate_prompt_write 钉死回归（test_prompt_gates）；"
                     "C1a 裁决收归平台层（原 skill.prompt_structure 退役）"),
        GateRuleMeta("platform.shot_min_chars", LAYER_PLATFORM,
                     "分镜提示词最短字数地板（防敷衍，固定不可调）",
                     "test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("platform.element_min_chars", LAYER_PLATFORM,
                     "关键元素提示词最短字数地板（防敷衍，固定不可调）",
                     "test_prompt_gates 结构闸校准钉死"),
        GateRuleMeta("platform.gen_confirm", LAYER_PLATFORM,
                     "生成确认闸：未经用户确认的 Prompt Draft 不触发生成",
                     "test_gen_confirm_gate 钉死；2026-08-21 门禁触发盘点"
                     "有真实拦截记录"),
        GateRuleMeta("platform.tool_risk", LAYER_PLATFORM,
                     "工具风险分级闸（§2.7）：审批分级生效档 approval_tier=confirm"
                     "（high 默认/未注册默认，数据驱动）的工具须经用户显式同意"
                     "方可执行；image_generate 批量轨由 gen_confirm 闸专属覆盖",
                     "宪法 §2.7 风险分级设立；test_tool_risk_gate 钉死"),
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
