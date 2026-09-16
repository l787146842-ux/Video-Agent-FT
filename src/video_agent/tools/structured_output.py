# -*- coding: utf-8 -*-
"""K6 批（2026-09-16 对齐 flova/dsh）：子代理结构化完工打卡工具 structured_output。

dsh `packages/subagent/subagent-in-process-driver/src/structured.ts` 同构：
「完成 = 一次工具调用」——子代理收尾必须调本工具按四槽（created/modified/
removed/unfinished）汇报实际落账事实，取代读纯文本收尾猜完成（假停闸机
误判根因）；打卡成功后本轮终局 guard 拒收后续工具调用（dsh :109-111 同款，
落点 = core/fc_tool_runner 轮内 guard）。

可见性：子代理专属（subagent_depth≥1）；主代理面经
planner._compute_excluded_tools 裁 CHILD_ONLY_TOOLS（且不进 UNAVAILABLE 段渲染）。
汇报指令文案唯一源 = prompts/shared/structured_output.md::BRIEF（随委派任务
下发，subagent.md 逐字锁零触碰）。
"""
from typing import List, Type

from pydantic import BaseModel, Field

from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.manager import ToolManager


class StructuredOutputInput(BaseModel):
    """structured_output 入参（四槽汇报；槽内条目为人可读事实清单）。"""

    created: List[str] = Field(
        default_factory=list,
        description="本次委派已创建的组/卡清单（类别+名称+ID），无则空数组")
    modified: List[str] = Field(
        default_factory=list,
        description="本次委派已修改的清单（类别+位置），无则空数组")
    removed: List[str] = Field(
        default_factory=list,
        description="本次委派已移除的清单（类别+位置），无则空数组")
    unfinished: List[str] = Field(
        default_factory=list,
        description="未完成事项清单（交回主代理处理），无则空数组")


class StructuredOutputTool(BaseTool):
    name = "structured_output"
    risk = "low"  # 只读汇报（落账事实由既有生产工具写入，本工具不写状态）
    detail_tier = "expand"  # 关键控制流：展开可见四槽汇报
    description = (
        "子代理完工打卡：委派任务收尾时调用本工具一次，按 created/modified/"
        "removed/unfinished 四槽汇报实际落账事实；打卡成功即委派完成确认。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return StructuredOutputInput

    async def aexecute(self, params: StructuredOutputInput) -> ToolResult:
        report = {
            "created": list(params.created),
            "modified": list(params.modified),
            "removed": list(params.removed),
            "unfinished": list(params.unfinished),
        }
        return ToolResult(success=True, data={
            "captured": True,
            "report": report,
            "summary": (
                f"已创建 {len(report['created'])} 项；已修改 {len(report['modified'])} 项；"
                f"已移除 {len(report['removed'])} 项；未完成 {len(report['unfinished'])} 项。"),
        })


def register_structured_output_tools() -> None:
    """注册子代理完工打卡 Tool（与 register_analysis_tools 同一接线口径）。"""
    ToolManager.register(StructuredOutputTool())
