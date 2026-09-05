# *- coding: utf-8 -*-
"""状态驱动管线知识源 + 闸预检（定义层承自本模块，账本/裁判数据归 workflow_runtime）。

本模块提供阶段表/依赖图/客观探针作为「法条」，供闸机消费（done-闸判定完成、
轮始闸预检装配原料闸/规格闸兜底卡；stage_precondition 越阶闸已随 C1b 退役）
（层 9 由代码执行不依赖模型自觉；行动发起永远归模型）。

本模块是纯数据层（阶段表/探针/兜底卡装配），无任何编排权
（不发起行动、不驱动轮次）。
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.core import gates_cards
from src.video_agent.skill_runtime import registry
from src.video_agent.state.models import (
    ASSEMBLY_PLAN_DOC_NAME, CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS,
)

# 粘性豁免/原料闸/规格闸机械兜底卡已随用户裁决 2026-08-31 退役
# （Flova 对齐：流程顺序与原料收集归 skill 散文 + 模型自觉，
# 平台不再轮始发卡）。


@dataclass(frozen=True)
class StageSpec:
    key: str
    title: str
    executors: Tuple[str, ...] = ()
    # 编排层直调执行器；False = 创作型阶段，交接模型循环（混合模式逃生门）
    deterministic: bool = True


CANONICAL_STAGES: Tuple[StageSpec, ...] = (
    StageSpec("analysis", "剧本分析", ("script_analyze",)),
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


def _all_media(groups: List[Dict[str, Any]], field: str) -> bool:
    """全部草稿均已具备指定媒体（无任何草稿时返 False，防空集恒真）"""
    drafts = [
        d for g in (groups or []) for d in (g.get("drafts") or [])
        if isinstance(d, dict)
    ]
    return bool(drafts) and all(str((d or {}).get(field) or "").strip() for d in drafts)


# 组装阶段客观产物：video_assembler 执行器落盘的成片组装方案文档。
# 探针据此区分「已生成未组装」与「已组装」（对标 Stop≠Done≠Verified：
# 完成必须看产物证据，不与 shot_media 探针同构）；常量归 state/models 单一事实源。


def _has_assembly_plan_doc(state: Dict[str, Any]) -> bool:
    return _has_document_named(state, ASSEMBLY_PLAN_DOC_NAME)


def _has_document_named(state: Dict[str, Any], name: str) -> bool:
    return any(
        str(d.get("name") or "") == name
        for d in (state.get("documents") or []) if isinstance(d, dict)
    )


def stage_done(key: str, state: Dict[str, Any], skill: str = "") -> bool:
    """阶段完成度客观探针（只认状态事实，认不出=未完成；fail-closed）。

    批 5「动作即事实」口径：analysis 判据 = 分析写入动作已落账
    （summary 是工具落账的最小锚点），平台不解析报告内容评流程。
    （C1b 裁决 2026-08-31：frontmatter done 声明通道退役，
    恒走各阶段平台客观探针。）"""
    if key == "analysis":
        return bool((state.get("analysis") or {}).get("summary"))
    ke = state.get(CAT_KEY_ELEMENTS) or []
    shots = state.get(CAT_SHOTS) or []
    audio = state.get(CAT_AUDIO_ITEMS) or []
    if key == "structure":
        return bool(ke) and bool(shots) and bool(audio)
    # 节点级结构探针：workflow_contract 单节点
    # 完成判定用（运行时内部键）。
    if key == "key_elements":
        return bool(ke)
    if key == "shots_groups":
        return bool(shots)
    if key == "audio_groups":
        return bool(audio)
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
        # 声明通道已在函数首位判定；未声明回落「全部分镜有视频 +
        # 组装方案文档在盘」，与 shot_media 探针解耦（已生成未组装不再误判完成）
        return (
            bool(shots)
            and _all_media(shots, "videoUrl")
            and _has_assembly_plan_doc(state)
        )
    return False


def step_done_declared(step_no: Any, skill: str) -> Optional[str]:
    """frontmatter flow.step_done_conditions 声明：step 号 → 客观探针阶段键；
    未声明返回 None（声明驱动，不猜）。"""
    if not skill:
        return None
    manifest = registry.skill_manifest_of(skill) or {}
    stage_key = str(
        ((manifest.get("flow") or {}).get("step_done_conditions") or {}).get(str(step_no))
        or ""
    ).strip()
    return stage_key or None


def step_done(step_no: Any, state: Dict[str, Any], skill: str) -> bool:
    """step 完成度客观探针（声明驱动，fail-closed）：
    step_done_conditions 声明的阶段探针是唯一事实源；未声明返 False。
    探针只记录客观完成度，不发起行动。"""
    stage_key = step_done_declared(step_no, skill)
    return stage_done(stage_key, state, skill) if stage_key else False


def step_done_probe(
    step_no: Any, state: Dict[str, Any], skill: str,
) -> Optional[bool]:
    """step_done_conditions 消费方适配：未声明返 None（回落消费方旧规则），
    已声明返客观探针结果（三态区分「无声明」与「声明了未完成」）。"""
    if step_done_declared(step_no, skill) is None:
        return None
    return step_done(step_no, state, skill)


def stage_table(skill: str) -> List[StageSpec]:
    """平台规范阶段表（skill 感知裁剪）。

    无 video_assembler 执行器章节的 Skill 无组装阶段。
    （C1b 裁决 2026-08-31：flow.stages dict 覆盖声明退役；
    2026-08-31 用户裁决：spec 机械阶段退役，规格归散文驱动。）"""
    entry = registry.resolve_entry(skill)
    tools = set(entry.available_tools) if entry else set()
    table: List[StageSpec] = []
    for spec in CANONICAL_STAGES:
        if spec.key == "assembly" and "video_assembler" not in tools:
            continue
        table.append(StageSpec(spec.key, spec.title, spec.executors, spec.deterministic))
    return table


def current_stage(state: Dict[str, Any], skill: str) -> Optional[StageSpec]:
    """第一个未完成的阶段；全部完成返回 None。"""
    for spec in stage_table(skill):
        if not stage_done(spec.key, state, skill):
            return spec
    return None


# ---------- 3A：frontmatter dependencies 消费（DAG 调度） ----------

def _step_to_stage(
    step_no: Any, manifest: Optional[Dict[str, Any]], table: List[StageSpec],
) -> Optional[str]:
    """frontmatter step 号 → 平台规范阶段：① step_stages 显式声明（权威）；
    ② stage_executors 执行器交集。
    （显式声明通道保留以兼容内存 manifest 注入的测试同构口径。）"""
    flow = ((manifest or {}).get("flow") or {})
    keys = {s.key for s in table}
    declared = str((flow.get("step_stages") or {}).get(str(step_no)) or "").strip()
    if declared:
        return declared if declared in keys else None
    execs = (flow.get("stage_executors") or {}).get(str(step_no)) or []
    if execs:
        for spec in table:
            if set(execs) & set(spec.executors):
                return spec.key
    return None


def _stage_dependencies(skill: str) -> Dict[str, List[str]]:
    """frontmatter flow.dependencies（step 号 DAG）翻译为平台阶段 DAG。

    未声明返回空 dict（orchestrate_turn 回落线性扫描，零行为变更）；
    无法映射的 step（如源协议细粒度步骤）其边被吸收并 warning。
    """
    manifest = registry.skill_manifest_of(skill) or {}
    deps_raw = ((manifest.get("flow") or {}).get("dependencies") or {})
    if not isinstance(deps_raw, dict) or not deps_raw:
        return {}
    table = stage_table(skill)
    all_steps = {str(k) for k in deps_raw}
    for prereqs in deps_raw.values():
        for p in prereqs or []:
            all_steps.add(str(p))
    step2stage = {s: _step_to_stage(s, manifest, table) for s in all_steps}
    out: Dict[str, List[str]] = {}
    for step_no, prereqs in deps_raw.items():
        tgt = step2stage.get(str(step_no))
        if not tgt:
            logger.warning(f"[StageProbes] dependencies step {step_no} 无法映射到平台阶段，边被吸收")
            continue
        for p in prereqs or []:
            src = step2stage.get(str(p))
            if src and src != tgt:
                lst = out.setdefault(tgt, [])
                if src not in lst:
                    lst.append(src)
    # 未声明阶段回落线性前置（表中前一阶段），防「未声明 = 无前置」
    # 打乱规范顺序（如 spec 首轮即就绪）；已声明阶段以声明为准（可并行）。
    prev: Optional[str] = None
    for spec in table:
        if spec.key not in out and prev is not None:
            out[spec.key] = [prev]
        prev = spec.key
    return out


# ---------- 阶段依赖图（规格闸/阶段完成探针共用；
# C1b 裁决 2026-08-31 阶段前置硬闸退役后仅余探针用途） ----------
#
# 业界依据（Claude Code hooks：「Hooks guarantee behavior; prompts suggest」，
# 且 Anthropic RFC#45427 教训：旁路钩子可被绕过，强制必须内嵌执行路径）：
# 阶段顺序不依赖控制流入口的运气，在工具执行路径上机械强制。
# 非执行器工具的归属阶段（执行器归属由阶段表 executors 声明推导）：
_PLATFORM_TOOL_STAGE: Dict[str, str] = {
    # 故事板操作类工具：结构阶段内操作（前置同 structure）
    "storyboard_create_group": "structure",
    "storyboard_add_draft": "structure",
    "storyboard_patch_draft": "structure",
    "storyboard_delete_group": "structure",
    "storyboard_confirm_draft": "structure",
    "storyboard_media_to_chat": "structure",
    "read_draft": "structure",
    # 提示词编写/媒体生成：结构完成后才开放（ke_media 前置=[structure]）
    "write_media_prompt": "ke_media",
    "image_generate": "ke_media",
    "generate_video": "ke_media",
}
_STAGE_TITLES: Dict[str, str] = {s.key: s.title for s in CANONICAL_STAGES}


def tool_stage_of(tool_name: str, table: List[StageSpec]) -> str:
    """工具 → 规范阶段键：阶段表 executors 声明优先，其次平台映射表；未命中返空。"""
    for spec in table:
        if tool_name in spec.executors:
            return spec.key
    return _PLATFORM_TOOL_STAGE.get(tool_name, "")


def _effective_stage_deps(skill: str, table: List[StageSpec]) -> Dict[str, List[str]]:
    """阶段前置闸专用依赖图：声明优先，无前置的阶段一律
    补线性前置（表中前一阶段）——闸机比调度更保守：调度里「未声明=未填」
    的留白在闸机层不允许（否则 ke_media 等阶段会裸奔越阶）。"""
    deps = {k: list(v) for k, v in _stage_dependencies(skill).items()}
    prev: Optional[str] = None
    for spec in table:
        if not deps.get(spec.key) and prev is not None:
            deps[spec.key] = [prev]
        prev = spec.key
    return deps


async def gate_precheck(
    state_manager: Any, skill: str, user_message: Any = "",
) -> None:
    """闸预检壳（2026-08-31 用户裁决退役原料闸/规格闸机械兜底卡）。

    恒返回 None = 交接模型循环；流程顺序与原料收集归 skill 散文 +
    模型自觉（Flova 对齐）。保留委托壳：planner_triage/planner 委托。
    """
    return None


# step_done_conditions 声明探针注入下一步机械派生（gates_cards 被
# prompt_gates 导入，反向顶层 import 成环，故用注册钩子解耦）。
gates_cards.register_step_done_probe(step_done_probe)
