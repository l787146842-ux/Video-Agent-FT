# -*- coding: utf-8 -*-
"""计划清单工具（plan_write，细案 docs/计划清单工具细案.md）。

模型自维护的多步任务进度账（对标 dsh todo_write 通用形态）：
- 整表替换：每次调用传完整清单覆盖旧表，无局部更新；
- 三态 pending/in_progress/completed，「至多一个 in_progress」代码硬校验；
- 时机引导全在本工具 description（软），校验落代码（硬）——G3 两分；
- 落盘 state["plan"]（直写 + save，analysis 先例，不入 undo 栈）；
- 轮首状态事件注入紧凑清单（空不注入）；步间零注入——模型回看自己
  历史里的工具调用参数即得进度（缓存设计核心，细案 §五）。
"""
from typing import Any, Dict, List, Tuple, Type

from pydantic import BaseModel, Field

from ..state.manager import StateManager
from .base import BaseTool, StrictToolInput, ToolResult
from .manager import ToolManager

# 清单上限（细案 §九 裁决点 3：先按此，批 0 数据回来再校）
MAX_ITEMS = 24
MAX_CONTENT_CHARS = 40
STATUSES = ("pending", "in_progress", "completed")


class PlanItem(StrictToolInput):
    content: str = Field(
        ..., description=f"步骤一句话描述，短祈使句，不超过 {MAX_CONTENT_CHARS} 字")
    status: str = Field(
        ..., description="状态：pending（未开始）/ in_progress（进行中）/ "
                         "completed（已完成）")


class PlanWriteInput(StrictToolInput):
    todos: List[PlanItem] = Field(
        ..., description=f"完整清单（1-{MAX_ITEMS} 项），整表替换旧表")


def validate_plan_items(items: List[Dict[str, Any]]) -> Tuple[str, str]:
    """清单校验（纯函数，返回 (原因码, 错误话术)；通过 = ("", "")）。

    话术 ≤3 句、纯事实+补救（v4-1 口径）；任一失败整次拒收、旧清单保留。
    单测直接打本函数拿校验矩阵。
    """
    n = len(items)
    if n == 0:
        return "empty", "清单校验失败：todos 为空。本次未写入，保留上次清单。"
    if n > MAX_ITEMS:
        return "too_many", (
            f"清单校验失败：{n} 项超过上限 {MAX_ITEMS}。本次未写入，保留上次清单；"
            "合并同类步骤后整表重提。")
    seen: set = set()
    for it in items:
        content = str(it.get("content") or "").strip()
        if not content:
            return "blank", (
                "清单校验失败：存在空 content 项。本次未写入，保留上次清单；"
                "补全该项描述后整表重提。")
        if content in seen:
            return "duplicate", (
                f"清单校验失败：步骤「{content[:20]}」重复。本次未写入，保留上次清单；"
                "去重后整表重提。")
        seen.add(content)
        status = str(it.get("status") or "")
        if status not in STATUSES:
            return "bad_status", (
                f"清单校验失败：状态「{status}」非法（仅 "
                + " / ".join(STATUSES) + "）。本次未写入，保留上次清单。")
    active = sum(1 for it in items
                 if str(it.get("status") or "") == "in_progress")
    if active > 1:
        return "multi_active", (
            f"清单校验失败：发现 {active} 个 in_progress（至多 1 个）。"
            "本次未写入，保留上次清单；合并为单一进行中项后整表重提。")
    return "", ""


class PlanWriteTool(BaseTool):
    name = "plan_write"
    risk = "low"  # 纯进度账，可整体重写（tool_risk 闸只挂 high，不触）
    detail_tier = "expand"  # 产出类：展开看输入参数+执行结果（analysis 同口径）
    description = (
        "维护当前多步任务的计划清单（整表替换）：开工前把每个具体步骤列一条；"
        "同一时刻至多一项 in_progress；完成一项立刻标 completed，不攒批；"
        f"单步小任务不建清单；每次调用传完整清单（1-{MAX_ITEMS} 项）覆盖旧表。"
        "清单是进度账，不替代 workflow_pause 的暂停确认。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return PlanWriteInput

    async def aexecute(self, params: PlanWriteInput) -> ToolResult:
        items = [{"content": str(p.content or "").strip(),
                  "status": str(p.status or "")} for p in params.todos]
        code, msg = validate_plan_items(items)
        if code:
            return ToolResult(success=False, error=msg,
                              error_code="validation", retryable=False)
        svc = StateManager.get_instance()
        async with svc.lock:
            svc.state_dict["plan"] = {
                "items": items,
                "updated_turn": int(svc.state_dict.get("turn_seq") or 0),
            }
            svc.save()
        open_count = sum(1 for it in items if it["status"] != "completed")
        # 成功回显极小（细案 §三：清单字节只存在于模型自己的 tool_call 参数）
        return ToolResult(success=True, data={
            "items": len(items), "open": open_count})


def register_plan_tools() -> None:
    """注册计划清单 Tool（与 register_analysis_tools 同一接线口径）"""
    ToolManager.register(PlanWriteTool())
