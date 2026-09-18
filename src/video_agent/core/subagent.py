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

2026-09-16 R4 批（用户裁决，对齐 flova）：故事板三阶段（key_elements/shots/
audio）从委派子代理翻回**主代理直做**——flova 唯一重大不一致=故事板设计在
主代理（7 份转录一致）；4444 取证证明 stage 隔离委派使 shot 规则章节结构性
不可达（RC1，留痕见 CHANGELOG §二 2026-09-16 R1-R6 批）。委派集只保留
script_analyze / write_media_prompt；同批 read_skill 自主代理生产轮解禁
（主代理设计故事板前须 read_skill 读全对应章节并消化进产出散文）。
"""
from typing import Dict, FrozenSet

from src.video_agent.utils.prompts import load_prompt_section
# 阶段标注取展示标签（顶层导入：core→skill_runtime 无环，prompt_builder 同构先例）
from src.video_agent.skill_runtime.registry import (
    CAPABILITY_TOOL_STAGES, STAGE_LABELS,
)

# 模型可见的子代理工具名（无 provider_kind，可在 fc_tool_runner 按名拦截，
# 同 workflow_pause 一类控制流伪工具；不受 check_fc_tool_name_literals 约束）。
SUBAGENT_TOOL_NAME = "run_subagent"

# 子级委派深度上限（B1：只允许一层）。
SUBAGENT_MAX_DEPTH = 1

# K6 批（2026-09-16 对齐 dsh structured.ts）：子代理专属工具集——完工打卡
# structured_output 仅子代理（depth≥1）可见；主代理面经
# planner._compute_excluded_tools 裁剪，且 prompt_builder 的 UNAVAILABLE 段
# 不渲染本集（主代理不感知打卡工具存在）。
CHILD_ONLY_TOOLS: FrozenSet[str] = frozenset({"structured_output"})

# 缺省类型名（历史兼容占位；通用形态下只有一个类型）。
SUBAGENT_KIND_GENERAL = "general"

# 子级工具面（2026-09-15 1111 批，对齐 dsh `applyChildComposition`：先 join 父
# preset 再 `tools.restrict({allow,deny})`，缺省即继承父面）：子代理**继承主代理
# 整面工具**，仅以 deny 集收口（inherit ∩ ¬deny），不再维护硬编码 allowlist。
# 硬编码 allowlist 会漏授阶段落点工具——1111 实证：script_analyze 子代理拿不到
# script_analysis_report（分析结论无法提交）。deny 四条与类型无关的硬约束：
#   run_subagent —— 结构防递归（子级看不到也无法调用）；
#   image_generate / generate_video —— 花钱生成留主线程受确认闸管；
#   workflow_pause —— 子级不向用户发起确认（审批=never）。
SUBAGENT_TOOL_DENY: FrozenSet[str] = frozenset({
    "run_subagent", "image_generate", "generate_video", "workflow_pause",
})

# stage 模式额外 deny：read_skill——该阶段章节已由系统全文注入，
# 结构上关闭跨阶段预读通道（分镜子代理物理看不到其它章节，等效 Flova 隔离）。
STAGE_TOOL_DENY_EXTRA: FrozenSet[str] = frozenset({"read_skill"})

# 阶段执行器（2026-09-15 试点、同日铺满）：委派可选的生产阶段枚举（与
# registry.CAPABILITY_TOOL_STAGES 键同名）。生成/组装类阶段（image_generate/
# generate_video/audio_generate/video_assembler）确认闸留主线程，不进本枚举。
# 2026-09-16 R4 批（用户裁决，对齐 flova）：故事板三阶段翻回主代理直做
# （flova 唯一重大不一致=故事板设计在主代理；4444 取证证明 stage 隔离委派
# 使 shot 规则章节结构性不可达），委派集只保留 script_analyze /
# write_media_prompt；章节映射与展示标签仍留 registry 供 read_skill/telemetry。
PIPELINE_STAGE_KINDS: FrozenSet[str] = frozenset({
    "script_analyze", "write_media_prompt",
})

# 两桶分工（正向设计单一事实源）：可委派阶段 → 阶段执行器在其上下文内调用的
# 生产工具（主代理面在顶级生产轮裁掉这些，只能经委派触达）；主线程阶段工具
# （document_write/workflow_pause/read_state_group/image_generate/generate_video）
# 不在此表，主代理直调。本表是「主代理面裁剪」与「阶段执行器必备工具」的唯一源。
_STAGE_TOOLS: Dict[str, FrozenSet[str]] = {
    "script_analyze": frozenset({"read_uploaded_doc", "script_analysis_report"}),
    "write_media_prompt": frozenset(
        {"storyboard_add_draft", "storyboard_patch_draft"}),
}

# 主代理生产轮工具面裁剪（PRODUCTION_MAIN_PRUNE / _MAIN_READBACK_DENY）已退役
# （2026-09-18 用户裁决「工具要给全」，对齐 flova 平台不剥夺主代理读原文能力）：
# 主代理持全量生产工具面，可委派阶段（script_analyze/write_media_prompt）仍由
# 协议引导委派（skill_runtime「可委派阶段整段委派」），委派不再是结构性强制。
# _STAGE_TOOLS 保留——委派子代理的阶段落点工具集仍由它定义。

# 装载期一致性校验（fail-loud，dsh tool-subagent L316-350）：阶段枚举必须同时
# 具备章节映射（CAPABILITY_TOOL_STAGES）与展示标签（STAGE_LABELS）与工具集
# （_STAGE_TOOLS），配置漂移在 import 期即报错，不带到运行时静默丢章节注入。
for _stage in PIPELINE_STAGE_KINDS:
    if _stage not in CAPABILITY_TOOL_STAGES:
        raise ValueError(
            f"[subagent] PIPELINE_STAGE_KINDS 漂移：阶段 {_stage!r} 缺 "
            f"registry.CAPABILITY_TOOL_STAGES 章节映射（fail-loud）")
    if _stage not in STAGE_LABELS:
        raise ValueError(
            f"[subagent] PIPELINE_STAGE_KINDS 漂移：阶段 {_stage!r} 缺 "
            f"registry.STAGE_LABELS 展示标签（fail-loud）")
    if _stage not in _STAGE_TOOLS:
        raise ValueError(
            f"[subagent] PIPELINE_STAGE_KINDS 漂移：阶段 {_stage!r} 缺 "
            f"_STAGE_TOOLS 工具集（fail-loud）")
del _stage


def stage_tools(stage: str = "") -> FrozenSet[str]:
    """阶段执行器必备工具集（空/未知阶段返回空集）。"""
    return _STAGE_TOOLS.get(resolve_stage(stage), frozenset())


def resolve_subagent_kind(kind: str = ""):
    """兼容旧调用签名：通用形态下恒返回单一类型 "general"（忽略传入 kind）。

    委派本身已经过同一闸机链，类型只是能力面预设——不再有分类型白名单。"""
    return SUBAGENT_KIND_GENERAL


def resolve_stage(stage: str = "") -> str:
    """阶段执行器 stage 归一化校验：试点枚举内原样返回；
    未知/空值回落 ""（= 通用形态，全现状不动，不阻断委派）。"""
    s = str(stage or "").strip()
    return s if s in PIPELINE_STAGE_KINDS else ""


def child_deny_set(stage: str = "") -> FrozenSet[str]:
    """子级 deny 集（dsh inherit∩restrict 的 restrict 面）：通用 = 四条硬约束；
    带 stage 追加 read_skill（章节已注入，断跨阶段预读）。子级可见面 =
    主代理面 − 本集（planner._compute_excluded_tools 据此裁剪）。"""
    return SUBAGENT_TOOL_DENY | (
        STAGE_TOOL_DENY_EXTRA if resolve_stage(stage) else frozenset())


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
    """子级任务文本 = 固定权限范围声明 + 阶段标注（带 stage 时）+ 一句目标。

    2026-09-15 1111 批（对齐 flova 精简）：任务书**只承载目标**。范围/源文档/
    产出规范一律不复述——工作台状态经读工具按需获取，源文档/Skill 自己用
    读工具取，系统注入的阶段章节是方法参考（措辞唯一源 = subagent.md
    DELEGATION_CONTEXT；2026-09-17 裁决：产出形态归 Skill 章节唯一表述源，
    平台引导子句「消化进产出/不照抄小标题」退役）；父复述只会污染
    子任务 + 双份事实源 + 烧 token。
    通用形态：不再前置分类型职责块；阶段形态：只加一行事实性阶段标注
    （取 registry.STAGE_LABELS，不带解释性括号——2026-09-16 P1-D/R3：括号内
    「章节即产出规范的全部依据」曾诱导子代理照抄章节骨架），章节正文由
    planner 装配层精准注入。
    """
    clean = str(task or "").strip()
    ctx = subagent_delegation_context()
    header = ""
    if ctx:
        header += f"{ctx}\n\n"
    resolved = resolve_stage(stage)
    if resolved:
        label = STAGE_LABELS.get(resolved, resolved)
        header += f"本次委派阶段：{label}\n\n"
    return f"{header}===== 本次委派目标 =====\n{clean}"
