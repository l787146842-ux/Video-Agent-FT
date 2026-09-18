# -*- coding: utf-8 -*-
"""A' 阶段键控临时尾通道（2026-09-18 批 B）。

故事板设计阶段主代理亲做（R4 裁决），skill 章节靠 read_skill 自愿读会被
长上下文稀释（2222 病：写 shot 时章节已被 3-4 万 token 埋没 → 单运镜、
零内切、台词脱离）。本模块每步构造「临时尾」= 当前故事板窗口对应的
剧本分析摘要 + skill 章节原文，经 agent_loop 的 extra_messages 通道拼在
消息最末（近生成端）、**不落事件流**。

设计定案（计划书 §五 / 已锁定决策）：
- 注入单位 = 一步（一次 LLM 调用），非分组；窗口内每步重算注入；
- 窗口 = KE 已开始且 review_storyboard 未过（workflow_runtime.in_storyboard_window，
  避探针粒度陷阱：建第一批 shot 后节点翻 audio，章节仍全程在场）；
- 纯函数 (state, skill) → 文本，不含时间戳/随机/遍历序，回放重算字节一致；
- 章节逐字原文，平台零产出形态引导（红线：desc 零引导 / 不给卡面正例）；
- 顺序：analysis 段在前（素材）、章节段在末（规范，近因效应离生成最近）；
- analysis 从状态快照挪来（context_builder 已摘除），只在本窗口注入，
  恢复裁决③「故事板阶段注入分析、其他阶段不需要」，且不与快照双份付钱。
"""
from typing import Any, Dict

from src.video_agent.core import workflow_runtime
from src.video_agent.skill_runtime import registry

# 故事板设计三章能力名（经 registry.SkillEntry.section_for 取原文）
_STORYBOARD_CAPABILITIES = (
    "storyboard_key_elements", "storyboard_shots", "storyboard_audio",
)

# 剧本分析注入预算（原 context_builder._build_analysis 同源；批 B 移此单一源）
_ANALYSIS_SUMMARY_CHARS = 500
_ANALYSIS_REPORT_CHARS = 2500


def _analysis_digest(state: Dict[str, Any]) -> str:
    """剧本分析摘要文本段（summary + report 截断）；无分析返回空串。

    纯函数：仅读 state.analysis，截断预算固定 → 回放字节一致。
    """
    analysis = state.get("analysis")
    if not isinstance(analysis, dict):
        return ""
    parts = []
    summary = str(analysis.get("summary") or "").strip()
    if summary:
        parts.append("分析摘要：" + summary[:_ANALYSIS_SUMMARY_CHARS])
    report = str(analysis.get("report") or "").strip()
    if report:
        parts.append("分析全文：" + report[:_ANALYSIS_REPORT_CHARS])
    if not parts:
        return ""
    # 引导头中性（标明来源与用途，零产出形态引导）
    return ("== 剧本分析（故事板设计参照，script_analyze 产出）==\n\n"
            + "\n\n".join(parts))


def build_stage_section_tail(state: Dict[str, Any], skill: str) -> str:
    """构造 A' 故事板临时尾（纯函数；非故事板窗口返回空串）。

    仅依赖 (state, skill)：窗口判定用客观探针、章节取 registry 装载的
    skill 原文、analysis 取 state.analysis，不掺时间戳/随机/遍历序 →
    回放重算字节一致（不落事件流）。
    返回空串 = 本步不注入（非故事板窗口 / skill 不可加载 / 章节为空）。
    """
    if not skill or not isinstance(state, dict):
        return ""
    if not workflow_runtime.in_storyboard_window(state, skill):
        return ""
    entry = registry.resolve_loadable_entry(skill)
    if entry is None:
        return ""
    sections = []
    for cap in _STORYBOARD_CAPABILITIES:
        sec = (entry.section_for(cap) or "").strip()
        if sec:
            sections.append(sec)
    if not sections:
        return ""
    parts = []
    # analysis 段在前（素材）；章节段在末（规范，近生成端 → 近因效应）
    digest = _analysis_digest(state)
    if digest:
        parts.append(digest)
    # 引导语极简中性、零产出形态引导（红线）；return 内联字符串（非模块级
    # CJK 常量，不触 check_prompt_literals）；章节原文在末 = 近生成端。
    parts.append("== 当前制作阶段 Skill 章节原文（逐字）==\n\n"
                 + "\n\n".join(sections))
    return "\n\n".join(parts)
