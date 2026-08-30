# -*- coding: utf-8 -*-
"""FC 批末对账段。

三段结构：闸机裁决（fc_gates）→ 执行（fc_tool_runner）→ 批末对账（本模块）。

对账只承载卡片注入类结论（规格硬边界暂停卡 / 阶段完成审阅卡 /
规格向导接管）；客观账本（BatchLedger）的生成成败字段另供
batch_checkpoint 取消回滚判定。C1a 裁决 2026-08-31：防虚报客观探针
（虚报覆盖改写）退役——工具执行主路径与 ToolResult 回喂保留。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Set

from loguru import logger

from src.video_agent.core import prompt_gates
from src.video_agent.core import workflow_runtime
from src.video_agent.state.manager import StateManager


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
    # 规格写入被向导拒收（拒收后必须接管为规格向导卡，模型不得跳过规格交互）
    spec_write_rejected: bool = False
    # 待对账输出（执行段累积，对账结论可覆盖）
    confirmation: str = ""
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)


def reconcile_batch(
    ledger: BatchLedger, state_provider: Callable[[], Dict[str, Any]],
) -> None:
    """批末对账（顺序敏感，勿调换）：规格文档硬边界 → 阶段完成审阅卡 →
    规格接管。覆盖结论直接写回 ledger（confirmation/options）。"""
    _reconcile_spec_doc_boundary(ledger, state_provider)
    _reconcile_stage_review_card(ledger, state_provider)
    _reconcile_spec_takeover(ledger, state_provider)


def _reconcile_spec_doc_boundary(
    ledger: BatchLedger, state_provider: Callable[[], Dict[str, Any]],
) -> None:
    """阶段硬边界：写入了规格/阶段文档但模型未自行暂停时，由系统强制暂停等审阅，
    不给它顺手把后续阶段（拆结构/写提示词）也打包做完的机会；
    写入规格文档时用专属文案（带文档卡片提示与下一步指引）。"""
    if ledger.doc_written and not ledger.confirmation:
        spec_hit = any(prompt_gates.is_spec_doc_name(n) for n in ledger.docs_written)
        if spec_hit:
            ledger.confirmation, ledger.confirmation_options = prompt_gates.spec_pause_card(
                state_provider())


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
        and not prompt_gates.flow_auto_continue(state_provider())
        and prompt_gates.storyboard_stage_complete(state_provider(), ledger.injected_skill)
    ):
        ledger.confirmation, ledger.confirmation_options = prompt_gates.structure_paused_confirmation(
            ledger.structure_kinds or prompt_gates.present_structure_kinds(state_provider()))
        logger.info("[FlowGate] 故事板阶段完成且模型未暂停，注入审阅卡")


def _reconcile_spec_takeover(
    ledger: BatchLedger, state_provider: Callable[[], Dict[str, Any]],
) -> None:
    """规格写入被向导拒收 → 系统接管为规格向导卡（与文本轨一致），
    模型不得用「请求阶段确认」跳过规格交互，也不得声称已生成规格。"""
    if not ledger.spec_write_rejected:
        return
    _spec_state = state_provider()
    inter = _spec_state.setdefault("interaction", {})
    took_over = False
    if prompt_gates.spec_doc_finalized(_spec_state):
        # 规格已定稿时模型的冗余手写只拒收警告，
        # 不接管暂停卡——拆解阶段的阶段卡正常出现，不再叫用户确认规格
        logger.info("[Planner] 规格已定稿，模型冗余规格写入仅拒收警告，不接管暂停卡")
    else:
        ledger.confirmation, ledger.confirmation_options = prompt_gates.spec_pause_card(_spec_state)
        workflow_runtime.apply_interaction(
            _spec_state, set_flags={"pending_pause_kind": "spec"})
        took_over = True
    if took_over:
        try:
            # 接管时必须同时洗掉 workflow_pause 写入的假完成文案，
            # 否则后续会把「已完成…写入项目文档」当作暂停内容回喂给模型
            workflow_runtime.apply_interaction(_spec_state, set_flags={
                "awaiting_confirmation": True,
                "confirmation_message": ledger.confirmation,
            })
            StateManager.get_instance().save()
        except Exception as _e:
            logger.warning("[Planner] 规格接管暂停态落盘失败（下轮可能重复接管）: {}", _e)
        logger.warning("[Planner] 规格写入被向导拒收，已接管为规格向导卡")
