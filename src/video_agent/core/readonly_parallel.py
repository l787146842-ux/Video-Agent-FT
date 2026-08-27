"""只读受限并行（批 7 · L3，默认关；接线点 = core/fc_tool_runner.py）。

仅对批内**连续** risk=low 只读工具段做受限并行执行，降低连续读类调用的
等待；闸机链仍逐调用按序裁决，写类/中高危/未注册工具一律串行。

段识别（白名单口径，不新造名单）：
- 连续 `ToolManager.get_tool_risk(name) == "low"` 的调用段为并行窗口，
  混入非 low（medium/high/未注册——既有 get_tool_risk deny-by-default
  归 high）即断段；窗口长度 ≥ 2 才有并行收益。
- 风险查询能力缺失/异常（测试桩）一律归 high（与批 6 batch_checkpoint 同口径）。

窗口执行（执行段）：
1. 幂等键命中（轮内账本）→ 直接用首次结果，不重复执行；
2. 闸机链逐调用**按序**裁决（含结构纯净闸/提示词剥离同序副作用），
   任一拒收即断并行：拒收前的已放行调用按序串行执行，拒收调用记拒因，
   其后调用回到主循环串行逐调用裁决（不二次过闸）；
3. 全部放行后并行执行（asyncio 任务 + 按序消费），结果按原序回填；
   窗口内任一调用失败/异常即回退串行消费剩余调用；
4. `GenerationCancelled` 显式穿透：先记本调用账本/trace（取消态）与
   批级检查点回滚判定再上抛，不得被并行调度吞咽。

开关关闭（默认）时 `plan_batch` 返回空计划，执行路径与现状完全等价。
"""
import asyncio
import json
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from loguru import logger

from src.video_agent.adapters.cancel_token import GenerationCancelled
from src.video_agent.config import settings
from src.video_agent.core import batch_checkpoint, fc_gates, tool_args_preview
from src.video_agent.core.fc_feedback import describe_fc_tool
from src.video_agent.core.sse_events import SSE_TOOL_FINISHED, SSE_TOOL_STARTED
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import stage_label_for_tool
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult

__all__ = ["PreExecuted", "plan_batch", "find_readonly_windows", "run_window"]


class PreExecuted(NamedTuple):
    """窗口内预执行结果（主循环按原下标回填消费）：
    result=工具结果或闸机拒收结果；gate_error=闸机拒因（放行时为 None）；
    elapsed_ms=执行耗时（保持 SSE_TOOL_FINISHED/trace 的耗时口径）。"""

    result: ToolResult
    gate_error: Optional[str]
    elapsed_ms: float


def _risk_of(tool_manager: Any, name: str) -> str:
    """工具风险分级：优先既有 ToolManager.get_tool_risk（deny-by-default）；
    查询能力缺失/异常一律归 high（保守：不新造名单、不漏放，同批 6 口径）。"""
    get_risk = getattr(tool_manager, "get_tool_risk", None)
    if get_risk is None:
        return "high"
    try:
        return str(get_risk(name) or "high").strip().lower() or "high"
    except Exception:
        return "high"


def _call_name_args(call: Any) -> Tuple[str, Dict[str, Any]]:
    """与主批循环同口径解析单个 tool_call（畸形调用归空名/空参）。"""
    func = call.get("function", {}) if isinstance(call, dict) else {}
    name = str(func.get("name") or "")
    args_raw = func.get("arguments", "{}")
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
    except json.JSONDecodeError:
        args = {}
    return name, (args if isinstance(args, dict) else {})


def find_readonly_windows(tool_calls: List[Any], tool_manager: Any) -> Dict[int, List[int]]:
    """连续 low 只读段识别：混入非 low（含未注册→high）即断段；
    窗口长度 ≥ 2 才入计划（单调用无并行收益）。返回 {窗口起始下标: 窗口内下标列表}。"""
    plan: Dict[int, List[int]] = {}
    cur: List[int] = []

    def _flush() -> None:
        if len(cur) >= 2:
            plan[cur[0]] = list(cur)
        cur.clear()

    for i, call in enumerate(tool_calls or []):
        name, _ = _call_name_args(call)
        if name and _risk_of(tool_manager, name) == "low":
            cur.append(i)
        else:
            _flush()
    _flush()
    return plan


def plan_batch(tool_calls: List[Any], tool_manager: Any) -> Tuple[Dict[int, List[int]], Dict[int, PreExecuted]]:
    """批级并行计划（接线面）：开关关闭（默认）或无可并行段时返回空计划，
    主循环代码路径与现状完全等价。返回 (窗口计划, 预执行结果回填字典)。"""
    if not settings.readonly_parallel_enabled:
        return {}, {}
    return find_readonly_windows(tool_calls, tool_manager), {}


def _quiet_cancel(task: "asyncio.Task") -> None:
    """安静取消并行兄弟任务：已完成取回异常（防未检索告警），
    未完成发取消并同步标记异常已检索（pending 取消任务的异常为 CancelledError）。"""
    if task.done():
        if not task.cancelled():
            try:
                task.result()
            except Exception:
                pass
    else:
        task.cancel()
        try:
            task.result()
        except Exception:
            pass


def _resolve_task_result(task: "asyncio.Task") -> ToolResult:
    """已完成任务取结果：异常转失败结果（与主循环失败口径一致），
    取消例外穿透（由调用方处置）。"""
    try:
        return task.result()
    except GenerationCancelled:
        raise
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return ToolResult(success=False, error=str(e) or e.__class__.__name__)


async def _take_result(
    task: "asyncio.Task", runner: Any, name: str, args: Dict[str, Any],
    injected_skill: str,
) -> ToolResult:
    """按序取单调用结果：未完成/被取消的任务回退串行重执（只读无副作用）；
    已完成直接取结果（不重复执行）。取消穿透不吞。"""
    if task.done() and not task.cancelled():
        return _resolve_task_result(task)
    _quiet_cancel(task)
    try:
        return await runner._dispatch_tool(name, args, injected_skill)
    except GenerationCancelled:
        raise
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return ToolResult(success=False, error=str(e) or e.__class__.__name__)


async def _record_cancelled(
    name: str, args: Dict[str, Any], call: Any, ci: int, t0: float,
    on_event: Any,
) -> None:
    """取消留痕（与串行主循环同口径）：started/finished 事件对 + trace 记账。
    窗口调度先于主循环的 started 事件，故补发配对保证时间线条目完整。
    账本/回滚判定在调用方穿透上抛前完成（不吞异常）。"""
    tool_event_id = str(call.get("id") or f"fc-{ci}") if isinstance(call, dict) else f"fc-{ci}"
    elapsed_ms = (time.monotonic() - t0) * 1000
    if on_event is not None:
        try:
            await on_event({
                "type": SSE_TOOL_STARTED,
                "id": tool_event_id,
                "name": name,
                "summary": describe_fc_tool(name, args),
                "args": tool_args_preview.redact_tool_args(name, args),
            })
            await on_event({
                "type": SSE_TOOL_FINISHED,
                "id": tool_event_id,
                "ok": False,
                "elapsed_ms": round(elapsed_ms, 1),
                "result_summary": "已被用户取消",
            })
        except Exception as e:
            logger.debug("[ReadOnlyParallel] 取消事件下发失败（不影响穿透）: {}", e)
    try:
        AgentTracer.get_instance().record_action(
            name=name, summary=describe_fc_tool(name, args),
            elapsed_ms=elapsed_ms, ok=False,
            stage=stage_label_for_tool(name),
            result_summary="已被用户取消",
            args=tool_args_preview.redact_tool_args(name, args),
        )
    except Exception as e:
        logger.debug("[ReadOnlyParallel] 取消 trace 记账失败（不影响穿透）: {}", e)


async def run_window(
    runner: Any,
    ctx: Any,
    ledger: Any,
    tool_calls: List[Any],
    indices: List[int],
    pre: Dict[int, PreExecuted],
    *,
    paused_this_batch: bool,
    injected_skill: str,
    on_event: Any,
    batch_cp: Optional[dict],
    batch_tools: List[str],
) -> int:
    """窗口调度（接线面）：闸机链逐调用按序裁决 → 全部放行才并行执行 →
    结果按原序回填 pre；任一拒收即断并行（其后调用回主循环串行裁决），
    任一失败/异常回退串行消费剩余；GenerationCancelled 显式穿透。
    返回窗口内累计的提示词结构闸拦截计数（主循环节拍器口径不变）。"""
    prompt_blocked = 0
    passed: List[Tuple[int, str, Dict[str, Any]]] = []
    for i in indices:
        call = tool_calls[i]
        name, args = _call_name_args(call)
        # current/空引用 → 真实 id（与主循环同口径；重复解析幂等）
        fc_gates.resolve_current_refs(ctx, name, args)
        # 幂等键轮内去重（T4）：同键命中直接用首次结果，跳过闸机链与实际执行
        _idem_key = str(args.get("idempotency_key") or "").strip()
        _idem_cached = runner._idempotency.check(_idem_key)
        if _idem_cached is not None:
            pre[i] = PreExecuted(_idem_cached, None, 0.0)
            continue
        # 结构纯净闸：内联详细提示词剥离（闸机链之前，与主循环同序）
        if fc_gates.strip_structure_prompt(ctx, name, args):
            ledger.prompt_stripped = True
        # 闸机链按序裁决（实现不动；逐调用短路语义与串行路径一致）
        chain = fc_gates.run_gate_chain(ctx, name, args, paused_this_batch=paused_this_batch)
        prompt_blocked += chain.prompt_gate_blocked
        if chain.error is not None:
            # 拒收即断并行：已放行调用按序串行执行，拒收调用记拒因回填，
            # 其后调用不入窗口，由主循环串行逐调用裁决
            await _serial_drain(runner, passed, pre, injected_skill=injected_skill)
            pre[i] = PreExecuted(ToolResult(success=False, error=chain.error), chain.error, 0.0)
            return prompt_blocked
        passed.append((i, name, args))

    # 全部放行 → 窗口内并行执行，按序消费回填：任一失败/异常即置串行标志，
    # 剩余调用取消并行任务后串行重执（已完成的取结果不重复执行）
    tasks = [
        asyncio.ensure_future(runner._dispatch_tool(name, args, injected_skill))
        for _i, name, args in passed
    ]
    serial = False
    for pos, (i, name, args) in enumerate(passed):
        t0 = time.monotonic()
        try:
            if serial:
                result = await _take_result(tasks[pos], runner, name, args, injected_skill)
            else:
                result = await tasks[pos]
                if not result.success:
                    serial = True
        except GenerationCancelled:
            for t in tasks:
                _quiet_cancel(t)
            await _record_cancelled(name, args, tool_calls[i], i, t0, on_event)
            batch_checkpoint.maybe_rollback_on_cancel(
                StateManager.get_instance(), batch_cp, cancelled_tool=name,
                ledger=ledger, tool_names=batch_tools,
                tool_manager=runner.tool_manager)
            raise
        except asyncio.CancelledError:
            for t in tasks:
                _quiet_cancel(t)
            raise
        pre[i] = PreExecuted(result, None, (time.monotonic() - t0) * 1000)
    return prompt_blocked


async def _serial_drain(
    runner: Any, passed: List[Tuple[int, str, Dict[str, Any]]],
    pre: Dict[int, PreExecuted], *, injected_skill: str,
) -> None:
    """闸机拒收断并行时：已放行调用按序串行执行回填（不二次过闸）。"""
    for i, name, args in passed:
        if i in pre:
            continue
        t0 = time.monotonic()
        try:
            result = await runner._dispatch_tool(name, args, injected_skill)
        except GenerationCancelled:
            raise  # 取消穿透：不得被串行收尾吞咽
        except Exception as e:  # 与主循环失败口径一致：异常转失败结果不炸批
            result = ToolResult(success=False, error=str(e) or e.__class__.__name__)
        pre[i] = PreExecuted(result, None, (time.monotonic() - t0) * 1000)
