"""闸机规则注册表数据层。

纯数据与归一化函数，无任何判定逻辑；顶层不依赖 core 其他模块（无环）。
消费方（guard_pipeline / planner_gate_session / routes/agent 等）直连本模块，
原 prompt_gates re-export 承重壳已随批次E收敛删除（2026-09-02）。

承载：GateRuleMeta 定义 + GATE_RULES 注册表数据 + GATE_MESSAGE_SECTIONS
闸机文案覆盖矩阵 + PAUSE_MESSAGE_SECTIONS 暂停/告警文案覆盖矩阵
+ normalize_rule_id() 归一函数。
判定逻辑（各族校验/audit_verdicts 等）仍在 prompt_gates.py。
"""
from dataclasses import dataclass
from typing import Dict, Tuple

# ---------- 闸机规则注册表（Policy-as-Data，宪法 §2.3） ----------

LAYER_PLATFORM = "platform"


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
        GateRuleMeta("platform.gen_confirm", LAYER_PLATFORM,
                     "生成确认闸：未经用户确认的 Prompt Draft 不触发生成",
                     "test_gen_confirm_gate 钉死；2026-08-21 门禁触发盘点"
                     "有真实拦截记录"),
        GateRuleMeta("platform.tool_risk", LAYER_PLATFORM,
                     "工具风险分级闸（§2.7）：生效审批档为 confirm（F1 双轴并单轴："
                     "risk 单轴推导，high 默认/未注册默认，确认只挂高危）的工具须经"
                     "用户显式同意方可执行；image_generate 批量轨由 gen_confirm 闸专属覆盖",
                     "宪法 §2.7 风险分级设立；test_tool_risk_gate 钉死"),
    )
}

# rule_id → prompts/gates/messages.md 外置文案分节（宪法 §2.3 文案外置覆盖矩阵）。
# 空元组 = 该闸无固定文案分节：拒因/警告为运行时客观数据组装
# （字数缺口/缺失字段清单等），不走 messages.md 固定分节。
# 覆盖完整性由 tests/unit/test_gate_messages_coverage.py 钉死：
# 键集与 GATE_RULES 一致，且非空分节必须存在于 messages.md。
GATE_MESSAGE_SECTIONS: Dict[str, Tuple[str, ...]] = {
    "platform.prompt_write": (),
    "platform.gen_confirm": ("GENERATION_CONFIRM", "GENERATION_CONFIRM_BLOCKED"),
    "platform.tool_risk": ("TOOL_RISK_BLOCKED",),
}

# 暂停/告警文案分节登记（非闸机规则条目，不入 GATE_RULES/GATE_MESSAGE_SECTIONS）：
# 结构暂停卡与暂停槽防御断言告警，同以 prompts/gates/messages.md 为单一事实源，
# 由 gates_cards.py 经 _gate_json/_gate_msg 按本表逻辑键加载（消费方引用本表，
# 分节键不再散落于消费点字面量）。逻辑键 → messages.md 分节 KEY。
# 覆盖完整性由 tests/unit/test_gate_messages_coverage.py 钉死：与
# GATE_MESSAGE_SECTIONS 合并后覆盖 messages.md 全部 ## KEY 分节（消除孤儿），
# 且每个逻辑键必须被 gates_cards.py 引用（登记即有消费者）。
PAUSE_MESSAGE_SECTIONS: Dict[str, str] = {
    "storyboard_structure_paused": "STORYBOARD_STRUCTURE_PAUSED",
    "shot_structure_paused": "SHOT_STRUCTURE_PAUSED",
    "pause_slot_assertion": "PAUSE_SLOT_ASSERTION",
}

def normalize_rule_id(rule_id: str) -> str:
    """rule_id 归一入口（承重符号）。

    别名表已随 skill/session 层闸机退役清空，现为恒等返回；
    消费面（guard_pipeline / override 留痕）保留统一入口，
    历史新别名需求在此单点扩展。
    """
    return str(rule_id or "")
