# *- coding: utf-8 -*-
"""状态驱动管线知识源 + 闸预检（Rule2 主体回归：定义层承自本模块，账本/裁判数据归 workflow_runtime）。

本模块提供阶段表/依赖图/客观探针作为「法条」，供 stage_precondition 闸
否决越阶、done-闸判定完成、轮始闸预检装配原料闸/规格闸兜底卡
（层 9 由代码执行不依赖模型自觉；行动发起永远归模型，ADR-0004）。
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.core import gates_cards
from src.video_agent.core import gates_inputs
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
    return str(
        (((manifest.get("flow") or {}).get("stages") or {}).get(key) or {}).get("done")
        or ""
    ).strip()


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
    # 节点级结构探针（整改批 3.1「账本无自报」）：workflow_contract 单节点
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
    探针只记录客观完成度，不发起行动（ADR-0004）。"""
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
#
# 任务#5：step_stages/dependencies 声明通道废除（正文 planner 是唯一流程源），
def _step_to_stage(
    step_no: Any, manifest: Optional[Dict[str, Any]], table: List[StageSpec],
) -> Optional[str]:
    """frontmatter step 号 → 平台规范阶段：① step_stages 显式声明（权威）；
    ② stage_executors 执行器交集。
    （描述关键词启发式回落与映射来源遥测已随整改批 3.5 退役：生产注册期
    fail-hard 禁声明 steps/dependencies，启发式分支生产不可达，且其
    「零误判」遥测只计数不落盘、无可核查证据——按折旧规程下账；
    显式声明通道保留以兼容内存 manifest 注入的测试同构口径。）"""
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
    事实源全复用既有单一源：阶段表/依赖图/客观探针（frontmatter 声明，
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


def _spec_stage_pending(state: Dict[str, Any], skill: str) -> bool:
    """规格闸就绪探针（原拓扑就绪集调度函数的唯一存活消费语义，任务#27 退役后迁入）。

    就绪 = spec 自身未完成且前置阶段全部 stage_done；无 dependencies
    声明时线性回落（spec 为第一个未完成阶段才就绪），与原调度函数
    成员判定逐句同构（零行为变更，任务#27 文本轨残留退役批迁入）。
    探针只读客观事实、不发起行动（ADR-0004）；原调度函数的「可执行批/
    交接」语义已随 runtime 直跑机制退役，防复活归
    check_legacy_orchestration 门禁。
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


# 重试引导卡派生（失败账本消费）已随整改批 1.3 删除：账本生产零写入，
# 消费链死路；防复活钉死见 tests/unit/test_dead_code_payoff.py


async def gate_precheck(
    state_manager: Any, skill: str, user_message: Any = "",
) -> Optional[OrchestratorOutcome]:
    """闸预检（Rule2 v6：runtime 闸节点；编排器定义层 + 兜底卡装配）。

    产出两类机械兜底卡，**永不执行阶段、永不抢先对话**：
    - 原料闸：需剧本 Skill 剧本缺失且未豁免 → 提醒卡/上传回执；
    - 规格闸：spec 阶段就绪且未完成 → spec_pending（向导收集卡）。
    （重试引导卡派生已随整改批 1.3 删除：失败账本死链清偿。）
    其余一律 None = 交接模型循环（模型持主动权，按注入的流程清单
    调用执行器/ workflow_pause；顺序由 stage_precondition 闸否决越阶）。
    """
    state = state_manager.state_dict
    msg = str(user_message or "")
    table = stage_table(skill)
    # 原料闸：analysis 在表且未完成时才判定
    if any(s.key == "analysis" and not stage_done("analysis", state, skill) for s in table):
        inter = state.setdefault("interaction", {})
        reqs = registry.skill_requires_inputs(skill)
        if reqs:
            # v3 原料闸（任务#35 B2）：requires_inputs 声明优先，任一 required
            # 项客观未满足即拦截；与 v2 script_required 两路不叠加（声明了
            # v3 清单就不再重复走旧判定，未声明才回落下方旧分支）。
            missing = gates_inputs.missing_required_inputs(state, skill)
            if inter.get("script_waived"):
                missing = [m for m in missing if m["type"] != "script"]
            waived_now = False
            if any(m["type"] == "script" for m in missing):
                if prompt_gates.script_waive_intent(msg):
                    inter["script_waived"] = True
                    state_manager.save_debounced()
                    waived_now = True
                    missing = [m for m in missing if m["type"] != "script"]
                elif prompt_gates.script_upload_ack_intent(msg):
                    return OrchestratorOutcome(
                        "script_ack", message=prompt_gates.SCRIPT_UPLOAD_ACK)
            if missing:
                if all(m["type"] == "script" for m in missing):
                    card_msg, card_opts = prompt_gates.script_remind_card()
                else:
                    # 非剧本类/混合缺失：通用提醒文案（无豁免选项）
                    card_msg = gates_inputs.input_remind_message(missing)
                    card_opts = []
                return OrchestratorOutcome(
                    "script_pending", message=card_msg, options=card_opts)
            if waived_now:
                return None  # 本轮豁免：交接模型循环（与 v2 豁免短路同语义）
        elif (
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
    # 重试引导（失败账本消费）已随整改批 1.3 删除（死链清偿）
    # 规格闸：spec 阶段就绪且未完成 → 向导收集卡（不执行、不抢先）
    if _spec_stage_pending(state, skill):
        return OrchestratorOutcome("spec_pending")
    return None


# step_done_conditions 声明探针注入下一步机械派生（gates_cards 被
# prompt_gates 导入，反向顶层 import 成环，故用注册钩子解耦）。
gates_cards.register_step_done_probe(step_done_probe)
