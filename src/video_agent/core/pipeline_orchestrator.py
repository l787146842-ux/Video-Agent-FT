# -*- coding: utf-8 -*-
"""状态驱动管线编排器（0818 架构板正批 B1）。

顶层顺序归代码：按工作台客观状态计算当前阶段、按批派发执行器、
阶段边界机械暂停；模型只做阶段内创作与 ad-hoc 指令（混合模式，B2 接线）。
对齐 Flova / LLM-as-Code 业界标准形态：顺序不来自散文解析，也不来自模型选择。

阶段表 = 平台规范表（探针客观判定）+ sidecar 覆盖（裁剪/同批执行器）。
创作型阶段（ke_media/shot_media）deterministic=False，B2 起交接模型循环。
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime.progress import emit_progress
from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS


@dataclass(frozen=True)
class StageSpec:
    key: str
    title: str
    executors: Tuple[str, ...] = ()
    # 编排层直调执行器；False = 创作型阶段，交接模型循环（混合模式逃生门）
    deterministic: bool = True


CANONICAL_STAGES: Tuple[StageSpec, ...] = (
    StageSpec("analysis", "剧本分析", ("script_analyze",)),
    StageSpec("spec", "成片规格"),
    StageSpec("structure", "故事板拆解",
              ("storyboard_key_elements", "storyboard_shots", "storyboard_audio")),
    StageSpec("ke_media", "关键元素设定图", (), deterministic=False),
    StageSpec("shot_media", "逐镜视频生成", (), deterministic=False),
    StageSpec("audio_assets", "音频资产", ("audio_generate",)),
    StageSpec("assembly", "时间线组装", ("video_assembler",)),
)


def _has_media(groups: List[Dict[str, Any]], field: str) -> bool:
    return any(
        str((d or {}).get(field) or "").strip()
        for g in (groups or []) for d in (g.get("drafts") or [])
        if isinstance(d, dict)
    )


def stage_done(key: str, state: Dict[str, Any]) -> bool:
    """阶段完成度客观探针（只认状态事实，认不出=未完成）。"""
    if key == "analysis":
        return bool((state.get("analysis") or {}).get("summary"))
    if key == "spec":
        return prompt_gates.has_spec_document(state)
    ke = state.get(CAT_KEY_ELEMENTS) or []
    shots = state.get(CAT_SHOTS) or []
    audio = state.get(CAT_AUDIO_ITEMS) or []
    if key == "structure":
        return bool(ke) and bool(shots) and bool(audio)
    if key == "ke_media":
        return bool(ke) and _has_media(ke, "imgUrl")
    if key == "shot_media":
        return bool(shots) and _has_media(shots, "videoUrl")
    if key == "audio_assets":
        return bool(audio) and (
            _has_media(audio, "audioUrl")
            or any(str((d or {}).get("prompt") or "").strip()
                   for g in audio for d in (g.get("drafts") or []))
        )
    if key == "assembly":
        return bool(shots) and _has_media(shots, "videoUrl")
    return False


def stage_table(skill: str) -> List[StageSpec]:
    """平台规范阶段表 + sidecar 覆盖（skip 裁剪 / 同批执行器替换）。"""
    manifest = registry.skill_manifest_of(skill) or {}
    overrides = ((manifest.get("flow") or {}).get("stages") or {})
    table: List[StageSpec] = []
    for spec in CANONICAL_STAGES:
        ov = overrides.get(spec.key) or {}
        if ov.get("skip"):
            continue
        executors = tuple(ov.get("executors") or spec.executors)
        table.append(StageSpec(spec.key, spec.title, executors, spec.deterministic))
    return table


def current_stage(state: Dict[str, Any], skill: str) -> Optional[StageSpec]:
    """第一个未完成的阶段；全部完成返回 None。"""
    for spec in stage_table(skill):
        if not stage_done(spec.key, state):
            return spec
    return None


async def run_deterministic_stage(
    skill: str, spec: StageSpec, *, max_retry: int = 1,
) -> List[Any]:
    """按批顺序直调执行器；失败确定性重试（幂等执行器安全），重试权不归模型。"""
    from src.video_agent.skill_runtime.exec_tools import build_executor_tool

    results = []
    for name in spec.executors:
        tool = build_executor_tool(name)
        if tool is None:
            logger.warning(f"[Orchestrator] 未知执行器 {name}，跳过")
            continue
        await emit_progress(f"正在执行「{spec.title}」：{name}…")
        schema = tool.get_input_schema()
        try:
            params = schema(skill_name=skill)
        except Exception:
            params = schema()
        attempt = 0
        while True:
            res = await tool.aexecute(params)
            if res.success or attempt >= max_retry:
                break
            attempt += 1
            logger.warning(
                f"[Orchestrator] {name} 失败，确定性重试 {attempt}/{max_retry}: {res.error}")
        results.append(res)
    return results


def compose_pause_card(
    state: Dict[str, Any], skill: str, done_spec: StageSpec,
    next_spec: Optional[StageSpec],
) -> Tuple[str, List[Dict[str, str]]]:
    """阶段边界暂停卡：纯客观事实（P3）；总结是否入卡随 sidecar 声明。"""
    manifest = registry.skill_manifest_of(skill) or {}
    include_summary = bool(
        ((manifest.get("pause") or {}).get("include_summary_in_pause")))
    lines = [f"✅ 阶段「{done_spec.title}」已完成。"]
    if done_spec.key == "analysis" and include_summary:
        summary = str((state.get("analysis") or {}).get("summary") or "").strip()
        if summary:
            lines.append(f"剧本一句话总结：{summary}")
    if next_spec:
        lines.append(f"下一阶段：「{next_spec.title}」。")
    else:
        lines.append("全部阶段已完成。")
    lines.append("确认后回复「继续」推进；如需调整请直接说明。")
    options = [
        {"label": "确认，继续", "value": "继续"},
        {"label": "先调整", "value": ""},
    ]
    return "\n".join(lines), options


@dataclass
class OrchestratorOutcome:
    kind: str  # paused / spec_pending / handoff_model / all_done / stage_failed
    message: str = ""
    options: List[Dict[str, str]] = None
    results: List[Any] = None


def flow_auto_continue(state: Dict[str, Any]) -> bool:
    """flow_directive 单消息豁免：本条消息不暂停（既有交互字段）。"""
    return bool(((state.get("interaction") or {}).get("auto_continue")))


async def orchestrate_turn(
    state_manager: Any, skill: str,
) -> Optional[OrchestratorOutcome]:
    """编排一轮：连续推进确定性阶段直到暂停/交接/失败。

    返回 None = 当前阶段为创作型，交接模型循环（B2 接线）。
    """
    state = state_manager.state_dict
    auto = flow_auto_continue(state)
    while True:
        spec = current_stage(state, skill)
        if spec is None:
            return OrchestratorOutcome("all_done", message="全部阶段已完成。")
        if not spec.deterministic:
            return None
        if spec.key == "spec":
            return OrchestratorOutcome("spec_pending")
        results = await run_deterministic_stage(skill, spec)
        failed = [r for r in results if not getattr(r, "success", False)]
        if failed:
            return OrchestratorOutcome(
                "stage_failed",
                message=f"阶段「{spec.title}」执行失败：{failed[0].error}",
                results=results,
            )
        nxt = current_stage(state, skill)
        if auto:
            continue
        msg, opts = compose_pause_card(state, skill, spec, nxt)
        return OrchestratorOutcome("paused", message=msg, options=opts, results=results)
