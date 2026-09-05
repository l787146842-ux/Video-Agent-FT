# -*- coding: utf-8 -*-
"""阶段成果正文通道（三通道分离正向设计 A）。

阶段成果（结构化分析等）由层 9 代码从工作台状态**确定性渲染**进正文
markdown，模型只负责短交代与提问——对齐 Claude Code/Codex/Flova 的
「用户面向内容由系统从状态渲染」业界共识（防成果被模型塞进 workflow_pause.message 导致阶段卡变正文、正文变旁白）。

渲染器注册表按工具名键控；v1 仅注册 script_analyze，未来阶段
（故事板自检报告等）按同注册表扩展，零侵入。
"""
from typing import Any, Callable, Dict, List


def _render_script_analyze(state: Dict[str, Any]) -> str:
    """剧本分析成果 → 正文 markdown（批 5 自由文本口径：《doc》+ 一句话
    总结 + 报告全文原样；不再拆要点粗体化）。"""
    analysis = state.get("analysis") or {}
    summary = str(analysis.get("summary") or "").strip()
    if not summary:
        return ""
    doc_name = str(analysis.get("doc_name") or "").strip()
    lines: List[str] = [
        f"## 剧本分析《{doc_name}》" if doc_name else "## 剧本分析",
        f"**一句话总结**：{summary}",
    ]
    report = str(analysis.get("report") or "").strip()
    if report:
        lines.append(report)
    return "\n".join(lines)


# 渲染器注册表：工具名 → (state) -> markdown 块（空串 = 无成果可渲染）
# 键 = 分析写入工具名（script_analysis_report，A1 批）；能力词 script_analyze
# 是章节标签非工具名，不作键（防幻影工具名回潮，test_skill_assistant_route）
TOOL_DELIVERABLE_RENDERERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "script_analysis_report": _render_script_analyze,
}


def render_stage_deliverables(
    state: Dict[str, Any], executed_tools: List[str],
) -> str:
    """本轮成功执行的工具成果按注册表渲染为正文 markdown；无命中返回空串。

    executed_tools 保序去重（同工具重复执行只渲染一次，取当前状态）。
    """
    blocks: List[str] = []
    for tool in dict.fromkeys(executed_tools or []):
        renderer = TOOL_DELIVERABLE_RENDERERS.get(str(tool or "").strip())
        if renderer is None:
            continue
        block = renderer(state or {})
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)
