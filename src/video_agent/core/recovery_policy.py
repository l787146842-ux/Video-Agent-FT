"""失败恢复策略分派表（policy-as-data，与闸机 GATE_RULES 同一哲学）。

审核结论（失败恢复分级）：坏输出统一走 nudge 重试是脚手架时代的
单通道恢复；升级为按失败类型分派的分级策略——每种失败只有一条
明确的恢复路径，重试预算与处置动作全部来自本表，循环骨架不再
硬编码恢复语义。

失败类型 → 处置动作：
- bad_output（空响应：无正文无工具调用）→ end_with_notice：
  收轮 + 用户可见提示 + retry 芯片，不重试。同输入重跑无信息增益
  必现同结局（4444 事故根因③；dsh/Claude Code 同语义：循环里没有
  「空响应重试」分支）；是否重试由用户经 retry 芯片决定；
- output_truncated（finish_reason=length，输出预算被思考/正文耗尽）
  → end_with_notice：撞帽以该原因收轮（dsh 同语义：绝不原样重试），
  输入侧治理见批 1（默认 256k 预算 + 400 钳制回落模型安全帽）；
- tool_failure（工具执行失败）→ feedback_degrade：
  错误经 fc_feedback.compose_failure_feedback 回喂模型自处置
  （transient 由模型自主换参重试、permanent 由模型降级或上报用户），
  循环层不做机械重试——机械重试同一失败工具调用只会放大成本；
- adapter_error（供应商侧错误）→ escalate：
  transient 重试已在适配层（adapters.retry）耗尽，到达循环侧的
  要么是 permanent（鉴权/参数/拒答），都不具循环内重试价值，
  原样上抛由统一错误路径承接；
- productive_reject（产出类调用被拒/失败的混合轮）→ feedback_degrade
  + 有界续轮预算（批 12 · 1000 事故正向修复，防打转烧满 max_steps）。

退役记录（2026-09-03 用户裁决 Q2）：
- 闸机拦截分派键→结构化上报：已退役。
  依据：文本轨退役后循环层拦截列表恒空（原 executor 上的零写入点字段
  已随兼容层根除批删除）；FC 轨闸机拦截已由 fc_gates
  reject_message 结构化回喂闭环（工具执行段内即完成上报+修正指引），
  不再需要循环层额外分派。轮末自愈策略同批退役。
  防复活见 scripts/check_legacy_orchestration.py FORBIDDEN。

退役记录（2026-09-07 五项修法批 2，用户裁决）：
- bad_output 的 nudge_retry 处置退役：_bad_output_nudge 实现体与
  prompts/planner/feedback.md::BAD_OUTPUT_NUDGE 分节随批删除；
  空响应/撞帽统一 end_with_notice 收轮（判空 = 正常收轮）。

新增失败类型 = 表中加一行 + 实现体登记；禁止在循环骨架内私设恢复分支。
"""
from dataclasses import dataclass
from typing import Dict, Optional

# ---------- 失败类型键 ----------
FAILURE_BAD_OUTPUT = "bad_output"
# finish_reason=length：输出预算被思考/正文耗尽（五项修法批 2 新增）
FAILURE_OUTPUT_TRUNCATED = "output_truncated"
FAILURE_TOOL = "tool_failure"
FAILURE_ADAPTER = "adapter_error"
# 批 12 · 1000 事故正向修复：产出类调用被拒/失败的混合轮「续轮回喂」预算键
FAILURE_PRODUCTIVE_REJECT = "productive_reject"
# 完成盖章批（dsh A2）：零工具、零变更、未盖章的纯口头收尾轮「续跑预算」键
FAILURE_UNSTAMPED_STOP = "unstamped_stop"
# 闸机拦截分派键已退役（2026-09-03 Q2 裁决）：FC 轨闸机拦截由 fc_gates
# reject_message 闭环，循环层无真实输入源。防复活见 check_legacy_orchestration。

# ---------- 处置动作键 ----------
ACTION_FEEDBACK_DEGRADE = "feedback_degrade"    # 回喂模型自处置（降级/上报）
ACTION_ESCALATE = "escalate"                    # 原样上抛，统一错误路径承接
# 收轮 + 用户可见提示（warnings/suggested retry 芯片），不重试
ACTION_END_WITH_NOTICE = "end_with_notice"
# nudge_retry 动作键已随 bad_output nudge 处置同批退役（2026-09-07 批 2）


@dataclass(frozen=True)
class RecoveryPolicy:
    """一条恢复策略登记：失败类型 → 处置动作 + 循环级重试预算。

    max_retries 仅指循环层的机械重试次数；模型收到回喂后自主发起的
    下个轮次的工具调用不算循环重试（那是模型决策，不是 harness 补偿）。
    """

    kind: str
    action: str
    max_retries: int
    rationale: str


RECOVERY_POLICIES: Dict[str, RecoveryPolicy] = {
    FAILURE_BAD_OUTPUT: RecoveryPolicy(
        kind=FAILURE_BAD_OUTPUT,
        action=ACTION_END_WITH_NOTICE,
        max_retries=0,
        rationale=(
            "空响应（无正文无工具调用）= 正常收轮（用户裁决 2026-09-07）："
            "同输入重跑无信息增益必现同结局（4444 事故根因③，dsh 同语义："
            "循环里没有空响应重试分支）；收轮附用户可见提示 + retry 芯片，"
            "是否重试由用户决定"
        ),
    ),
    FAILURE_OUTPUT_TRUNCATED: RecoveryPolicy(
        kind=FAILURE_OUTPUT_TRUNCATED,
        action=ACTION_END_WITH_NOTICE,
        max_retries=0,
        rationale=(
            "finish_reason=length：输出预算被思考/正文耗尽（4444 事故根因②）。"
            "撞帽以该原因收轮（dsh 同语义：撞帽绝不原样重试）；输入侧治理见"
            "批 1（默认 256k 预算 + 400 钳制回落模型安全帽），retry 芯片由用户触发"
        ),
    ),
    FAILURE_TOOL: RecoveryPolicy(
        kind=FAILURE_TOOL,
        action=ACTION_FEEDBACK_DEGRADE,
        max_retries=0,
        rationale=(
            "工具执行失败经 fc_feedback 结构化回喂：transient 由模型自主重试，"
            "permanent 由模型降级或上报用户；循环层机械重试无信息增益"
        ),
    ),
    FAILURE_ADAPTER: RecoveryPolicy(
        kind=FAILURE_ADAPTER,
        action=ACTION_ESCALATE,
        max_retries=0,
        rationale=(
            "供应商 transient 重试已在适配层耗尽（adapters.retry，不变量 I03），"
            "到达循环侧即 permanent——nudge 不覆盖供应商错误，原样上抛"
        ),
    ),
    FAILURE_PRODUCTIVE_REJECT: RecoveryPolicy(
        kind=FAILURE_PRODUCTIVE_REJECT,
        action=ACTION_FEEDBACK_DEGRADE,
        max_retries=2,
        rationale=(
            "批 12 · 1000 正向修复：产出类工具调用被拒/失败的混合轮不按纯文本轮"
            "提前终止（拒因必须被下一轮消费，模型自纠——发暂停卡/改参；1000 实证："
            "read_skill 成功 + 写规格被拒的混合轮口播假完成收尾）。max_retries = "
            "同轮产出类续轮预算，防「被拒-口播-续轮」打转烧满 max_steps；"
            "超限走轮末收尾 + 警告 + 继续按钮。全拒收轮续轮（批 9）不走本预算"
        ),
    ),
    FAILURE_UNSTAMPED_STOP: RecoveryPolicy(
        kind=FAILURE_UNSTAMPED_STOP,
        action=ACTION_FEEDBACK_DEGRADE,
        max_retries=1,
        rationale=(
            "完成盖章批（dsh A2 同语义）：本轮零工具调用、工作台零变更、又未"
            "登记完成章时，纯口头收尾不受理——回喂客观事实后由模型自纠（调工具 / "
            "暂停 / 盖章）。max_retries=1：同轮只续一次，不撞「回喂-口头承诺-再回喂」"
            "打转（4444 教训：无信息增益的重跑必现同结局）；超限走普通收尾 + "
            "事实性警告（未完成阶段入账 warnings，不拦人不 trap 用户）"
        ),
    ),
}


def recovery_for(kind: str) -> RecoveryPolicy:
    """按失败类型取恢复策略；未登记的类型显式 KeyError（禁止静默兜底）。"""
    return RECOVERY_POLICIES[kind]


def classify_step_failure(
    *,
    content: str = "",
    fc_applied: int = 0,
    adapter_error: Optional[BaseException] = None,
    finish_reason: str = "",
) -> str:
    """循环级失败分类器：把一步执行的观测信号归一到失败类型键。

    优先级（高→低）：供应商错误 > 空响应（按 finish_reason 分流
    截断/真空两键）；
    其余带工具执行的失败信号归工具失败（回喂通道承接）。

    finish_reason 分流（五项修法批 2）：空响应且 length = 输出预算截断
    （FAILURE_OUTPUT_TRUNCATED）；空响应且其他 = 真空响应
    （FAILURE_BAD_OUTPUT）。

    2026-09-03 退役：闸机拦截参数已删除（该分支退役，
    FC 轨闸机拦截由 fc_gates reject_message 闭环，循环层无真实输入源）。
    """
    if adapter_error is not None:
        return FAILURE_ADAPTER
    if not str(content or "").strip() and int(fc_applied or 0) == 0:
        if str(finish_reason or "").strip() == "length":
            return FAILURE_OUTPUT_TRUNCATED
        return FAILURE_BAD_OUTPUT
    return FAILURE_TOOL


__all__ = [
    "FAILURE_BAD_OUTPUT",
    "FAILURE_OUTPUT_TRUNCATED",
    "FAILURE_TOOL",
    "FAILURE_ADAPTER",
    "ACTION_FEEDBACK_DEGRADE",
    "ACTION_ESCALATE",
    "ACTION_END_WITH_NOTICE",
    "RecoveryPolicy",
    "RECOVERY_POLICIES",
    "recovery_for",
    "classify_step_failure",
]
