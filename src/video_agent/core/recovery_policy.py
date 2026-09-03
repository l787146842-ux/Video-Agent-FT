"""失败恢复策略分派表（policy-as-data，与闸机 GATE_RULES 同一哲学）。

审核结论（失败恢复分级）：坏输出统一走 nudge 重试是脚手架时代的
单通道恢复；升级为按失败类型分派的分级策略——每种失败只有一条
明确的恢复路径，重试预算与处置动作全部来自本表，循环骨架不再
硬编码恢复语义。

失败类型 → 处置动作：
- bad_output（LLM 输出解析失败：空/畸形）→ nudge_retry：
  保留 nudge 为该分支的唯一实现（脚手架 S03 收窄后的登记身份），
  重试上限取本表 max_retries；
- tool_failure（工具执行失败）→ feedback_degrade：
  错误经 fc_feedback.compose_failure_feedback 回喂模型自处置
  （transient 由模型自主换参重试、permanent 由模型降级或上报用户），
  循环层不做机械重试——机械重试同一失败工具调用只会放大成本；
- adapter_error（供应商侧错误）→ escalate：
  transient 重试已在适配层（adapters.retry）耗尽，到达循环侧的
  要么是 permanent（鉴权/参数/拒答），都不具循环内重试价值，
  原样上抛由统一错误路径承接。

退役记录（2026-09-03 用户裁决 Q2）：
- 闸机拦截分派键→结构化上报：已退役。
  依据：文本轨退役后循环层拦截列表恒空（原 executor 上的零写入点字段
  已随兼容层根除批删除）；FC 轨闸机拦截已由 fc_gates
  reject_message 结构化回喂闭环（工具执行段内即完成上报+修正指引），
  不再需要循环层额外分派。轮末自愈策略同批退役。
  防复活见 scripts/check_legacy_orchestration.py FORBIDDEN。

新增失败类型 = 表中加一行 + 实现体登记；禁止在循环骨架内私设恢复分支。
"""
from dataclasses import dataclass
from typing import Dict, Optional

# ---------- 失败类型键 ----------
FAILURE_BAD_OUTPUT = "bad_output"
FAILURE_TOOL = "tool_failure"
FAILURE_ADAPTER = "adapter_error"
# 闸机拦截分派键已退役（2026-09-03 Q2 裁决）：FC 轨闸机拦截由 fc_gates
# reject_message 闭环，循环层无真实输入源。防复活见 check_legacy_orchestration。

# ---------- 处置动作键 ----------
ACTION_NUDGE_RETRY = "nudge_retry"              # 附格式纠正提示重试（nudge）
ACTION_FEEDBACK_DEGRADE = "feedback_degrade"    # 回喂模型自处置（降级/上报）
ACTION_ESCALATE = "escalate"                    # 原样上抛，统一错误路径承接
# 结构化上报动作键已随闸机拦截分派键同批退役（2026-09-03）


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
        action=ACTION_NUDGE_RETRY,
        max_retries=2,
        rationale=(
            "模型侧空/畸形输出属能力缺口补偿（脚手架 S03）；nudge 文案外置 "
            "prompts/planner/feedback.md::BAD_OUTPUT_NUDGE，是该分支唯一实现"
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
}


def recovery_for(kind: str) -> RecoveryPolicy:
    """按失败类型取恢复策略；未登记的类型显式 KeyError（禁止静默兜底）。"""
    return RECOVERY_POLICIES[kind]


def classify_step_failure(
    *,
    content: str = "",
    fc_applied: int = 0,
    adapter_error: Optional[BaseException] = None,
) -> str:
    """循环级失败分类器：把一步执行的观测信号归一到失败类型键。

    优先级（高→低）：供应商错误 > 空/畸形输出；
    其余带工具执行的失败信号归工具失败（回喂通道承接）。

    2026-09-03 退役：闸机拦截参数已删除（该分支退役，
    FC 轨闸机拦截由 fc_gates reject_message 闭环，循环层无真实输入源）。
    """
    if adapter_error is not None:
        return FAILURE_ADAPTER
    if not str(content or "").strip() and int(fc_applied or 0) == 0:
        return FAILURE_BAD_OUTPUT
    return FAILURE_TOOL


__all__ = [
    "FAILURE_BAD_OUTPUT",
    "FAILURE_TOOL",
    "FAILURE_ADAPTER",
    "ACTION_NUDGE_RETRY",
    "ACTION_FEEDBACK_DEGRADE",
    "ACTION_ESCALATE",
    "RecoveryPolicy",
    "RECOVERY_POLICIES",
    "recovery_for",
    "classify_step_failure",
]
