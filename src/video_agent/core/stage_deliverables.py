# -*- coding: utf-8 -*-
"""阶段成果正文通道（三通道分离正向设计 A）。

阶段成果（结构化分析等）由层 9 代码从工作台状态**确定性渲染**进正文
markdown，模型只负责短交代与提问——对齐 Claude Code/Codex/Flova 的
「用户面向内容由系统从状态渲染」业界共识（1111 事故正向修复：成果曾
被模型塞进 workflow_pause.message 导致阶段卡变正文、正文变旁白）。

渲染器注册表按工具名键控；v1 仅注册 script_analyze，未来阶段
（故事板自检报告等）按同注册表扩展，零侵入。
"""
from typing import Any, Callable, Dict, List


def _split_point_head(point: str) -> tuple:
    """要点行拆「标题：内容」（全角/半角冒号均认）；标题过长视为无标题。"""
    for sep in ("：", ":"):
        if sep in point:
            head, _, rest = point.partition(sep)
            if head and rest and len(head) <= 12:
                return head.strip(), rest.strip()
    return "", point


def _render_script_analyze(state: Dict[str, Any]) -> str:
    """剧本分析成果 → 正文 markdown（《doc》+ 一句话总结 + 要点清单）。"""
    analysis = state.get("analysis") or {}
    summary = str(analysis.get("summary") or "").strip()
    if not summary:
        return ""
    doc_name = str(analysis.get("doc_name") or "").strip()
    lines: List[str] = [
        f"## 剧本分析《{doc_name}》" if doc_name else "## 剧本分析",
        f"**一句话总结**：{summary}",
    ]
    for point in (analysis.get("key_points") or []):
        p = str(point or "").strip()
        if not p:
            continue
        head, rest = _split_point_head(p)
        lines.append(f"- **{head}**：{rest}" if head else f"- {p}")
    return "\n".join(lines)


# 渲染器注册表：工具名 → (state) -> markdown 块（空串 = 无成果可渲染）
TOOL_DELIVERABLE_RENDERERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "script_analyze": _render_script_analyze,
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
