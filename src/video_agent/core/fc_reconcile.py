# -*- coding: utf-8 -*-
"""FC 批末对账段。

三段结构：闸机裁决（fc_gates）→ 执行（fc_tool_runner）→ 批末对账（本模块）。

本模块现在只承载**客观账本**（BatchLedger）：执行段逐项记账的批末事实面。
卡片注入类结论已清空——阶段完成审阅卡（`_reconcile_stage_review_card`，
依赖 `prompt_gates.storyboard_stage_complete`）随 2026-11-12 宽权限批退役：
平台不在批末机械注入审阅卡，暂停卡唯一发行主体 = 模型 `workflow_pause`。
C1a 裁决 2026-08-31：防虚报客观探针（虚报覆盖改写）退役——工具执行主路径
与 ToolResult 回喂保留。规格硬边界/规格接管更早已随用户裁决 2026-08-31
（D-08 清偿）退役：规格交互归 Skill 散文 + 模型自主暂停。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Set


@dataclass
class BatchLedger:
    """批内客观事实账本（执行段逐项记账）。

    全部字段可由执行结果客观判定，不含任何对模型文案的解读；
    confirmation/confirmation_options/tool_results 是执行段累积的输出，
    当前无对账结论覆盖它们（卡片注入类结论已退役，原样上抛）。
    """

    injected_skill: str = ""
    # 以下三项是批前/批内客观快照，由执行段（fc_tool_runner）逐项写入：
    # 曾用于驱动阶段完成审阅卡，卡片退役后仍作为账本事实面保留
    #（字段消费方在 fc_tool_runner，不属本模块写范围）。
    skill_strict: bool = False
    storyboard_empty_before: bool = False
    doc_written: bool = False
    docs_written: List[str] = field(default_factory=list)
    structure_created: bool = False
    structure_kinds: Set[str] = field(default_factory=set)
    # 生成类工具本批成败跟踪（批末对账事实面；2026-09-27 批：批级回滚退役后
    # 不再供回滚判定，字段保留因其为对账客观账本的既有语义）
    gen_failed_err: str = ""
    gen_succeeded: bool = False
    # 执行段累积输出（无对账结论覆盖，原样上抛）
    confirmation: str = ""
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)


def reconcile_batch(
    ledger: BatchLedger, state_provider: Callable[[], Dict[str, Any]],
) -> None:
    """批末对账入口（保留单一调用点，当前无对账结论可注入）。

    历史结论（阶段完成审阅卡 = `_reconcile_stage_review_card`）已随
    2026-11-12 宽权限批退役：平台不再在批末机械注入审阅卡，暂停卡唯一
    发行主体 = 模型 `workflow_pause`。

    入口保留为承重点（`fc_tool_runner.execute` 尾部单一调用点、BatchLedger
    客观账本仍是批末事实面），避免消费方在无结论可注入时还要分叉判空。
    """
    _ = ledger, state_provider  # 客观账本仍在执行段累积，入口不做覆盖写
