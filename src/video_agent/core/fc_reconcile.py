# -*- coding: utf-8 -*-
"""FC 批末对账段。

三段结构：闸机裁决（fc_gates）→ 执行（fc_tool_runner）→ 批末对账（本模块）。

对账只承载卡片注入类结论（阶段完成审阅卡）；客观账本（BatchLedger）
的生成成败字段另供 batch_checkpoint 取消回滚判定。C1a 裁决 2026-08-31：
防虚报客观探针（虚报覆盖改写）退役——工具执行主路径与 ToolResult 回喂保留。
规格硬边界/规格接管已随用户裁决 2026-08-31（D-08 清偿）退役：
规格交互归 Skill 散文 + 模型自主暂停。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Set

from loguru import logger

from src.video_agent.core import prompt_gates


@dataclass
class BatchLedger:
    """批内客观事实账本（执行段逐项记账）。

    全部字段可由执行结果客观判定，不含任何对模型文案的解读；
    confirmation/confirmation_options/tool_results 是执行段累积的
    待对账输出，对账结论（卡片注入类）按探针事实覆盖它们。
    """

    injected_skill: str = ""
    skill_strict: bool = False
    storyboard_empty_before: bool = False
    doc_written: bool = False
    docs_written: List[str] = field(default_factory=list)
    structure_created: bool = False
    structure_kinds: Set[str] = field(default_factory=set)
    # 生成类工具本批成败跟踪（batch_checkpoint 取消回滚判定依据）
    gen_failed_err: str = ""
    gen_succeeded: bool = False
    # 待对账输出（执行段累积，对账结论可覆盖）
    confirmation: str = ""
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)


def reconcile_batch(
    ledger: BatchLedger, state_provider: Callable[[], Dict[str, Any]],
) -> None:
    """批末对账：阶段完成审阅卡。覆盖结论直接写回 ledger（confirmation/options）。

    （规格文档硬边界与规格接管已随用户裁决 2026-08-31 退役，D-08 清偿。）"""
    _reconcile_stage_review_card(ledger, state_provider)


def _reconcile_stage_review_card(
    ledger: BatchLedger, state_provider: Callable[[], Dict[str, Any]],
) -> None:
    """暂停点归位 Skill 阶段边界：
    平台不再「关键元素首建后硬暂停」；仅当本批把故事板推进到阶段完成
    （Skill 声明的组别齐）且模型未自行暂停时，注入审阅卡；
    模型自发暂停一律保留其文案与选项（平台不覆盖）。"""
    if (
        not ledger.confirmation
        and ledger.skill_strict
        and ledger.storyboard_empty_before
        and prompt_gates.storyboard_stage_complete(state_provider(), ledger.injected_skill)
    ):
        ledger.confirmation, ledger.confirmation_options = prompt_gates.structure_paused_confirmation(
            ledger.structure_kinds or prompt_gates.present_structure_kinds(state_provider()))
        logger.info("[FlowGate] 故事板阶段完成且模型未暂停，注入审阅卡")
