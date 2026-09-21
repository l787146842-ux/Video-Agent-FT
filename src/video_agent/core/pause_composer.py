# -*- coding: utf-8 -*-
"""暂停卡通道/选项面处理。

暂停卡唯一发行主体 = 模型的 workflow_pause 工具调用（对齐
AskUserQuestion 范式）；本模块只做通道分离，不发行卡片。

2026-09-21 批B（事故 5555/Q4，用户裁决「照搬 dsh」）：**问句改由模型撰写**。
翻案 2026-08-31 / v2批4「卡问句系统组装」裁决——原接线为「模型 workflow_pause
只提交需要审批的事实，卡问句系统按阶段组装成固定模板，模型原文一律进正文
通道」。实测（5555 落盘 chatMessages[1].confirm）该模板恒为
「「本阶段」已完成，请过目以上成果并选择下一步。」：阶段标签回落（见
fc_tool_runner 的委派阶段回填）+ 问句与本次要问的事完全无关（那一轮实际在
问输出语言/画幅/时长/角色处理）。

现契约（对齐 dsh `dsh-tool-ask-user` + `dsh-user-questions`）：
- `question` = 模型撰写的问题正文（取代系统模板问句）；`header` = 短标题；
  `detail` = 辅助说明（**不变成选项**）；`multi_select` = 多选标志；
- 回携 `pause_id`（卡片级稳定 id，回答按 id 匹配）；
- **模型未写 question 时回落系统模板**——绝不静默丢弃（`fc_tool_runner`
  记载 2026-09-12 曾因「无阶段感知静默剥离字段」造成假成功空提示词卡，
  该项目红线对本次改动同样适用：宁可回落，不可静默丢）。
- kind（stage_done/confirm）供前端按语义渲染标题。
（remind/collect 卡已随原料闸/规格向导退役删除，用户裁决 2026-08-31。
  阶段边界系统派生「继续」选项已随阶段规则去代码化批退役——平台不再
  判阶段完成，无边界可派生，2026-09-10。）
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

# 暂停卡语义种类（前端标题渲染唯一依据，消灭「待补原料=阶段完成」误标）
PAUSE_KIND_STAGE_DONE = "stage_done"  # 阶段完成审阅
PAUSE_KIND_CONFIRM = "confirm"      # 常规模型暂停


@dataclass
class PauseCard:
    """暂停卡通道分离结果（单一事实源）。

    question：确认通道（前端标题/问句行）——模型撰写优先，空则系统模板；
    overflow：正文通道（模型 message 原文，进正文，绝不进问句行）；
    header / detail：模型撰写的短标题与辅助说明（可选）；
    multi_select：多选标志。
    """

    question: str = ""
    overflow: str = ""
    header: str = ""
    detail: str = ""
    multi_select: bool = False


def stage_template_question(stage_label: str = "") -> str:
    """系统兜底问句（阶段完成模板）——仅在模型未写 question 时使用。"""
    return f"「{stage_label or '本阶段'}」已完成，请过目以上成果并选择下一步。"


def compose_pause_card(
    *,
    model_question: str = "",
    model_message: str = "",
    stage_label: str = "",
    header: str = "",
    detail: str = "",
    multi_select: Any = False,
) -> PauseCard:
    """暂停卡两通道 + 问题级字段的确定性组装（无阈值补丁）。

    模型写了 question → 用它当问句（对齐 dsh：问题由模型撰写）；
    未写 → 回落 `stage_template_question`（不静默丢弃、不空卡）。
    模型 message 一律进正文通道（空原文返回空串）。
    """
    question = str(model_question or "").strip()
    if not question:
        question = stage_template_question(stage_label)
    return PauseCard(
        question=question,
        overflow=str(model_message or ""),
        header=str(header or "").strip(),
        detail=str(detail or "").strip(),
        multi_select=bool(multi_select),
    )


def split_pause_channels(model_message: str, stage_label: str = "") -> Tuple[str, str]:
    """兼容旧签名（返回 (问句, 正文原文)）。

    2026-09-21 批B 起问句归模型撰写，本函数等价于「未写 question」的
    调用形态（恒回落系统模板）。新代码请直接用 `compose_pause_card`。
    """
    card = compose_pause_card(model_message=model_message, stage_label=stage_label)
    return card.question, card.overflow


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
