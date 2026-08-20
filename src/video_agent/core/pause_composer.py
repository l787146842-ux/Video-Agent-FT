# -*- coding: utf-8 -*-
"""暂停卡唯一发行点（三通道契约，宪法 v6 Rule2，ADR-0003）。

v1：runtime 直跑后的阶段边界卡（kind=stage_done）——
- 正文通道：成果由层 9 确定性渲染（stage_deliverables），卡不复述；
- 确认通道：一句确认问句（≤PAUSE_MSG_MAX 语义，长成果禁入卡）；
- 引导通道：选项面系统派生（sidecar 流程继续选项 + 规格向导 +
  调整类白名单），模型自造继续/规格类选项无入口。

批 2 将模型 workflow_pause / 机械兜底卡 / 轮末策略卡全汇流到此，
并下发 kind（remind/collect/stage_done/confirm）供前端按语义渲染标题。
"""
from typing import Any, Dict, List

from src.video_agent.core import gates_cards
from src.video_agent.core import gates_spec

# 暂停卡语义种类（前端标题渲染唯一依据，消灭「待补原料=阶段完成」误标）
PAUSE_KIND_REMIND = "remind"        # 待补原料/前置缺失提醒
PAUSE_KIND_COLLECT = "collect"      # 规格收集向导
PAUSE_KIND_STAGE_DONE = "stage_done"  # 阶段完成审阅
PAUSE_KIND_CONFIRM = "confirm"      # 常规模型暂停


def compose_stage_pause(
    state: Dict[str, Any], skill: str, stage_title: str,
) -> Dict[str, Any]:
    """阶段边界暂停卡（runtime 直跑后）：短问句 + 系统派生选项面。

    继续选项由 sidecar flow.steps + 客观状态机械派生（current_flow_step）；
    规格未定稿时规格向导合并进选项面（merge_spec_param_wizard），
    模型不撰写任何选项。"""
    message = f"「{stage_title}」已完成，请过目以上成果并选择下一步。"
    options: List[Dict[str, Any]] = []
    sys_opt = gates_cards.system_continue_option(state, skill)
    if sys_opt:
        options.append(sys_opt)
    final_msg, opts, _merged = gates_spec.merge_spec_param_wizard(
        state, message, options)
    return {
        "message": str(final_msg or message),
        "options": list(opts or options),
        "kind": PAUSE_KIND_STAGE_DONE,
    }


def compose_remind_card(message: str, options: List[Dict[str, Any]]) -> Dict[str, Any]:
    """提醒类卡（原料闸等）：kind=remind，前端不得渲染为「阶段完成」。"""
    return {"message": message, "options": list(options or []), "kind": PAUSE_KIND_REMIND}


def compose_collect_card(message: str, options: List[Dict[str, Any]]) -> Dict[str, Any]:
    """规格收集向导卡：kind=collect；引导词归正文通道由调用方装配。"""
    return {"message": message, "options": list(options or []), "kind": PAUSE_KIND_COLLECT}
