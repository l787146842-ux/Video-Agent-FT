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
"""
from typing import FrozenSet
import hashlib

from src.video_agent.utils.prompts import load_prompt_section

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


def resolve_subagent_kind(kind: str = ""):
    """兼容旧调用签名：通用形态下恒返回单一类型 "general"（忽略传入 kind）。

    委派本身已经过同一闸机链，类型只是能力面预设——不再有分类型白名单。"""
    return SUBAGENT_KIND_GENERAL


def whitelist_for_kind(kind: str = "") -> FrozenSet[str]:
    """子级工具白名单（唯一，不含 run_subagent / 花钱生成 / workflow_pause）。"""
    return SUBAGENT_TOOL_WHITELIST


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


def build_subagent_task(task: str, kind: str = SUBAGENT_KIND_GENERAL) -> str:
    """子级任务文本 = 固定权限范围声明 + 待建清单（幂等锚）+ 本次委派任务。

    通用形态：不再前置分类型职责块；子级该做什么全凭任务书说明（与 dsh 一致）。
    待建清单含幂等锚（task_id hash），重复委派同一任务时子级可跳过已做项。
    """
    clean = str(task or "").strip()
    ctx = subagent_delegation_context()
    header = ""
    if ctx:
        header += f"{ctx}\n\n"
    # 幂等锚：任务内容 hash 作为唯一标识，同 ID 工作已做完则跳过
    task_id = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]
    header += f"===== 待建清单（task_id: {task_id}）=====\n按任务书目标一次性完成以下所有工作项。幂等锚：同一 task_id 的工作项如果已存在于工作台，直接跳过。\n\n"
    return f"{header}===== 本次委派任务 =====\n{clean}"
