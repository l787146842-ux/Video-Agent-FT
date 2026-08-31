# *- coding: utf-8 -*-
"""状态驱动管线知识源 + 闸预检（定义层承自本模块，账本/裁判数据归 workflow_runtime）。

本模块提供阶段表/依赖图/客观探针作为「法条」，供 stage_precondition 闸
否决越阶、done-闸判定完成、轮始闸预检装配原料闸/规格闸兜底卡
（层 9 由代码执行不依赖模型自觉；行动发起永远归模型）。

本模块是纯数据层（阶段表/探针/兜底卡装配），无任何编排权
（不发起行动、不驱动轮次）。
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.core import gates_cards
from src.video_agent.core import prompt_gates
from src.video_agent.core import workflow_runtime
from src.video_agent.skill_runtime import registry
from src.video_agent.state.models import (
    ASSEMBLY_PLAN_DOC_NAME, CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS,
)

# 粘性豁免（script_waived 模式泛化，批 B）：同类确认批过一次不再问。
# 确认类别 → interaction 豁免旗标名；写入统一经 workflow_runtime.reduce_interaction
# （interaction 旗标唯一写入点），gate_precheck 判定短路只读本表；
# 与 ADR-0004 条款 3 自主性档位概念衔接（用户显式确认授予的豁免留痕）。
CONFIRMATION_WAIVER_FLAGS: Dict[str, str] = {
    "script": "script_waived",
}


def waive_confirmation_category(state_manager: Any, category: str) -> bool:
    """按确认类别记账豁免（同类确认批过一次不再问）；未知类别返回 False。"""
    flag = CONFIRMATION_WAIVER_FLAGS.get(category)
    if not flag:
        return False
    workflow_runtime.reduce_interaction(state_manager, set_flags={flag: True})
    return True


def confirmation_category_waived(state: Dict[str, Any], category: str) -> bool:
    """确认类别是否已豁免（只读；豁免旗标名归 CONFIRMATION_WAIVER_FLAGS）。"""
    flag = CONFIRMATION_WAIVER_FLAGS.get(category)
    return bool(flag and ((state or {}).get("interaction") or {}).get(flag))


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


def _stage_done_decl(skill: str, key: str) -> str:
    """frontmatter 阶段完成条件声明（flow.stages.<阶段键>.done，可选，任意阶段同构）：
    当前支持 "document:<文档名>"；未声明返空串（回落平台客观探针）。"""
    if not skill:
        return ""
    manifest = registry.skill_manifest_of(skill) or {}
    stages = ((manifest.get("flow") or {}).get("stages") or {})
    # 数组形态 = workflow 结构声明，不属阶段覆盖通道
    if not isinstance(stages, dict):
        return ""
    return str((stages.get(key) or {}).get("done") or "").strip()


def stage_done(key: str, state: Dict[str, Any], skill: str = "") -> bool:
    """阶段完成度客观探针（只认状态事实，认不出=未完成；fail-closed）。

    frontmatter 声明探针通道（任意阶段同构）：flow.stages.<key>.done 声明
    优先（document:<文档名>），未声明回落各阶段平台客观探针。"""
    decl = _stage_done_decl(skill, key)
    if decl.startswith("document:"):
        return _has_document_named(state, decl[len("document:"):].strip())
    if key == "analysis":
        return bool((state.get("analysis") or {}).get("summary"))
    if key == "spec":
        return prompt_gates.has_spec_document(state)
    ke = state.get(CAT_KEY_ELEMENTS) or []
    shots = state.get(CAT_SHOTS) or []
    audio = state.get(CAT_AUDIO_ITEMS) or []
    if key == "structure":
        return bool(ke) and bool(shots) and bool(audio)
    # 节点级结构探针：workflow_contract 单节点
    # 完成判定用。运行时内部键——frontmatter 声明白名单仍锁
    # CANONICAL_STAGE_KEYS，这三键不可经 stages.<key>.done 声明覆盖。
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
    """平台规范阶段表 + frontmatter 覆盖（skip 裁剪 / 同批执行器替换）。

    skill 感知裁剪：未声明 spec_wizard 的 Skill 无规格阶段；
    无 video_assembler 执行器章节的 Skill 无组装阶段（除非 frontmatter 显式覆盖）。"""
    manifest = registry.skill_manifest_of(skill) or {}
    overrides = ((manifest.get("flow") or {}).get("stages") or {})
    # 数组形态 = workflow 结构声明（compile_definition 消费），
    # 阶段裁剪通道只消费 dict 覆盖声明，数组视为零覆盖
    if not isinstance(overrides, dict):
        overrides = {}
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


def _spec_stage_pending(state: Dict[str, Any], skill: str) -> bool:
    """规格闸就绪探针。

    就绪 = spec 自身未完成且前置阶段全部 stage_done；无 dependencies
    声明时线性回落（spec 为第一个未完成阶段才就绪）。
    探针只读客观事实、不发起行动。
    """
    table = stage_table(skill)
    if not any(s.key == "spec" for s in table):
        return False
    if stage_done("spec", state, skill):
        return False
    deps = _stage_dependencies(skill)
    if not deps:
        # 线性回落：仅当 spec 是第一个未完成阶段（且为确定性阶段）
        for spec in table:
            if not stage_done(spec.key, state, skill):
                return spec.key == "spec"
        return False
    return all(stage_done(d, state, skill) for d in deps.get("spec", []))


@dataclass
class OrchestratorOutcome:
    kind: str  # script_pending / script_ack / spec_pending
    message: str = ""
    options: List[Dict[str, str]] = None
    results: List[Any] = None


async def gate_precheck(
    state_manager: Any, skill: str, user_message: Any = "",
) -> Optional[OrchestratorOutcome]:
    """闸预检（Rule2 v6：runtime 闸节点；编排器定义层 + 兜底卡装配）。

    产出两类机械兜底卡，**永不执行阶段、永不抢先对话**：
    - 原料闸：需剧本 Skill 剧本缺失且未豁免 → 提醒卡/上传回执；
    - 规格闸：spec 阶段就绪且未完成 → spec_pending（向导收集卡）。
    其余一律 None = 交接模型循环（模型持主动权，按注入的流程清单
    调用执行器/ workflow_pause；顺序由 stage_precondition 闸否决越阶）。
    """
    state = state_manager.state_dict
    msg = str(user_message or "")
    table = stage_table(skill)
    # 原料闸：analysis 在表且未完成时才判定（C1b 裁决 2026-08-31：
    # v3 requires_inputs 声明轴退役，原料闸回落 v2 script_required 单路）
    if any(s.key == "analysis" and not stage_done("analysis", state, skill) for s in table):
        if (
            registry.script_required_active(skill)
            and not prompt_gates.script_present(state)
            and not confirmation_category_waived(state, "script")
        ):
            if prompt_gates.script_waive_intent(msg):
                waive_confirmation_category(state_manager, "script")
                return None  # 豁免：交接模型循环
            if prompt_gates.script_upload_ack_intent(msg):
                return OrchestratorOutcome(
                    "script_ack", message=prompt_gates.SCRIPT_UPLOAD_ACK)
            card_msg, card_opts = prompt_gates.script_remind_card()
            return OrchestratorOutcome(
                "script_pending", message=card_msg, options=card_opts)
    # 规格闸：spec 阶段就绪且未完成 → 向导收集卡（不执行、不抢先）
    if _spec_stage_pending(state, skill):
        return OrchestratorOutcome("spec_pending")
    return None


# step_done_conditions 声明探针注入下一步机械派生（gates_cards 被
# prompt_gates 导入，反向顶层 import 成环，故用注册钩子解耦）。
gates_cards.register_step_done_probe(step_done_probe)
