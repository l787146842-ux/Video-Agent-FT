# -*- coding: utf-8 -*-
"""剧本分析写入通道（Skill 流程跑通修复批 1 · A1；批 5 改自由文本）。

此前全仓多处读 ``state.analysis.summary``、零处写入：模型没有
「分析有地方交卷」的工具（协议甚至明示"分析结论直接写入回复"），
工作流永远卡在第一步。本工具补上写入点，既有消费方零改动生效：

- ``stage_probes.stage_done("analysis")`` 客观探针；
- ``event_cards`` 剧本分析已完成事件卡（detail_md 携报告全文挂卡折叠，
  对齐批 2026-09-08 前为 stage_deliverables 正文渲染，已随裁决退役）；
- ``gates_cards`` 分析探针判据；
- ``context_builder._build_analysis`` 状态裁剪注入。

命名口径：工具名 = ``script_analysis_report``，与能力词
``script_analyze``（Skill 章节标签，阶段标记非工具名）刻意区分——
防幻影能力词回潮进助手白名单（test_skill_assistant_route 钉死）。

形态口径（批 5，对齐外部标杆 机制）：外部标杆 全程没有结构化字段表——
分析/规格都是自由文本，平台从不解析产物内容判流程进度。故入参只留
一个必填的一句话锚点 + 自由文本报告，模型按各自 Skill 的
``script_analyze`` 章节要求想写什么写什么；完成判据 = 本工具调用
成功（动作即事实），不再有"字段名失配→模型连败放弃"这类死法。
"""
from typing import Type

from pydantic import BaseModel, Field

from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import BaseTool, StrictToolInput, ToolResult
from src.video_agent.tools.manager import ToolManager


class ScriptAnalyzeInput(StrictToolInput):
    """script_analysis_report 入参（写类，extra=forbid）"""

    doc_name: str = Field("", description="分析的剧本来源文档名（无文档留空）")
    summary: str = Field(
        ..., description="一句话总结（分析阶段的完成锚点，不能为空）")
    report_markdown: str = Field(
        "",
        description=(
            "分析报告全文（Markdown 自由文本）：按所用 Skill 的 script_analyze "
            "章节要求撰写；Skill 未声明分析路径时格式自定。字段与格式不限，"
            "只求后续阶段能照此执行"
        ),
    )
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class ScriptAnalyzeTool(BaseTool):
    name = "script_analysis_report"
    risk = "medium"  # §2.7：写状态但可整体重写（分析结论可再次提交覆盖）
    detail_tier = "expand"  # 产出类：展开看输入参数+执行结果
    description = (
        "提交剧本/素材分析结论（分析阶段的完成落点，调用成功即视为完成）："
        "summary 一句话总结 + 按所用 Skill 的 script_analyze 章节要求写 Markdown 报告"
        "（Skill 未声明分析路径时格式自定）；重复提交以最后一次为准。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ScriptAnalyzeInput

    async def aexecute(self, params: ScriptAnalyzeInput) -> ToolResult:
        summary = str(params.summary or "").strip()
        if not summary:
            return ToolResult(
                success=False,
                error=("Validation Error: summary 不能为空（一句话总结是分析阶段的"
                       "完成锚点）。已提交的其他字段本次未写入，补上总结后整体重新提交即可。"),
                error_code="validation", retryable=False,
            )
        payload = {
            "doc_name": str(params.doc_name or "").strip(),
            "summary": summary,
            "report": str(params.report_markdown or "").strip(),
        }
        svc = StateManager.get_instance()
        async with svc.lock:
            svc.state_dict["analysis"] = payload
            svc.save()
        return ToolResult(success=True, data={
            "summary_chars": len(summary),
            "report_chars": len(payload["report"]),
        })


def register_analysis_tools() -> None:
    """注册分析写入 Tool（与 register_document_tools 同一接线口径）"""
    ToolManager.register(ScriptAnalyzeTool())
