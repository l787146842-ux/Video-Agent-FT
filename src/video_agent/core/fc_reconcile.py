# -*- coding: utf-8 -*-
"""FC 批末对账段。

三段结构：闸机裁决（fc_gates）→ 执行（fc_tool_runner）→ 批末对账（本模块）。

防虚报范式：对账以执行段收集的客观成败账本（BatchLedger）为第一依据
——同 workflow_runtime.sync_run 的客观探针范式（完成度只认探针，fail-closed），
批末覆盖只由「探针不一致」触发；措辞匹配（_FALLBACK_CLAIM_MARKERS）降为
兜底判别器，只判断模型暂停文案是否带生成类声称，不再独立承载任何裁决。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Set

from loguru import logger

from src.video_agent.core import prompt_gates
from src.video_agent.core import workflow_runtime
from src.video_agent.skill_runtime.registry import stage_label_for_tool
from src.video_agent.state.manager import StateManager

# 兜底判别器：仅用于判断模型暂停文案是否带生成类声称；
# 覆盖的触发权归客观账本（gen_failed_err/gen_succeeded），不归本表
_FALLBACK_CLAIM_MARKERS = (
    "已触发", "已为您触发", "开始生成", "正在生成", "生成中",
    "已生成", "已完成", "生成完毕", "出图进度",
)


@dataclass
class BatchLedger:
    """批内客观事实账本（执行段逐项记账，批末对账的唯一触发依据）。

    全部字段可由执行结果客观判定，不含任何对模型文案的解读；
    confirmation/confirmation_options/tool_results 是执行段累积的
    待对账输出，对账结论按探针事实覆盖它们。
    """

    injected_skill: str = ""
    skill_strict: bool = False
    storyboard_empty_before: bool = False
    doc_written: bool = False
    docs_written: List[str] = field(default_factory=list)
    prompt_stripped: bool = False
    prompt_gate_blocked: int = 0
    structure_created: bool = False
    structure_kinds: Set[str] = field(default_factory=set)
    # 生成类工具本批成败跟踪（防虚报：同批失败后暂停文案不得声称已触发生成）
    gen_failed_err: str = ""
    gen_succeeded: bool = False
    # 关键文档写入成败跟踪（document_write 失败仍声称完成 → 防虚报覆盖）
    key_tool_failed: List[str] = field(default_factory=list)
    key_tool_errors: Dict[str, str] = field(default_factory=dict)
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
    结构纯净事实回喂 → 生成防虚报 → 提示词拦截防虚报 → 规格接管 →
    关键步骤防虚报。覆盖结论直接写回 ledger（confirmation/options/tool_results）。
    """
    _reconcile_spec_doc_boundary(ledger, state_provider)
    _reconcile_stage_review_card(ledger, state_provider)
    _reconcile_structure_stripped(ledger)
    _reconcile_gen_false_claim(ledger)
    _reconcile_prompt_gate_blocked(ledger)
    _reconcile_spec_takeover(ledger, state_provider)
    _reconcile_key_tool_failure(ledger)


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


def _reconcile_structure_stripped(ledger: BatchLedger) -> None:
    """结构阶段剥离了内联详细提示词：回喂中显式告知，防止模型虚报「提示词已写好」。"""
    if ledger.prompt_stripped:
        ledger.tool_results.append({
            "name": "系统闸机",
            "ok": False,
            "error": (
                "结构搭建阶段只建骨架：内联草稿中的详细提示词已被剥离，当前草稿无提示词（事实）。"
                "请等用户确认故事板后，再用 storyboard_patch_draft 逐条编写提示词草案；"
                "向用户陈述需与此一致。"
            ),
        })


def _reconcile_gen_false_claim(ledger: BatchLedger) -> None:
    """生成防虚报（客观探针对账为主）：同批生成类工具失败且无成功（探针事实）
    而模型暂停文案带生成类声称（兜底措辞判别）→ 覆盖为诚实文案
    （对齐文本轨 gate_heal 的「拦截后不接受虚报」原则）。"""
    if not (ledger.gen_failed_err and not ledger.gen_succeeded and ledger.confirmation):
        return
    if not any(mk in ledger.confirmation for mk in _FALLBACK_CLAIM_MARKERS):
        return  # 文案诚实（无生成声称）→ 探针不一致不波及暂停文案
    logger.warning("[Planner] 防虚报拦截：生成工具失败但暂停文案声称已触发，已覆盖为诚实文案")
    ledger.confirmation = (
        "出图尚未执行：本次生成被系统闸机拦截（"
        f"{ledger.gen_failed_err[:80]}）。提示词草案已就绪，请在左侧故事板审阅；"
        "确认后我将按全局设置中的生成渠道触发生成。"
    )
    ledger.confirmation_options = [{
        "label": "确认提示词草案，开始生成概念图",
        "description": "将目标草稿标记为已确认并重新触发生成",
    }, {
        "label": "先调整提示词",
        "description": "告诉我需要修改的草稿与修改意见",
    }]


def _reconcile_prompt_gate_blocked(ledger: BatchLedger) -> None:
    """暂停防虚报（问题2）：本批有提示词写入被质量闸拦截（未写入卡片），
    模型却仍暂停引导用户「确认提示词」→ 覆盖为诚实文案
    （对齐生成失败防虚报闸；结构刚建立时已由结构暂停文案接管，不重复覆盖）。"""
    if not (ledger.prompt_gate_blocked and ledger.confirmation and not ledger.structure_created):
        return
    logger.warning(f"[Planner] 暂停防虚报：{ledger.prompt_gate_blocked} 条提示词写入被拦，覆盖暂停文案")
    ledger.confirmation = (
        f"部分提示词写入被系统质量闸拦截（{ledger.prompt_gate_blocked} 条未通过校验、未写入卡片），"
        "请先在左侧故事板审阅已成功写入的草案；确认后我将按 Skill 规范重写被拦截的提示词并再次请您确认。"
    )
    ledger.confirmation_options = [{
        "label": "确认已写入的草案，继续重写被拦截的提示词",
        "description": "把已审阅草案标记为已确认，并重写被闸机拦截的提示词",
    }, {
        "label": "先调整提示词",
        "description": "告诉我需要修改的草稿与修改意见",
    }]


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


def _reconcile_key_tool_failure(ledger: BatchLedger) -> None:
    """关键工具（document_write）存在失败且模型带确认声称完成 → 覆盖为诚实文案
    （关键步骤防虚报收敛到文档写入）。"""
    if not (ledger.confirmation and ledger.key_tool_failed and not ledger.spec_write_rejected):
        return
    # 失败工具名映射为用户友好名（内部英文名不出现在用户文案）
    _failed = "、".join(
        dict.fromkeys(stage_label_for_tool(n) or n for n in ledger.key_tool_failed)
    )[:160]
    logger.warning(f"[Planner] 关键步骤防虚报：{_failed} 失败但模型声称完成，已覆盖")
    ledger.confirmation = (
        f"关键步骤未全部完成：{_failed} 执行失败，工作台状态未按预期更新；"
        "请按系统提示重试，不要声称已完成。"
    )
    ledger.confirmation_options = [{
        "label": "重试",
        "description": "重新执行未完成的关键步骤",
    }]
