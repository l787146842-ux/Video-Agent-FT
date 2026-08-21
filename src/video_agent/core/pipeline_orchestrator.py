# *- coding: utf-8 -*-
"""状态驱动管线知识源 + 闸预检（Rule2 主体回归：定义层承自本模块，账本/裁判数据归 workflow_runtime）。

本模块提供阶段表/依赖图/客观探针作为「法条」，供 stage_precondition 闸
否决越阶、done-闸判定完成、轮始闸预检装配原料闸/规格闸兜底卡
（层 9 由代码执行不依赖模型自觉；行动发起永远归模型，ADR-0004）。
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import registry
from src.video_agent.state.models import (
    ASSEMBLY_PLAN_DOC_NAME, CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS,
)


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


def _all_media(groups: List[Dict[str, Any]], field: str) -> bool:
    """全部草稿均已具备指定媒体（无任何草稿时返 False，防空集恒真）"""
    drafts = [
        d for g in (groups or []) for d in (g.get("drafts") or [])
        if isinstance(d, dict)
    ]
    return bool(drafts) and all(str((d or {}).get(field) or "").strip() for d in drafts)


# 组装阶段客观产物（批 6）：video_assembler 执行器落盘的成片组装方案文档。
# 探针据此区分「已生成未组装」与「已组装」（对标 Stop≠Done≠Verified：
# 完成必须看产物证据，不与 shot_media 探针同构）；常量归 state/models 单一事实源。


def _has_assembly_plan_doc(state: Dict[str, Any]) -> bool:
    return any(
        str(d.get("name") or "") == ASSEMBLY_PLAN_DOC_NAME
        for d in (state.get("documents") or []) if isinstance(d, dict)
    )


def _assembly_done_decl(skill: str) -> str:
    """sidecar 组装完成条件声明（flow.stages.assembly.done，可选）：
    当前支持 "document:<文档名>"；未声明返空串（回落平台客观探针）。"""
    if not skill:
        return ""
    manifest = registry.skill_manifest_of(skill) or {}
    return str(
        (((manifest.get("flow") or {}).get("stages") or {}).get("assembly") or {}).get("done")
        or ""
    ).strip()


def stage_done(key: str, state: Dict[str, Any], skill: str = "") -> bool:
    """阶段完成度客观探针（只认状态事实，认不出=未完成；fail-closed）。"""
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
        # 批 6：sidecar 声明优先；未声明回落「全部分镜有视频 + 组装方案文档在盘」，
        # 与 shot_media 探针解耦（已生成未组装不再被误判完成）
        decl = _assembly_done_decl(skill)
        if decl.startswith("document:"):
            name = decl[len("document:"):].strip()
            return any(
                str(d.get("name") or "") == name
                for d in (state.get("documents") or []) if isinstance(d, dict)
            )
        return (
            bool(shots)
            and _all_media(shots, "videoUrl")
            and _has_assembly_plan_doc(state)
        )
    return False


def stage_table(skill: str) -> List[StageSpec]:
    """平台规范阶段表 + sidecar 覆盖（skip 裁剪 / 同批执行器替换）。

    skill 感知裁剪：未声明 spec_wizard 的 Skill 无规格阶段；
    无 video_assembler 执行器章节的 Skill 无组装阶段（除非 sidecar 显式覆盖）。"""
    manifest = registry.skill_manifest_of(skill) or {}
    overrides = ((manifest.get("flow") or {}).get("stages") or {})
    entry = registry.resolve_entry(skill)
    tools = set(entry.available_tools) if entry else set()
    table: List[StageSpec] = []
    for spec in CANONICAL_STAGES:
        ov = overrides.get(spec.key) or {}
        if ov.get("skip"):
            continue
        if spec.key == "spec" and not (
            registry.spec_wizard_active(skill) or ov.get("executors")
        ):
            continue
        if spec.key == "assembly" and "video_assembler" not in tools \
                and not ov.get("executors"):
            continue
        executors = tuple(ov.get("executors") or spec.executors)
        table.append(StageSpec(spec.key, spec.title, executors, spec.deterministic))
    return table


def current_stage(state: Dict[str, Any], skill: str) -> Optional[StageSpec]:
    """第一个未完成的阶段；全部完成返回 None。"""
    for spec in stage_table(skill):
        if not stage_done(spec.key, state, skill):
            return spec
    return None


# ---------- 3A：sidecar dependencies 消费（DAG 调度） ----------
#
# step 描述关键词 → 平台规范阶段。顺序即优先级：assembly 等特化阶段在前，
# structure 作为兼底放最后。step 5 分镜表格图（运镜轨迹示意）属视觉锚点类，
# 归入 ke_media 后其依赖边被吸收（6→[4,5] 坍缩为 shot_media→ke_media）。
_STEP_STAGE_HINTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("analysis", ("分析", "读取并", "剧本文件")),
    ("spec", ("规格", "参数写入", "Final_Video_Spec")),
    ("assembly", ("组装", "时间线", "剪辑")),
    ("ke_media", ("设定图", "概念图", "三视图", "运镜轨迹", "分镜表格图")),
    ("shot_media", ("生成视频", "逐 shot")),
    ("audio_assets", ("音频", "BGM", "旁白")),
    ("structure", ("Storyboard", "故事板", "key_element", "拆解")),
)


def _step_to_stage(
    step_no: Any, manifest: Optional[Dict[str, Any]], table: List[StageSpec],
) -> Optional[str]:
    """sidecar step 号 → 平台规范阶段：① stage_executors 执行器交集；② 描述关键词。"""
    flow = ((manifest or {}).get("flow") or {})
    execs = (flow.get("stage_executors") or {}).get(str(step_no)) or []
    if execs:
        for spec in table:
            if set(execs) & set(spec.executors):
                return spec.key
    desc = str((flow.get("steps") or {}).get(str(step_no)) or "")
    keys = {s.key for s in table}
    for key, kws in _STEP_STAGE_HINTS:
        if key in keys and any(k in desc for k in kws):
            return key
    return None


def _stage_dependencies(skill: str) -> Dict[str, List[str]]:
    """sidecar flow.dependencies（step 号 DAG）翻译为平台阶段 DAG。

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
            logger.warning(f"[Orchestrator] dependencies step {step_no} 无法映射到平台阶段，边被吸收")
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


# ---------- 阶段前置闸（控制流统一：平台不变量） ----------
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
    "generate_image": "ke_media",
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


def evaluate_stage_precondition(
    tool_name: str, state: Dict[str, Any], skill: str,
) -> Optional[str]:
    """阶段前置闸判定（platform.stage_precondition，GATE_RULES 登记）。

    返回拒收文案（结构化拒因，回喂模型）；None = 放行。
    事实源全复用既有单一源：阶段表/依赖图/客观探针（sidecar 声明，
    未声明前置回落线性链，与 3A 调度同构且更保守）。无 Skill 激活不启用。
    """
    if not skill:
        return None
    table = stage_table(skill)
    if not table:
        return None
    stage = tool_stage_of(tool_name, table)
    if not stage:
        return None
    deps = _effective_stage_deps(skill, table).get(stage, [])
    missing = [d for d in deps if not stage_done(d, state, skill)]
    if not missing:
        return None
    names = "、".join(f"「{_STAGE_TITLES.get(d, d)}」" for d in missing)
    return (
        f"阶段前置闸拦截：{names} 尚未完成，当前不得调用 {tool_name}。"
        "请先完成前置阶段（流程顺序由 Skill 声明机械强制，非建议）。"
    )


def next_batch(
    state: Dict[str, Any], skill: str,
) -> Tuple[List[StageSpec], bool]:
    """拓扑就绪集：返回 (可执行确定性阶段批, 是否交接创作型阶段)。

    就绪 = 自身未完成且前置阶段全部 stage_done；同批可并行。
    有确定性阶段就绪时优先执行；仅创作型就绪时交接模型循环。
    无 dependencies 声明 → 线性回落（第一个未完成阶段决定，零行为变更）。
    """
    table = stage_table(skill)
    done = {s.key: stage_done(s.key, state, skill) for s in table}
    if all(done.values()):
        return [], False
    deps = _stage_dependencies(skill)
    if not deps:
        for spec in table:
            if not done[spec.key]:
                if not spec.deterministic:
                    return [], True
                return [spec], False
        return [], False
    ready: List[StageSpec] = []
    handoff = False
    for spec in table:
        if done[spec.key]:
            continue
        if all(done.get(p, False) for p in deps.get(spec.key, ())):
            if spec.deterministic:
                ready.append(spec)
            else:
                handoff = True
    if ready:
        return ready, False
    return [], handoff


@dataclass
class OrchestratorOutcome:
    kind: str  # script_pending / script_ack / spec_pending（批 12 后仅兜底卡三类）
    message: str = ""
    options: List[Dict[str, str]] = None
    results: List[Any] = None


async def gate_precheck(
    state_manager: Any, skill: str, user_message: Any = "",
) -> Optional[OrchestratorOutcome]:
    """闸预检（Rule2 v6：runtime 闸节点；编排器定义层 + 兜底卡装配）。

    只产出两类机械兜底卡，**永不执行阶段、永不抢先对话**：
    - 原料闸：需剧本 Skill 剧本缺失且未豁免 → 提醒卡/上传回执；
    - 规格闸：spec 阶段就绪且未完成 → spec_pending（向导收集卡）。
    其余一律 None = 交接模型循环（模型持主动权，按注入的流程清单
    调用执行器/ workflow_pause；顺序由 stage_precondition 闸否决越阶）。
    """
    state = state_manager.state_dict
    msg = str(user_message or "")
    table = stage_table(skill)
    # 原料闸：analysis 在表且未完成时才判定
    if any(s.key == "analysis" and not stage_done("analysis", state, skill) for s in table):
        inter = state.setdefault("interaction", {})
        if (
            registry.script_required_active(skill)
            and not prompt_gates.script_present(state)
            and not inter.get("script_waived")
        ):
            if prompt_gates.script_waive_intent(msg):
                inter["script_waived"] = True
                state_manager.save_debounced()
                return None  # 豁免：交接模型循环
            if prompt_gates.script_upload_ack_intent(msg):
                return OrchestratorOutcome(
                    "script_ack", message=prompt_gates.SCRIPT_UPLOAD_ACK)
            card_msg, card_opts = prompt_gates.script_remind_card()
            return OrchestratorOutcome(
                "script_pending", message=card_msg, options=card_opts)
    # 规格闸：spec 阶段就绪且未完成 → 向导收集卡（不执行、不抢先）
    batch, _handoff = next_batch(state, skill)
    if any(s.key == "spec" for s in batch):
        return OrchestratorOutcome("spec_pending")
    return None
