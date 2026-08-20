# -*- coding: utf-8 -*-
"""暂停卡唯一发行点（三通道契约，宪法 v6 Rule2，ADR-0003）。

v2（重构计划批4）：暂停卡 = 节点 decision_schema 的无状态渲染——
- 模型 workflow_pause 只提交「节点需要审批」事实，卡问句系统组装，
  模型原文进正文通道（无阈值补丁：通道分离是契约不是压缩）；
- 选项面：阶段边界 = 系统派生唯一入口（模型选项直接拒收，不做模糊清洗）；
  规格未定稿 = 系统向导唯一入口（维度模糊映射退役）；
- kind（remind/collect/stage_done/confirm）供前端按语义渲染标题。
"""
from typing import Any, Dict, List, Tuple

from src.video_agent.core import gates_cards
from src.video_agent.core import gates_spec
from src.video_agent.core import prompt_gates
# 模块属性调用（测试 patch 目标=registry 命名空间，
# 顶层 from-import 会冻结绑定导致 patch 失效）
from src.video_agent.skill_runtime import registry as _registry

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


def split_pause_channels(model_message: str, stage_label: str = "") -> Tuple[str, str]:
    """v2 批4：FC workflow_pause 两通道确定性分离（无阈值补丁）。

    确认通道 = 系统组装问句（带真实阶段标签）；模型原文一律进
    正文通道（空原文返回空串）。暂停与选项不被没收。"""
    short = f"「{stage_label or '本阶段'}」已完成，请过目以上成果并选择下一步。"
    return short, str(model_message or "")


def normalize_option_surface(
    state: Dict[str, Any],
    skill: str,
    message: str,
    options: List[Dict[str, Any]],
    boundary_hit: bool = False,
) -> Tuple[str, List[Dict[str, Any]]]:
    """选项面单一归一（v2 批4：模型不撰写工作流选项，非法直接拒收）。

    - 规格未定稿：规格交互唯一入口 = 系统向导（模型选项直接拒收，
      维度模糊映射退役）；
    - 阶段边界：选项面 = 系统派生继续项 + 向导组（模型选项拒收）；
    - 其余：模型选项原样保留（普通确认语义）。
    """
    opts = [o for o in (options or []) if isinstance(o, dict)]
    spec_open = False
    try:
        if skill and _registry.spec_wizard_active(skill):
            dims = prompt_gates.skill_spec_dimensions(skill)
            if dims and not gates_spec.spec_doc_finalized(state):
                spec_open = True
                opts = []  # 模型选项直接拒收（向导为唯一入口）
            _m, opts, _merged = gates_spec.merge_spec_param_wizard(
                state, message, opts)
    except Exception:
        pass
    if boundary_hit and skill:
        sys_opt = gates_cards.system_continue_option(state, skill)
        opts = ([sys_opt] if sys_opt else []) + (opts if spec_open else [])
    return message, opts
