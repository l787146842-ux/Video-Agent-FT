# -*- coding: utf-8 -*-
"""正宗子代理（run_subagent）契约与纯辅助。

对齐业界（Claude Code / qoder / dsh `packages/subagent`）：**模型经 FC 发起、
复用同一 `run_agent_loop`、走同一 `guard_pipeline`、只回摘要**的一次性子级。
**不是** 0818/任务#36 B5 退役的那套机械执行器——它由运行时替模型直跑阶段、
绕闸、另开非-FC 通道，其退役符号已被防复活门禁永久锁（本模块不复活、不引用）。

本模块刻意**不 import planner / agent_loop**（避免 core 内模块环）：只放常量与
纯函数；真正的子级装配在 `planner._launch_subagent`（planner 侧合法持有循环件）。

子级固定范围声明与类型花名册文案外置 `prompts/planner/subagent.md`
（Rule 6：prose 不进代码）。类型（kind）形态对齐 qoder 具名子代理清单：
每个类型 = 一份工具白名单 + 一段职责块（目标/验收/先取读哪一章）。
"""
from dataclasses import dataclass
from typing import FrozenSet, Mapping

from src.video_agent.utils.prompts import load_prompt_section

# 模型可见的子代理工具名（无 provider_kind，可在 fc_tool_runner 按名拦截，
# 同 workflow_pause 一类控制流伪工具；不受 check_fc_tool_name_literals 约束）。
SUBAGENT_TOOL_NAME = "run_subagent"

# 子级工具白名单唯一源 = 下方 SUBAGENT_KINDS（按类型分派），不另列全集。
# **故意不含花钱生成**（image_generate/generate_video）——生成留主线程受确认闸管；
# **不含 run_subagent**——天然防递归（子级看不到也无法调用）。

# 子级委派深度上限（B1：只允许一层）。
SUBAGENT_MAX_DEPTH = 1

# 缺省类型（兼容旧只传 task 的调用与存量会话）
SUBAGENT_KIND_GENERAL = "general"


@dataclass(frozen=True)
class SubagentKind:
    """一个具名子代理类型：工具白名单 + 职责块分节键（qoder 花名册形态）。"""

    name: str
    whitelist: FrozenSet[str]
    section: str


# 类型白名单（先窄：3 个类型）：一律**不含花钱生成**（image_generate/generate_video）
# 与 **不含 run_subagent**（结构防递归）；子级只能经建组/改卡/写档类工具落账。
SUBAGENT_KINDS: Mapping[str, SubagentKind] = {
    "storyboard_split": SubagentKind(
        "storyboard_split",
        frozenset({
            "storyboard_create_group", "storyboard_add_draft", "storyboard_patch_draft",
            "read_state_group", "read_skill", "read_uploaded_doc", "read_project_doc",
            "document_write",
        }),
        "KIND_STORYBOARD_SPLIT",
    ),
    "media_prompt_write": SubagentKind(
        "media_prompt_write",
        frozenset({
            "storyboard_patch_draft", "read_state_group", "read_draft", "read_skill",
            "read_project_doc", "view_storyboard_media", "document_write",
        }),
        "KIND_MEDIA_PROMPT_WRITE",
    ),
    SUBAGENT_KIND_GENERAL: SubagentKind(
        SUBAGENT_KIND_GENERAL,
        frozenset({
            "storyboard_create_group", "storyboard_add_draft", "storyboard_patch_draft",
            "read_state_group", "read_skill", "read_uploaded_doc", "document_write",
        }),
        "KIND_GENERAL",
    ),
}

# 向后兼容旧名（B1 口径与存量测试）：等价于缺省类型白名单，不另列工具清单。
SUBAGENT_TOOL_WHITELIST: FrozenSet[str] = SUBAGENT_KINDS[
    SUBAGENT_KIND_GENERAL].whitelist


def resolve_subagent_kind(kind: str) -> SubagentKind:
    """按名取类型；未知名/空值回落缺省类型（不拒委派：类型只是能力面预设，
    委派本身已经过同一闸机链，不因拼写差异丢掉整轮工作）。"""
    key = str(kind or "").strip().lower()
    return SUBAGENT_KINDS.get(key) or SUBAGENT_KINDS[SUBAGENT_KIND_GENERAL]


def whitelist_for_kind(kind: str) -> FrozenSet[str]:
    """类型对应的工具白名单（任何类型都不含 run_subagent 与花钱生成）。"""
    return resolve_subagent_kind(kind).whitelist


def subagent_kind_block(kind: str) -> str:
    """类型职责块（目标/验收/取读要求，唯一源 = prompts/planner/subagent.md）。"""
    return (load_prompt_section("planner/subagent.md", resolve_subagent_kind(kind).section)
            or "").strip()


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


def build_subagent_task(task: str, kind: str = SUBAGENT_KIND_GENERAL) -> str:
    """子级任务文本 = 类型职责块 + 固定权限范围声明 + 本次委派任务。

    职责块前置使子级一开始就知道“我是哪类子代理、验收标准是什么”，
    不需回到主对话上下文去推（子级看不到主对话）。"""
    clean = str(task or "").strip()
    resolved = resolve_subagent_kind(kind)
    kind_block = subagent_kind_block(resolved.name)
    ctx = subagent_delegation_context()
    header = ""
    if kind_block:
        header += f"【子代理类型：{resolved.name}】\n{kind_block}\n\n"
    if ctx:
        header += f"{ctx}\n\n"
    return f"{header}===== 本次委派任务 =====\n{clean}"
