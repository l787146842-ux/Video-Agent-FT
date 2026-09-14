# -*- coding: utf-8 -*-
"""正宗子代理（run_subagent）契约与纯辅助。

对齐业界（Claude Code / qoder / dsh `packages/subagent`）：**模型经 FC 发起、
复用同一 `run_agent_loop`、走同一 `guard_pipeline`、只回摘要**的一次性子级。
**不是** 0818/任务#36 B5 退役的那套机械执行器——它由运行时替模型直跑阶段、
绕闸、另开非-FC 通道，其退役符号已被防复活门禁永久锁（本模块不复活、不引用）。

本模块刻意**不 import planner / agent_loop**（避免 core 内模块环）：只放常量与
纯函数；真正的子级装配在 `planner._launch_subagent`（planner 侧合法持有循环件）。

2026-09-11 批③A（对齐 dsh 通用形态）：具名类型（storyboard_split /
media_prompt_write）退役 → **单一通用子代理**。dsh 只有一个通用 subagent（按
工具面白名单限权，不预设任务种类），委派策略改由主对话的 `subagent` system 段
（见 prompts/planner/subagent.md :: SUBAGENT_POLICY）承载，与业务无关，画布等新
场景无需再加类型。子级仍保留两条与类型无关的硬约束：不含花钱生成、不含
run_subagent（结构防递归）。

2026-09-15 阶段执行器试点批（用户裁决，部分翻案批③A）：对齐 Flova「章节分别
注入对应阶段子执行器」——run_subagent 加可选 `stage`（试点 script_analyze /
storyboard_shots）：带 stage 时系统精准注入该阶段 Skill 章节全文（替代全文
截断）并收紧工具面（去 read_skill，结构上关闭跨阶段预读污染）；不带 stage
的通用委派全现状不动。仍是模型经 FC 自主发起、同一循环同一闸机链，
非机械执行器（FORBIDDEN 符号零触碰）。
"""
from typing import FrozenSet
import hashlib

from src.video_agent.utils.prompts import load_prompt_section
# 阶段标注取展示标签（顶层导入：core→skill_runtime 无环，prompt_builder 同构先例）
from src.video_agent.skill_runtime.registry import STAGE_LABELS

# 模型可见的子代理工具名（无 provider_kind，可在 fc_tool_runner 按名拦截，
# 同 workflow_pause 一类控制流伪工具；不受 check_fc_tool_name_literals 约束）。
SUBAGENT_TOOL_NAME = "run_subagent"

# 子级委派深度上限（B1：只允许一层）。
SUBAGENT_MAX_DEPTH = 1

# 缺省类型名（历史兼容占位；通用形态下只有一个类型）。
SUBAGENT_KIND_GENERAL = "general"

# 子级工具白名单唯一源（通用）：子代理能落账/取读的普通工具面。
# **故意不含花钱生成**（image_generate/generate_video）——生成留主线程受确认闸管；
# **不含 run_subagent**——天然防递归（子级看不到也无法调用）；
# **不含 workflow_pause**——子级不向用户发起确认（审批=never）。
SUBAGENT_TOOL_WHITELIST: FrozenSet[str] = frozenset({
    "storyboard_create_group", "storyboard_add_draft", "storyboard_patch_draft",
    "read_state_group", "read_draft", "read_skill", "read_uploaded_doc",
    "read_project_doc", "view_storyboard_media", "document_write",
})

# 阶段执行器试点（2026-09-15）：委派可选的生产阶段枚举（与
# registry.CAPABILITY_TOOL_STAGES 键同名）；试点只开两个最吃上下文的阶段，
# 铺开批照模子加其余五个（storyboard_key_elements / storyboard_audio /
# write_media_prompt / audio_generate / video_assembler）。
PIPELINE_STAGE_KINDS: FrozenSet[str] = frozenset({
    "script_analyze", "storyboard_shots",
})

# stage 模式工具面 = 通用白名单去 read_skill：该阶段章节已由系统全文注入，
# 结构上关闭跨阶段预读通道（分镜子代理物理看不到 write_media_prompt 章节，
# 等效 Flova 子执行器隔离）；其余工具照旧（落账/读回/写文档）。
STAGE_TOOL_WHITELIST: FrozenSet[str] = SUBAGENT_TOOL_WHITELIST - {"read_skill"}


def resolve_subagent_kind(kind: str = ""):
    """兼容旧调用签名：通用形态下恒返回单一类型 "general"（忽略传入 kind）。

    委派本身已经过同一闸机链，类型只是能力面预设——不再有分类型白名单。"""
    return SUBAGENT_KIND_GENERAL


def resolve_stage(stage: str = "") -> str:
    """阶段执行器 stage 归一化校验：试点枚举内原样返回；
    未知/空值回落 ""（= 通用形态，全现状不动，不阻断委派）。"""
    s = str(stage or "").strip()
    return s if s in PIPELINE_STAGE_KINDS else ""


def whitelist_for_kind(kind: str = "", stage: str = "") -> FrozenSet[str]:
    """子级工具白名单：不带 stage = 通用面（含 read_skill）；
    带 stage = 收紧面（章节已注入，去 read_skill 断跨阶段预读）。
    两面均不含 run_subagent / 花钱生成 / workflow_pause。"""
    return STAGE_TOOL_WHITELIST if resolve_stage(stage) else SUBAGENT_TOOL_WHITELIST


def subagent_kind_block(kind: str = "") -> str:
    """类型职责块（具名类型退役后恒空）：通用子代理不再有分类型 prose。"""
    return ""


class SubagentDepthError(Exception):
    """委派深度超过上限（对齐 dsh `SubagentDepthError`）。"""


def resolve_child_depth(parent_depth: int, max_depth: int = SUBAGENT_MAX_DEPTH) -> int:
    """子级深度 = 父级 + 1，超过 `max_depth` 抛错（对齐 dsh `resolveChildDepth`）。

    纯函数、单调：恢复态由调用方携带真实 parent_depth，不得归零。
    """
    child_depth = int(parent_depth or 0) + 1
    if max_depth is not None and child_depth > int(max_depth):
        raise SubagentDepthError(child_depth, int(max_depth))
    return child_depth


def subagent_delegation_context() -> str:
    """子级固定权限范围声明（唯一源 = prompts/planner/subagent.md DELEGATION_CONTEXT）。"""
    return (load_prompt_section("planner/subagent.md", "DELEGATION_CONTEXT") or "").strip()


def subagent_policy() -> str:
    """主对话委派策略段（唯一源 = prompts/planner/subagent.md SUBAGENT_POLICY）。

    由 prompt_builder._sec_subagent 条件注入（仅当 run_subagent 对模型可见）。"""
    return (load_prompt_section("planner/subagent.md", "SUBAGENT_POLICY") or "").strip()


def build_subagent_task(task: str, kind: str = SUBAGENT_KIND_GENERAL,
                        stage: str = "") -> str:
    """子级任务文本 = 固定权限范围声明 + 阶段标注（带 stage 时）+
    待建清单（幂等锚）+ 本次委派任务。

    通用形态：不再前置分类型职责块；子级该做什么全凭任务书说明（与 dsh 一致）。
    阶段形态（2026-09-15 试点）：只加一行阶段标注（取 registry.STAGE_LABELS，
    不写 prose 花名册——③A 遗产保留），章节正文由 planner 装配层精准注入。
    待建清单含幂等锚（task_id hash），重复委派同一任务时子级可跳过已做项。
    """
    clean = str(task or "").strip()
    ctx = subagent_delegation_context()
    header = ""
    if ctx:
        header += f"{ctx}\n\n"
    resolved = resolve_stage(stage)
    if resolved:
        label = STAGE_LABELS.get(resolved, resolved)
        header += f"本次委派阶段：{label}（系统已注入该阶段 Skill 章节全文，章节即产出规范的全部依据）。\n\n"
    # 幂等锚：任务内容 hash 作为唯一标识，同 ID 工作已做完则跳过
    task_id = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]
    header += f"===== 待建清单（task_id: {task_id}）=====\n按任务书目标一次性完成以下所有工作项。幂等锚：同一 task_id 的工作项如果已存在于工作台，直接跳过。\n\n"
    return f"{header}===== 本次委派任务 =====\n{clean}"
