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

2026-09-16 R4 批（已翻案，见下）：故事板三阶段曾翻回主代理直做。

2026-09-19 主代理纯编排批（用户裁决，翻案 R4 + 2026-09-18「工具要给全」）：
主代理改为**纯编排角色**——结构性缺少各执行阶段的专业写入工具（MAIN_AGENT_DENY），
只能经 run_subagent 委派触达；除媒体生成（image_generate/generate_video，花钱生成
确认闸只能主线程发行）外，全部生产阶段委派子代理。委派集恢复故事板三阶段
（key_elements/shots/audio）+ 素材分析 + 提示词撰写（提示词撰写与媒体生成是两个
独立顺序阶段，非包含关系，故提示词撰写属委派集）。子代理 read_skill 保持 deny
（STAGE_TOOL_DENY_EXTRA）：子代理只能用注入的对应 Skill 分区 + 共享项目状态 +
明确传递的资源，不能自由读其他章节（规则按职责隔离、项目状态按需共享）。RC1
（4444 取证：stage 隔离使 shot 规则不可达）由「按正确 stage 粒度委派 + 精准章节
注入 + 跨阶段数据经共享状态可见」化解，非靠解禁 read_skill。
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

# stage 模式额外 deny（2026-09-21 批0 扩充，事故 2222/Q5）：
#   read_skill —— 该阶段章节已由系统全文注入，结构上关闭跨阶段预读通道
#     （分镜子代理物理看不到其它章节，等效 Flova 隔离）；
#   storyboard_confirm_draft / storyboard_media_to_chat —— 两者都是**面向用户的
#     交互动作**（把草稿标记「已确认」= 用户裁决；把媒体插入用户输入框 = 给用户
#     过目），没有任何可委派阶段声明它，故带 stage 的子代理一律不持有。
#     装载期校验（见下）保证它们永不被任何 _STAGE_TOOLS 阶段认领——若将来某阶段
#     真要它，fail-loud 会要求先从本集移出，不会静默失效。
STAGE_TOOL_DENY_EXTRA: FrozenSet[str] = frozenset({
    "read_skill", "storyboard_confirm_draft", "storyboard_media_to_chat",
})

# 阶段执行器：委派可选的生产阶段枚举（与 registry.CAPABILITY_TOOL_STAGES 键
# 同名）。媒体生成（image_generate/generate_video）花钱确认闸只能主线程发行，
# 留主代理不进本枚举；时间线组装（video_assembler）本项目暂无对应工具，待工具
# 落地再登记（fail-loud 校验要求 _STAGE_TOOLS 非空）。
# 2026-09-19 主代理纯编排批：恢复故事板三阶段（key_elements/shots/audio），
# 委派集 = 素材分析 + 故事板设计三阶段 + 提示词撰写。
PIPELINE_STAGE_KINDS: FrozenSet[str] = frozenset({
    "script_analyze",
    "storyboard_key_elements", "storyboard_shots", "storyboard_audio",
    "write_media_prompt",
})

# 阶段执行器必备工具集（正向设计单一事实源）：每个可委派阶段的子代理在其
# 上下文内调用的生产工具。供 stage_tools() 查询 + 装载期 fail-loud 校验。
# 注意：本表含读工具（read_uploaded_doc），故主代理结构性 deny 集
# （MAIN_AGENT_DENY）≠ 本表并集——主代理保留读工具，只锁写入/执行工具。
_STAGE_TOOLS: Dict[str, FrozenSet[str]] = {
    "script_analyze": frozenset({"read_uploaded_doc", "script_analysis_report"}),
    "storyboard_key_elements": frozenset(
        {"storyboard_create_group", "storyboard_delete_group"}),
    "storyboard_shots": frozenset(
        {"storyboard_create_group", "storyboard_delete_group",
         "storyboard_add_draft", "storyboard_patch_draft"}),
    "storyboard_audio": frozenset(
        {"storyboard_create_group", "storyboard_delete_group",
         "storyboard_add_draft"}),
    "write_media_prompt": frozenset(
        {"storyboard_add_draft", "storyboard_patch_draft"}),
}

# 主代理结构性 deny 集（2026-09-19 主代理纯编排批，翻案 2026-09-18「工具要给全」）：
# 主代理是纯编排角色，物理上缺少各执行阶段的专业写入工具——这些工具只能经
# run_subagent 委派给子代理触达（planner._compute_excluded_tools 在 depth==0 时
# 并入本集；one visibility = one permission：schema 不可见 + 误调拒执行，
# turn_excluded.md 渲染「经委派执行对应阶段」路由提示）。范围 = 素材分析产出 +
# 故事板结构写入 + 提示词草稿写入（提示词撰写与故事板设计共用 add/patch_draft）。
# 媒体生成（image_generate/generate_video）与读工具/文档/确认/编排工具不在本集
# （主代理保留：理解需求/读资料/维护文档/处理确认节点/编排/花钱生成带确认闸）。
MAIN_AGENT_DENY: FrozenSet[str] = frozenset({
    "script_analysis_report",
    "storyboard_create_group", "storyboard_delete_group",
    "storyboard_add_draft", "storyboard_patch_draft",
})

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

# MAIN_AGENT_DENY 一致性：每个主代理 deny 工具必须被某个可委派阶段使用，否则
# 主代理锁掉后无子代理阶段可用 = 结构性不可达（配置漂移在 import 期即报错）。
_all_stage_tools: FrozenSet[str] = frozenset().union(*_STAGE_TOOLS.values())
_orphan_deny = MAIN_AGENT_DENY - _all_stage_tools
if _orphan_deny:
    raise ValueError(
        f"[subagent] MAIN_AGENT_DENY 漂移：{sorted(_orphan_deny)} 不属任何 "
        f"_STAGE_TOOLS 阶段工具集（主代理锁掉后不可达，fail-loud）")
del _all_stage_tools, _orphan_deny

# MAIN_AGENT_DENY 之外还有一组「带 stage 一律 deny」的交互工具
# （STAGE_TOOL_DENY_EXTRA 非 read_skill 部分）：它们面向用户动作，任何可委派
# 阶段都不该持有。若将来某阶段真需要（把它写进 _STAGE_TOOLS），本校验在装载期
# 报错，逼改动者显式做出取舍——不会出现「阶段声明了却拿不到」的静默失效。
_stage_owned_extra = frozenset(
    t for t in STAGE_TOOL_DENY_EXTRA
    if any(t in tools for tools in _STAGE_TOOLS.values()))
if _stage_owned_extra:
    raise ValueError(
        f"[subagent] STAGE_TOOL_DENY_EXTRA 漂移：{sorted(_stage_owned_extra)} "
        f"已被某可委派阶段声明为必备工具，却同时在 stage deny 集内（自相矛盾，"
        f"fail-loud）——请先从 STAGE_TOOL_DENY_EXTRA 移出再声明")
del _stage_owned_extra


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
    带 stage 追加 read_skill（章节已注入，断跨阶段预读）+ **本阶段未声明的
    委派专属写入工具**（2026-09-21 批0，事故 2222/Q5）。子级可见面 =
    主代理面 − 本集（planner._compute_excluded_tools 据此裁剪）。

    第三项的依据（one visibility = one permission）：MAIN_AGENT_DENY 里的工具
    主代理结构性不可见，只存在于委派路径上——故只有在自己 `_STAGE_TOOLS` 里
    声明它的那个阶段拿得到，其余阶段物理不可达。改前实测（2222）：key_elements
    子代理可见 18/23 个工具，add_draft/patch_draft/script_analysis_report 全在，
    与注入章节的散文约束冲突，模型被迫自行裁决「算不算越权」并最终越界。
    修的是「散文宣称了阶段授权、代码没实施」这处不一致，不是新增散文禁令（P2）。
    """
    resolved = resolve_stage(stage)
    if not resolved:
        return SUBAGENT_TOOL_DENY
    return (SUBAGENT_TOOL_DENY | STAGE_TOOL_DENY_EXTRA
            | (MAIN_AGENT_DENY - stage_tools(resolved)))


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
