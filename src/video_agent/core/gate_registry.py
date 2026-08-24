"""闸机规则注册表数据层（任务 23 P7-2：自 prompt_gates.py 切出）。

纯数据与归一化函数，无任何判定逻辑；顶层不依赖 core 其他模块（无环）。
prompt_gates 原位留承重壳 re-export 保持既有引用路径不变
（宪法 §12 登记壳；零行为变更，代码逐字迁移；登记见 coupling_registry R13）。

承载：GateRuleMeta 定义 + GATE_RULES 注册表数据 + RULE_ALIASES 别名表
+ normalize_rule_id() 归一函数。判定逻辑（各族校验/audit_verdicts 等）
仍在 prompt_gates.py。
"""
from dataclasses import dataclass
from typing import Dict

# ---------- 闸机规则注册表（Policy-as-Data，宪法 §2.3； 恢复） ----------

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
# Skill 层为内容结构/流程规则（manifest 可关/放宽/加严；流程闸只警告不拦人）。
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
        GateRuleMeta("platform.tool_risk", LAYER_PLATFORM,
                     "工具风险分级闸（§2.7）：high 级且无既有确认原语覆盖的工具"
                     "（画布写入/文档写入）须经用户显式同意方可执行"),
        GateRuleMeta("skill.prompt_structure", LAYER_SKILL,
                     "提示词结构总闸（guard_pipeline 合成判定）：字数/语言/时长/"
                     "字幕/音频/镜头语言结构校验的组合签发点"),
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
                     "元素概念图前置闸：元素无图时附警告（只警告不拦人）"),
        GateRuleMeta("skill.flow.storyboard_pending", LAYER_SKILL,
                     "故事板待确认窗口闸：结构未确认时附警告（只警告不拦人）"),
        GateRuleMeta("skill.gen_asset_binding", LAYER_SKILL,
                     "生成前资产绑定检查：分镜 sceneRefs 引用的关键元素"
                     "无概念图时拦截视频生成（任务#12 E-6 禁令下沉）"),
        GateRuleMeta("skill.script_required", LAYER_SKILL,
                     "剧本原料闸：需剧本 Skill 原料缺失时反复提醒上传；"
                     "执行侧拦 agent 越阶结构操作，不拦用户；豁免/坚持旁路"),
        GateRuleMeta("platform.stage_precondition", LAYER_PLATFORM,
                     "阶段前置闸（控制流统一）：工具归属阶段的前置阶段"
                     "未完成时拒收调用（frontmatter 声明依赖图为唯一事实源）；机械强制，"
                     "manifest 无权关闭，仅用户坚持可一次性豁免放行并留痕"),
    )
}

# rule_id 别名归一表（旧写法 → 注册表正式条目，单向只读映射）。
# 来源依据（P5 实测扫描，不凭空造）：data/agent_traces.jsonl* 全部轮转份与
# guard_pipeline 实际签发值均已是正式 ID；storyboard_prompt_structure 为
# 注册表时代前的下划线命名遗存（tests/e2e/studio.spec.ts mock 帧留痕），
# 归一后历史口径可并入 skill.prompt_structure。（P7-2 已随本模块切出。）
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
