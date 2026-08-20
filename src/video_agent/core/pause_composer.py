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
from typing import Any, Dict, List, Tuple

import re

from src.video_agent.core import gates_cards
from src.video_agent.core import gates_spec
from src.video_agent.core import prompt_gates
# 模块属性调用（测试 patch 目标=registry 命名空间，
# 顶层 from-import 会冻结绑定导致 patch 失效）
from src.video_agent.skill_runtime import registry as _registry

# 确认通道问句上限（三通道 B：成果展示归正文，卡只留短问句）
PAUSE_MSG_MAX = 220

# 模型自造规格组 → Skill 标准维度的模糊映射（选项面归一，
# 裸值/异名组一律由系统向导取代，模型不能增删维度）
_DIM_ALIAS = {
    "画幅": "画幅比例", "比例": "画幅比例", "画幅比例": "画幅比例",
    "风格": "影像风格基调", "影像风格": "影像风格基调",
    "时长": "目标时长", "目标时长": "目标时长",
    "语言": "输出语言", "输出语言": "输出语言",
}

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


def compress_pause_message(message: str, stage_label: str = "") -> Tuple[str, str]:
    """三通道 B 确定性变换：超 PAUSE_MSG_MAX 的模型 pause 原文进正文通道，
    确认通道压缩为系统短问句（带真实阶段标签）；不没收暂停与选项。"""
    text = str(message or "")
    if len(text) <= PAUSE_MSG_MAX:
        return text, ""
    short = f"「{stage_label or '本阶段'}」已完成，请过目以上成果并选择下一步。"
    return short, text


def _is_model_spec_group(option: Dict[str, Any], dims: List[str]) -> bool:
    """模型自造规格类选项判定（group/label 头部命中维度别名映射）。"""
    group = str(option.get("group") or "").strip()
    label = str(option.get("label") or "").strip()
    alias_hit = group in _DIM_ALIAS or any(
        label.startswith(k) for k in _DIM_ALIAS)
    if not alias_hit:
        return False
    canon = _DIM_ALIAS.get(group) or next(
        (v for k, v in _DIM_ALIAS.items() if label.startswith(k)), "")
    return bool(canon) and (not dims or canon in dims)


def normalize_option_surface(
    state: Dict[str, Any],
    skill: str,
    message: str,
    options: List[Dict[str, Any]],
    boundary_hit: bool = False,
) -> Tuple[str, List[Dict[str, Any]]]:
    """选项面单一归一（Rule2 v6：模型不撰写选项面）。

    - 规格未定稿时：模型自造规格类选项（裸值/异名组）剔除，
      系统向导（标准「键：值」）为规格交互唯一入口；
    - 阶段边界（boundary_hit）：剔除模型自造继续类选项，
      系统派生「确认，进入「X」」前置；调整类选项保留。
    """
    opts = [o for o in (options or []) if isinstance(o, dict)]
    try:
        dims: List[str] = []
        if _registry.spec_wizard_active(skill):
            dims = prompt_gates.skill_spec_dimensions(skill)
            if dims and not gates_spec.spec_doc_finalized(state):
                opts = [o for o in opts if not _is_model_spec_group(o, dims)]
            _m, opts, _merged = gates_spec.merge_spec_param_wizard(
                state, message, opts)
    except Exception:
        pass
    if boundary_hit and skill:
        sys_opt = gates_cards.system_continue_option(state, skill)
        if sys_opt:
            _cont_re = re.compile(r"(继续|推进|进入|开始)")
            opts = [
                o for o in opts
                if not (
                    _cont_re.search(str(o.get("label") or ""))
                    and str(o.get("value") or "") not in ("继续", "补拆")
                )
            ]
            opts.insert(0, sys_opt)
    return message, opts
