# -*- coding: utf-8 -*-
"""剧本分析写入通道（Skill 流程跑通修复批 1 · A1）。

此前全仓多处读 ``state.analysis.summary``、零处写入：模型没有
「分析有地方交卷」的工具（协议甚至明示"分析结论直接写入回复"），
工作流永远卡在第一步。本工具补上写入点，既有消费方零改动生效：

- ``stage_probes.stage_done("analysis")`` 客观探针；
- ``stage_deliverables`` 阶段成果渲染器（按工具名键控，
  正文自动渲染总结与要点）；
- ``gates_cards`` 分析探针判据；
- ``context_builder._build_analysis`` 状态裁剪注入。

命名口径：工具名 = ``script_analysis_report``，与能力词
``script_analyze``（Skill 章节标签，阶段标记非工具名）刻意区分——
防幻影能力词回潮进助手白名单（test_skill_assistant_route 钉死）。

参数 schema 取自各 Skill ``script_analyze`` 章节要求（剧本分类 A/B/C、
角色/场景/道具清单、幕次结构）。skill 感知（M6）：章节为空/不存在的
Skill（如商品宣传短片）不要求分析产物；A/B/C 只是工具参数，不是平台
分支——跳不跳过分析是模型的判断。
"""
from typing import List, Type

from pydantic import BaseModel, ConfigDict, Field

from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import BaseTool, StrictToolInput, ToolResult
from src.video_agent.tools.manager import ToolManager


class CharacterEntry(BaseModel):
    """角色条目（仅提取剧本已明确描述的内容，缺失项由模型标注「待用户补充」）"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="角色名")
    scenes: str = Field("", description="出场场景")
    appearance: str = Field("", description="外貌/服装描述（含多套造型时分行列出）")


class SceneEntry(BaseModel):
    """场景条目"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="场景名")
    features: str = Field("", description="空间特征描述（结构/参照物/材质/光源）")
    shot_range: str = Field("", description="出现的镜头范围")


class ActEntry(BaseModel):
    """幕次条目"""

    model_config = ConfigDict(extra="forbid")

    act: str = Field(..., description="幕次（开篇/发展/转折/高潮/结尾）")
    shots_estimate: str = Field("", description="该幕大致镜头数量估算")


class ScriptAnalyzeInput(StrictToolInput):
    """script_analyze 入参（写类，extra=forbid 原子拒收未知字段）"""

    doc_name: str = Field("", description="分析的剧本来源文档名（无文档留空）")
    script_class: str = Field(
        "",
        description=(
            "剧本分类结论：A（成熟分镜剧本，可直接拆故事板）| "
            "B（散文体/纯对话，建议先短剧化改编）| C（半结构化，拆解时补全分镜要素）。"
            "Skill 无分类轴时留空"
        ),
    )
    summary: str = Field(..., description="一句话总结（分析阶段的完成判据，不能为空）")
    key_points: List[str] = Field(
        default_factory=list, description="关键要点清单（人物/场景/风格/硬约束等，逐条一行）"
    )
    characters: List[CharacterEntry] = Field(
        default_factory=list, description="角色清单（姓名/出场场景/外貌服装）"
    )
    scenes: List[SceneEntry] = Field(
        default_factory=list, description="场景清单（名称/空间特征/镜头范围）"
    )
    props: List[str] = Field(default_factory=list, description="关键道具")
    acts: List[ActEntry] = Field(
        default_factory=list, description="剧情结构：幕次划分与各幕镜头数量估算"
    )
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class ScriptAnalyzeTool(BaseTool):
    name = "script_analysis_report"
    risk = "medium"  # §2.7：写状态但可整体重写（分析结论可再次提交覆盖）
    detail_tier = "expand"  # 产出类：展开看输入参数+执行结果
    description = (
        "提交剧本/素材分析结论（分析结果的唯一落点）：分类结论、一句话总结、"
        "角色/场景/道具清单、幕次结构。分析完成后必须调用本工具落账，"
        "否则平台不认为分析阶段已完成；重复调用以最后一次为准。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ScriptAnalyzeInput

    async def aexecute(self, params: ScriptAnalyzeInput) -> ToolResult:
        summary = str(params.summary or "").strip()
        if not summary:
            return ToolResult(
                success=False,
                error=("Validation Error: summary 不能为空（一句话总结是分析阶段的"
                       "完成判据）。已提交的其他字段本次未写入，补上总结后整体重新提交即可。"),
                error_code="validation", retryable=False,
            )
        payload = {
            "doc_name": str(params.doc_name or "").strip(),
            "script_class": str(params.script_class or "").strip().upper(),
            "summary": summary,
            "key_points": [p.strip() for p in params.key_points if str(p or "").strip()],
            "characters": [c.model_dump() for c in params.characters],
            "scenes": [s.model_dump() for s in params.scenes],
            "props": [p.strip() for p in params.props if str(p or "").strip()],
            "acts": [a.model_dump() for a in params.acts],
        }
        svc = StateManager.get_instance()
        async with svc.lock:
            svc.state_dict["analysis"] = payload
            svc.save()
        return ToolResult(success=True, data={
            "summary_chars": len(summary),
            "key_points": len(payload["key_points"]),
            "characters": len(payload["characters"]),
            "scenes": len(payload["scenes"]),
            "props": len(payload["props"]),
            "acts": len(payload["acts"]),
        })


def register_analysis_tools() -> None:
    """注册分析写入 Tool（与 register_document_tools 同一接线口径）"""
    ToolManager.register(ScriptAnalyzeTool())
