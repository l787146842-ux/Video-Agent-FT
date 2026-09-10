# -*- coding: utf-8 -*-
"""正宗子代理（run_subagent）契约与纯辅助。

对齐业界（Claude Code / qoder / dsh `packages/subagent`）：**模型经 FC 发起、
复用同一 `run_agent_loop`、走同一 `guard_pipeline`、只回摘要**的一次性子级。
**不是** 0818/任务#36 B5 退役的那套机械执行器——它由运行时替模型直跑阶段、
绕闸、另开非-FC 通道，其退役符号已被防复活门禁永久锁（本模块不复活、不引用）。

本模块刻意**不 import planner / agent_loop**（避免 core 内模块环）：只放常量与
纯函数；真正的子级装配在 `planner._launch_subagent`（planner 侧合法持有循环件）。

子级固定范围声明文案外置 `prompts/planner/subagent.md`（Rule 6：prose 不进代码）。
"""
from typing import FrozenSet

from src.video_agent.utils.prompts import load_prompt_section

# 模型可见的子代理工具名（无 provider_kind，可在 fc_tool_runner 按名拦截，
# 同 workflow_pause 一类控制流伪工具；不受 check_fc_tool_name_literals 约束）。
SUBAGENT_TOOL_NAME = "run_subagent"

# 子级工具白名单（B1 先窄）：只读 + 故事板结构写入 + 文档写入。
# **故意不含花钱生成**（image_generate/generate_video）——生成留主线程受确认闸管；
# **不含 run_subagent**——天然防递归（子级看不到也无法调用）。
SUBAGENT_TOOL_WHITELIST: FrozenSet[str] = frozenset({
    "storyboard_create_group",
    "storyboard_add_draft",
    "storyboard_patch_draft",
    "read_state_group",
    "read_skill",
    "read_uploaded_doc",
    "document_write",
})

# 子级委派深度上限（B1：只允许一层）。
SUBAGENT_MAX_DEPTH = 1


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


def build_subagent_task(task: str) -> str:
    """把固定范围声明前置进子级任务文本（不改系统提示装配路径）。"""
    clean = str(task or "").strip()
    ctx = subagent_delegation_context()
    header = f"{ctx}\n\n" if ctx else ""
    return f"{header}===== 本次委派任务 =====\n{clean}"
