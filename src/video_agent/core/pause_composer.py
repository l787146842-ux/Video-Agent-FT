# -*- coding: utf-8 -*-
"""暂停卡通道/选项面处理。

暂停卡唯一发行主体 = 模型的 workflow_pause 工具调用（对齐
AskUserQuestion 范式）；本模块只做通道分离，不发行卡片：
- 模型 workflow_pause 只提交「需要审批」事实，卡问句系统组装，
  模型原文进正文通道（通道分离是契约不是压缩）；
- 选项面：模型选项原样保留；
- kind（stage_done/confirm）供前端按语义渲染标题。
（remind/collect 卡已随原料闸/规格向导退役删除，用户裁决 2026-08-31。
  阶段边界系统派生「继续」选项已随阶段规则去代码化批退役——平台不再
  判阶段完成，无边界可派生，2026-09-10。）
"""
from typing import Any, Dict, List, Tuple

# 暂停卡语义种类（前端标题渲染唯一依据，消灭「待补原料=阶段完成」误标）
PAUSE_KIND_STAGE_DONE = "stage_done"  # 阶段完成审阅
PAUSE_KIND_CONFIRM = "confirm"      # 常规模型暂停


def split_pause_channels(model_message: str, stage_label: str = "") -> Tuple[str, str]:
    """FC workflow_pause 两通道确定性分离（无阈值补丁）。

    确认通道 = 系统组装问句（带真实阶段标签）；模型原文一律进
    正文通道（空原文返回空串）。暂停与选项不被没收。"""
    short = f"「{stage_label or '本阶段'}」已完成，请过目以上成果并选择下一步。"
    return short, str(model_message or "")


def normalize_option_surface(
    state: Dict[str, Any],
    skill: str,
    message: str,
    options: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """选项面单一归一（模型不撰写工作流选项，非法直接拒收）。

    - 模型选项原样保留（普通确认语义）。
    （2026-08-31 用户裁决：规格向导机械合并退役，模型选项不再拒收。
      2026-09-10 阶段规则去代码化批：阶段边界系统派生的「继续」项退役——
      平台不再判阶段完成，无边界可派生；state/skill 形参保留以稳住调用契约。）
    """
    opts = [o for o in (options or []) if isinstance(o, dict)]
    return message, opts
