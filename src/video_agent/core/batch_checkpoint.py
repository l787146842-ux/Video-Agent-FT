"""批级检查点与条件回滚（批 6 · L1；接线点 = core/fc_tool_runner.py）。

修复「取消留半截态」：含写类/中高危工具的批在执行前经 StateManager 打整态
检查点；批内失败/取消时按**保守白名单条件**决定是否把状态恢复到批前
快照。恢复经 StateManager 受控写面（Rule 3 唯一写入点：
snapshot_state/restore_snapshot），禁止 state.clear()/update() 直接字典改法。

保守回滚条件（白名单式，缺任一条件即不回滚只留痕）：
- 本批确实失败或被取消；
- 批内无 risk=high 工具出现（ToolManager.get_tool_risk，画布写等
  外部副作用通道默认 high——未注册/未声明同样归 high，天然排除）；
- 生成族无成功也无失败/取消（fc_reconcile.BatchLedger 客观账本
  gen_succeeded / gen_failed_err：供应商侧已提交的外部任务不可回滚）；
- 无文档写入标志（BatchLedger doc_written / docs_written 既有字段复用）。
"""
from typing import Any, Iterable, Optional

from loguru import logger

from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager

__all__ = [
    "take_checkpoint",
    "batch_tool_names",
    "batch_has_risky_tool",
    "should_rollback",
    "maybe_rollback",
    "maybe_rollback_on_failure",
    "maybe_rollback_on_cancel",
]


def batch_tool_names(response: Any) -> list:
    """从 ChatResponse 提取本批全部工具名（含闸机拦截前即终止的调用）。"""
    names = []
    for call in getattr(response, "tool_calls", None) or []:
        func = call.get("function", {}) if isinstance(call, dict) else {}
        name = str(func.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _tool_risk(tool_manager: Any, name: str) -> str:
    """工具风险分级：优先既有 ToolManager.get_tool_risk；
    查询异常/测试桩缺能力一律归 high（保守：不新造名单、不漏放）。"""
    get_risk = getattr(tool_manager, "get_tool_risk", None)
    if get_risk is None:
        return "high"
    try:
        return str(get_risk(name) or "high").strip().lower() or "high"
    except Exception:
        return "high"


def batch_has_risky_tool(response: Any, tool_manager: Any) -> bool:
    """批内是否出现写类/中高危工具（risk ∈ {medium, high}）——检查点触发条件。"""
    return any(
        _tool_risk(tool_manager, name) in ("medium", "high")
        for name in batch_tool_names(response)
    )


def take_checkpoint(svc: Optional[Any] = None) -> Optional[dict]:
    """批首经 StateManager 打整态检查点；失败只记日志返回 None（不阻断批执行）。"""
    try:
        svc = svc or StateManager.get_instance()
        return svc.snapshot_state()
    except Exception as e:
        logger.warning("[BatchCheckpoint] 检查点快照失败（本批不做条件回滚）: {}", e)
        return None


def should_rollback(
    *,
    failed: bool,
    tool_names: Iterable[str] = (),
    gen_succeeded: bool = False,
    gen_failed_err: str = "",
    doc_written: bool = False,
    docs_written: Iterable[str] = (),
    tool_manager: Any = None,
) -> bool:
    """保守回滚条件谓词（白名单式）：仅当批内失败/取消**且**批内无任何外部
    副作用标志才回滚。副作用数据源不新造名单：
    - ToolManager.get_tool_risk：批内出现 risk=high 工具即排除（画布写等）；
    - BatchLedger 生成族客观账本：生成成功或失败/取消（供应商侧任务已提交）即排除；
    - 文档写标志：doc_written / docs_written（BatchLedger 既有字段）非空即排除。
    """
    if not failed:
        return False
    tm = tool_manager if tool_manager is not None else ToolManager
    for name in tool_names:
        if _tool_risk(tm, name) == "high":
            return False
    if gen_succeeded or gen_failed_err:
        return False
    if doc_written or any(str(d or "").strip() for d in (docs_written or ())):
        return False
    return True


def maybe_rollback(
    svc: Any,
    snapshot: Optional[dict],
    *,
    cancelled: bool = False,
    failed_tool: str = "",
    ledger: Any = None,
    tool_names: Iterable[str] = (),
    tool_manager: Any = None,
) -> bool:
    """按保守条件执行回滚；回滚自身失败只记日志不二次抛出。返回是否实际回滚。"""
    if snapshot is None:
        return False
    gen_succeeded = bool(getattr(ledger, "gen_succeeded", False))
    gen_failed_err = str(getattr(ledger, "gen_failed_err", "") or "")
    doc_written = bool(getattr(ledger, "doc_written", False))
    docs_written = list(getattr(ledger, "docs_written", None) or [])
    reason = "取消" if cancelled else "失败"
    if not should_rollback(
        failed=True, tool_names=tool_names, gen_succeeded=gen_succeeded,
        gen_failed_err=gen_failed_err, doc_written=doc_written,
        docs_written=docs_written, tool_manager=tool_manager,
    ):
        logger.info(
            "[BatchCheckpoint] 批内{}（{}）但检测到外部副作用标志"
            "（high 风险工具/生成族成败/文档写入），不回滚只留痕",
            reason, failed_tool or "unknown",
        )
        return False
    try:
        svc = svc or StateManager.get_instance()
        svc.restore_snapshot(snapshot)
        logger.warning(
            "[BatchCheckpoint] 批内{}（{}）且无外部副作用标志，"
            "状态已回滚至批前检查点", reason, failed_tool or "unknown",
        )
        return True
    except Exception as e:
        logger.warning("[BatchCheckpoint] 回滚执行失败（保留现场，不二次抛出）: {}", e)
        return False


def maybe_rollback_on_failure(
    svc: Any, snapshot: Optional[dict], *, failed_tool: str = "",
    ledger: Any = None, tool_names: Iterable[str] = (), tool_manager: Any = None,
) -> bool:
    """失败分支接线面（保持既有语义：记账顺序不变，只在分支尾调用）。"""
    return maybe_rollback(
        svc, snapshot, failed_tool=failed_tool, ledger=ledger,
        tool_names=tool_names, tool_manager=tool_manager)


def maybe_rollback_on_cancel(
    svc: Any, snapshot: Optional[dict], *, cancelled_tool: str = "",
    ledger: Any = None, tool_names: Iterable[str] = (), tool_manager: Any = None,
) -> bool:
    """取消分支接线面（GenerationCancelled 穿透上抛前先过保守条件判定）。"""
    return maybe_rollback(
        svc, snapshot, cancelled=True, failed_tool=cancelled_tool,
        ledger=ledger, tool_names=tool_names, tool_manager=tool_manager)
