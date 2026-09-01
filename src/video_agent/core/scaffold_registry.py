"""脚手架注册表。

业界依据（Anthropic《Effective Harnesses for Long-Running Agents》）：harness 的每个
组件都是一条「模型做不到 X」的假设；假设会过期，模型升级即逐件拆测。

本注册表把补丁从「隐形债务」变为「登记资产」：
- classification=scaffold：对模型能力缺口的补偿，可折旧，入拆除仪式
  （见 AGENTS.md §七）；必须有可证伪的 assumption 与 retest_policy；
- classification=invariant：工程/物理约束，长期承重，季度审计但不入拆除仪式。

棘轮（scripts/check_scaffold_registry.py + test_scaffold_registry.py 钉死）：
scaffold 计数只降不升，基线 = SCAFFOLD_COUNT_BASELINE；新增脚手架必须经宪法
13.5 决策树（含 eval 证明缺口存在）并上调基线的书面裁决。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ScaffoldEntry:
    """一条脚手架/不变量登记：component 为可导入符号路径（module:attr）。"""

    sid: str
    component: str
    assumption: str
    evidence: str
    retest_policy: str
    classification: str  # "scaffold" | "invariant"


SCAFFOLDS = (
    # ---------- 脚手架（可折旧） ----------
    ScaffoldEntry(
        "S03", "src.video_agent.core.agent_loop:_bad_output_nudge",
        "模型会连续产出空/畸形输出（失败恢复分级后收窄为恢复策略分派表"
        " bad_output 分支唯一实现；工具失败/闸机拦截/供应商错误各有分级"
        "出口，不再经 nudge，见 core/recovery_policy.py）",
        "bad_output_retry trace 计数；recovery_policy 分派表回归；audit 回归",
        "每次主模型切换",
        "scaffold"),
    ScaffoldEntry(
        "S05", "src.video_agent.skill_runtime.registry:fallback_skill_from_state",
        "请求会丢失 skill 名，需回退 usedSkills 末位",
        "回归测试钉死",
        "前端请求恒带 skill_slug 被机械验证后",
        "scaffold"),
    ScaffoldEntry(
        "S06", "src.video_agent.skill_runtime.registry:match_skill_name_from_text",
        "用户会直接发 Skill 名而不挂引用块",
        "回归测试钉死",
        "前端 @/Skill 引用块覆盖全部唤起路径后",
        "scaffold"),
    ScaffoldEntry(
        "S07", "src.video_agent.core.round_end_policies:_cond_gate_heal",
        "模型被闸机拦截后会原样重试，需升级改写指引",
        "gate_heal 回归",
        "每次主模型切换",
        "scaffold"),
    ScaffoldEntry(
        "S08", "src.video_agent.core.round_end_policies:_claims_structure_done",
        "模型会虚报「已完成拆解」而状态为空",
        "回归测试钉死",
        "每次主模型切换",
        "scaffold"),
    ScaffoldEntry(
        "S09", "src.video_agent.core.planner:_SKILL_REMINDER",
        "模型读了 Skill 全文后仍会忘记暂停点",
        "回归测试钉死",
        "编排器机械暂停全覆盖后",
        "scaffold"),
    ScaffoldEntry(
        "S10", "src.video_agent.core.round_end_policies:_cond_stage_done_fallback",
        "执行器跑完但模型不自发暂停，需层 9 补发引导卡",
        "层 9 回归",
        "编排器接管暂停点后",
        "scaffold"),
    ScaffoldEntry(
        "S13", "src.video_agent.core.round_end_policies:_cond_aborted_continuation_audit",
        "模型会说「马上继续」却以 stop 收尾（audit-0819 假停取证）",
        "audit-0819-fakestop 回归",
        "每次主模型切换",
        "scaffold"),
    # ---------- 不变量（长期承重） ----------
    ScaffoldEntry(
        "I01", "src.video_agent.core.token_budget:truncate_messages",
        "上下文窗口有限是物理约束，与模型能力无关",
        "token_budget 单测",
        "季度审计",
        "invariant"),
    ScaffoldEntry(
        "I02", "src.video_agent.core.fc_feedback:compress_prior_feedback",
        "token 成本经济学，任何模型都承重（C3）",
        "fc_feedback 单测",
        "季度审计",
        "invariant"),
    ScaffoldEntry(
        "I03", "src.video_agent.adapters.retry",
        "上游网络/服务瞬时故障是物理约束",
        "retry 单测",
        "季度审计",
        "invariant"),
    ScaffoldEntry(
        "I04", "src.video_agent.core.guard_pipeline",
        "安全不变量：闸机判定机械强制；双轨一致条款随 4-4 单轨化简化",
        "动作一致性测试",
        "季度审计",
        "invariant"),
    ScaffoldEntry(
        "I05", "src.video_agent.core.prompt_builder:PromptBuilder.build_skill_catalog",
        "上下文经济学不变量：渐进式披露（目录常驻+开关过滤+正文预算注入+全文/资源按需+素材按引用描述符）",
        "prompt_builder 单测",
        "季度审计",
        "invariant"),
    ScaffoldEntry(
        "I06", "src.video_agent.core.prompt_gates:GATE_RULES",
        "安全策略即数据，属宪法不变量",
        "test_prompt_gates/test_gate_messages_coverage 回归（gate_corpus 黄金语料校准已随 C1a 裁决 2026-08-31 退役）",
        "季度审计",
        "invariant"),
    ScaffoldEntry(
        "I07", "src.video_agent.core.planner:Planner._issue_pause",
        "暂停/回应是结构化事件而非文本猜测（对标 AskUserQuestion："
        "用户选择经结构化通道回携，展示层状态从权威登记派生）",
        "test_pause_structure 回归",
        "季度审计",
        "invariant"),
    ScaffoldEntry(
        "I08", "src.video_agent.core.live_metrics:record_degradation",
        "承重接线静默降级必须可观测（断线防复发：豁免消费/暂停登记/"
        "会话压缩/事件通道/闸预检五点计数，/api/agent/degradations 暴露）",
        "test_degradation_telemetry 回归",
        "季度审计",
        "invariant"),
    ScaffoldEntry(
        "I09", "src.video_agent.core.action_executor",
        "承重壳（审核整改批 8 登记）：层级例外已清偿（D-01，2026-08-22）——执行器下沉 core，"
        "对 web 生成管线/供应商配置的依赖倒置为 core/ports.py 端口，"
        "web 层装配点注入；web 侧 re-export 壳已阶段二清退（任务#13 F-4，"
        "消费方全部改指向 core 真身）；对外行为冻结不变",
        "action_executor 相关集成测试",
        "下沉计划阶段验收",
        "invariant"),
)

# 棘轮基线（每拆除一件随降，禁止上调）：scaffold 类计数只降不升。
# 字面常量而非对 SCAFFOLDS 动态求和（动态求和是恒真基线，
# 棘轮名存实亡）。只降不升；上调须书面裁决
# 并同批修改本常量。
SCAFFOLD_COUNT_BASELINE = 8


def scaffold_entries() -> tuple:
    return tuple(e for e in SCAFFOLDS if e.classification == "scaffold")


def invariant_entries() -> tuple:
    return tuple(e for e in SCAFFOLDS if e.classification == "invariant")
