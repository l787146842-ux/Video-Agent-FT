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

2026-09-21 批F（事故 4444/Q2③+Q3）：**暂停卡由「一个问题」扩为「一次可问
N 个问题」**（对齐 dsh `questions[]`）。4444 实跑取证：模型有 5 个维度要问
（画幅/时长/风格/角色造型/二向箔显名），手上只有**一个扁平 options + 一个
multi_select**，只能自创「套餐」把前四维压成互斥预设、把第五维塞进 detail；
为「怎么问这一个问题」花了 8 段思考/2740 字/34.3s，且第五维**结构上无法被
用户回答** → 模型自判「未回复即遵循原文」并把它写成了既定规格。
dsh 参照：`dsh-tool-ask-user` 的 `ask_user_question` 收 `questions` 数组，
每项自带 id/question/header/options/multi_select（`dsh-user-questions`
types.d.ts:29-44 另有 detail）。

现契约（对齐 dsh `dsh-tool-ask-user` + `dsh-user-questions`）：
- `questions[]` = 问题级列表（**权威面**）；每项 id/question/header/detail/
  options/multi_select；留空则由扁平字段构造单问（**旧形态不废除**）；
- `question` = 首问投影（兼容位，既有消费方零改动）；
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
class PauseQuestion:
    """一个问题（对齐 dsh `AskUserQuestionItem` 的字段面）。

    2026-09-21 批F（事故 4444/Q2③+Q3）：暂停卡由「一个问题」扩为
    「一次可问 N 个问题」——每问自带 id/问句/短标题/说明/选项/多选标志。
    旧形态（一个扁平 question + 一组 options + 一个 multi_select）**不废除**：
    它被归一为**单元素**列表，既有消费方零改动（回落保留，不静默丢弃）。
    """

    id: str = ""
    question: str = ""
    header: str = ""
    detail: str = ""
    multi_select: bool = False
    options: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PauseCard:
    """暂停卡通道分离结果（单一事实源）。

    questions：问题级列表（**权威面**，批F 起一次可问 N 个问题）；
    question：确认通道（前端标题/问句行）——**首问投影**，既有消费方零改动；
    overflow：正文通道（模型 message 原文，进正文，绝不进问句行）；
    header / detail / multi_select：首问投影（同 question，兼容位）。
    """

    question: str = ""
    overflow: str = ""
    header: str = ""
    detail: str = ""
    multi_select: bool = False
    questions: List[PauseQuestion] = field(default_factory=list)


def stage_template_question(stage_label: str = "") -> str:
    """系统兜底问句（阶段完成模板）——仅在模型未写 question 时使用。"""
    return f"「{stage_label or '本阶段'}」已完成，请过目以上成果并选择下一步。"


def normalize_options(raw: Any) -> List[Dict[str, Any]]:
    """选项面归一（唯一实现）：dict 形态取 label/description/group/value，
    纯字符串形态包成 {label}；label 为空者丢弃。**不改语义、不做派生**
    （阶段边界系统派生「继续」项已随阶段规则去代码化批退役）。"""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for o in raw:
        if isinstance(o, dict) and str(o.get("label") or "").strip():
            item = {
                "label": str(o.get("label")).strip(),
                "description": str(o.get("description") or "").strip(),
            }
            if str(o.get("group") or "").strip():
                item["group"] = str(o.get("group")).strip()
            if str(o.get("value") or "").strip():
                item["value"] = str(o.get("value")).strip()
            out.append(item)
        elif isinstance(o, str) and o.strip():
            out.append({"label": o.strip(), "description": ""})
    return out


def normalize_questions(
    raw_questions: Any,
    *,
    model_question: str = "",
    stage_label: str = "",
    header: str = "",
    detail: str = "",
    multi_select: Any = False,
    options: Any = None,
) -> List[PauseQuestion]:
    """问题级归一（批F 唯一实现，对齐 dsh `questions[]`）。

    模型写了 `questions` → 逐项归一（缺 question 的项回落阶段模板，不丢项）；
    未写 → 由扁平字段构造**单元素**列表（旧形态的等价投影，既有行为不变）。
    两路都空问句时仍回落阶段模板——绝不产出空卡（2026-09-12 静默剥离红线）。
    """
    out: List[PauseQuestion] = []
    if isinstance(raw_questions, list):
        for i, q in enumerate(raw_questions):
            if not isinstance(q, dict):
                continue
            qtext = str(q.get("question") or "").strip()
            if not qtext:
                # 缺问句不丢项：回落阶段模板（该问仍有选项可答）
                qtext = stage_template_question(stage_label)
            out.append(PauseQuestion(
                id=str(q.get("id") or "").strip() or f"q{i + 1}",
                question=qtext,
                header=str(q.get("header") or "").strip(),
                detail=str(q.get("detail") or "").strip(),
                multi_select=bool(q.get("multi_select", False)),
                options=normalize_options(q.get("options")),
            ))
    if out:
        return out
    # 回落：旧扁平形态 → 单元素列表
    qtext = str(model_question or "").strip() or stage_template_question(stage_label)
    return [PauseQuestion(
        id="q1",
        question=qtext,
        header=str(header or "").strip(),
        detail=str(detail or "").strip(),
        multi_select=bool(multi_select),
        options=normalize_options(options),
    )]


def compose_pause_card(
    *,
    model_question: str = "",
    model_message: str = "",
    stage_label: str = "",
    header: str = "",
    detail: str = "",
    multi_select: Any = False,
    questions: Any = None,
    options: Any = None,
) -> PauseCard:
    """暂停卡两通道 + 问题级字段的确定性组装（无阈值补丁）。

    模型写了 `questions` → 一次问 N 个问题（各自问句/选项/多选标志）；
    否则由扁平字段构造单问（旧形态等价）。首问投影进 question/header/
    detail/multi_select 兼容位，既有消费方零改动。
    模型 message 一律进正文通道（空原文返回空串）。
    """
    qs = normalize_questions(
        questions,
        model_question=model_question, stage_label=stage_label,
        header=header, detail=detail, multi_select=multi_select,
        options=options,
    )
    first = qs[0]
    return PauseCard(
        question=first.question,
        overflow=str(model_message or ""),
        header=first.header,
        detail=first.detail,
        multi_select=first.multi_select,
        questions=qs,
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
