# -*- coding: utf-8 -*-
"""委派深度上下文（跨切面原语下沉层）。

为什么需要它：工具层（`tools/*`）拿不到 `PlannerContext`——`BaseTool.aexecute`
只收入参模型，`ToolManager.invoke_tool` 也只有 name+kwargs，`fc_tool_runner`
不带执行上下文进工具。但**少数工具必须知道「我是在主代理还是子代理里跑」**：

`read_file` / `read_image` 对 user-only 技能（`model_invocable=false`）的判据
是「主代理拒绝、子代理放行」（用户裁决 2026-11-12，见 `ARCHITECTURE_RULES.md`
§2.8）：主代理不得经任何路径自行加载用户专用技能正文，子代理可以（保留
「主代理把技能包路径交给子代理自读」的供给设计）。

实现取 contextvar 而非给每个工具加 ctx 参数：
- 与 `utils/cancel_token.py`、`skill_runtime/progress.py` 同构，绑定/解绑成对、
  异常路径随任务上下文消亡；
- 绑定点唯一 = `agent_loop.run_agent_loop`（子代理走同一个循环，深度天然正确，
  恢复态也不会归零），零新增调用点。

依赖方向：`tools` → `utils` 合法（`check_layer_imports` 只禁 core/tools → web）。
"""
from contextvars import ContextVar, Token

# 未绑定 = 0（主代理）：fail-closed 取更严的一侧——宁可少放行正文，
# 也不让未绑定的独立路径意外拿到 user-only 内容。
_subagent_depth_var: ContextVar[int] = ContextVar(
    "subagent_depth", default=0,
)


def bind_subagent_depth(depth: int) -> Token:
    """绑定本轮委派深度（`run_agent_loop` 循环入口调用），返回解绑凭证。"""
    try:
        value = int(depth or 0)
    except (TypeError, ValueError):
        value = 0
    return _subagent_depth_var.set(max(0, value))


def unbind_subagent_depth(tk: Token) -> None:
    """解绑（循环各出口调用；异常路径 contextvar 随任务消亡兜底，幂等）。"""
    try:
        _subagent_depth_var.reset(tk)
    except (ValueError, LookupError):
        pass


def current_subagent_depth() -> int:
    """当前上下文的委派深度（0 = 主代理；未绑定同样返回 0）。"""
    try:
        return max(0, int(_subagent_depth_var.get() or 0))
    except (TypeError, ValueError):
        return 0


def is_subagent_context() -> bool:
    """是否在子代理上下文内（深度 ≥ 1）。"""
    return current_subagent_depth() > 0


__all__ = [
    "bind_subagent_depth",
    "unbind_subagent_depth",
    "current_subagent_depth",
    "is_subagent_context",
]
