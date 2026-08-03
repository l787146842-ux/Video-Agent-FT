"""
Workflow 执行引擎。

修复项（相对旧版）：
- 并发上限：调度时（create_task 前）就登记 running_phases，同一批不会超发；
- 失败处理：出现失败后等待在跑任务收尾，不再丢弃孤儿任务；
- 支持注入 phase_executor（真实业务逻辑），引擎只负责依赖调度/并发/重试/超时；
- 按 retry_policy 重试；
- phase 可返回 {"skipped": True, "detail": ...} 表示「诚实跳过」（满足依赖但明确标注未执行）。
"""
import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from loguru import logger

from .models import PhaseDefinition, WorkflowDefinition

# phase_executor(phase, context) -> Any；抛异常视为失败；返回 {"skipped": True} 视为跳过
# context 是阶段间共享数据字典，前一阶段的输出存入 context[phase_id]
PhaseExecutor = Callable[[PhaseDefinition, Dict[str, Any]], Awaitable[Any]]
# on_event(event: dict) -> None；事件：phase_started / phase_completed / phase_failed
EventHook = Callable[[Dict[str, Any]], Awaitable[None]]


class WorkflowEngine:
    def __init__(
        self,
        workflow_def: WorkflowDefinition,
        phase_executor: Optional[PhaseExecutor] = None,
        on_event: Optional[EventHook] = None,
    ):
        self.workflow_def = workflow_def
        self.phases: Dict[str, PhaseDefinition] = {p.phase_id: p for p in workflow_def.phases}
        self.phase_executor = phase_executor or self._demo_executor
        self.on_event = on_event

        self.completed_phases: Set[str] = set()   # 含 skipped（用于依赖判定）
        self.skipped_phases: Set[str] = set()
        self.failed_phases: Set[str] = set()
        self.running_phases: Set[str] = set()
        self.phase_results: Dict[str, Dict[str, Any]] = {}
        self.phase_context: Dict[str, Any] = {}  # 阶段间共享数据（前一阶段输出作为后一阶段输入）
        self._tasks: Dict[str, asyncio.Task] = {}
        self._awaiting_confirmation: bool = False  # 交互模式：等待用户确认推进

    @staticmethod
    async def _demo_executor(phase: PhaseDefinition, context: Dict[str, Any]) -> Dict[str, Any]:
        """默认执行器——仅用于无 UI 的 CLI 演示，明确标注 demo"""
        logger.info(f"[Workflow] (demo) 模拟执行 phase: {phase.phase_id}")
        await asyncio.sleep(0.2)
        return {"detail": f"demo 模式：phase '{phase.name}' 未执行真实逻辑"}

    async def _emit(self, event: Dict[str, Any]) -> None:
        if self.on_event:
            try:
                await self.on_event(event)
            except Exception as e:
                logger.warning(f"[Workflow] 事件回调失败: {e}")

    def _get_executable_phases(self) -> List[PhaseDefinition]:
        executable = []
        for phase_id, phase in self.phases.items():
            if (
                phase_id in self.completed_phases
                or phase_id in self.failed_phases
                or phase_id in self.running_phases
            ):
                continue
            if all(dep in self.completed_phases for dep in phase.depends_on):
                executable.append(phase)
        return executable

    def _retry_delay(self, attempt: int) -> float:
        policy = self.workflow_def.context.retry_policy
        base = max(policy.base_delay_seconds, 0)
        if policy.backoff == "exponential":
            return base * (2 ** (attempt - 1))
        return base * attempt  # linear

    async def _run_phase(self, phase: PhaseDefinition) -> None:
        """执行单个 phase（带超时与重试）。调用前 phase 已登记进 running_phases。"""
        policy = self.workflow_def.context.retry_policy
        await self._emit({"event": "phase_started", "phase": phase.phase_id, "label": phase.name})

        attempt = 0
        try:
            while True:
                attempt += 1
                try:
                    result = await asyncio.wait_for(
                        self.phase_executor(phase, self.phase_context), timeout=phase.timeout_seconds
                    )
                    skipped = isinstance(result, dict) and bool(result.get("skipped"))
                    detail = (result or {}).get("detail", "") if isinstance(result, dict) else ""
                    self.completed_phases.add(phase.phase_id)
                    if skipped:
                        self.skipped_phases.add(phase.phase_id)
                    # 将阶段输出存入 phase_context，供下游阶段读取
                    self.phase_context[phase.phase_id] = result
                    self.phase_results[phase.phase_id] = {
                        "status": "skipped" if skipped else "completed",
                        "detail": detail,
                        "result": result,
                    }
                    logger.info(
                        f"[Workflow] Phase {'跳过' if skipped else '完成'}: "
                        f"{phase.name} ({phase.phase_id})"
                    )
                    await self._emit({
                        "event": "phase_completed",
                        "phase": phase.phase_id,
                        "label": phase.name,
                        "detail": detail,
                        "skipped": skipped,
                    })
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if attempt > policy.max_retries:
                        raise
                    delay = self._retry_delay(attempt)
                    logger.warning(
                        f"[Workflow] Phase {phase.phase_id} 第 {attempt} 次失败: {e}，"
                        f"{delay}s 后重试"
                    )
                    await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.failed_phases.add(phase.phase_id)
            self.phase_results[phase.phase_id] = {"status": "failed", "error": str(e)}
            logger.error(f"[Workflow] Phase 失败: {phase.name} - {e}")
            await self._emit({
                "event": "phase_failed",
                "phase": phase.phase_id,
                "label": phase.name,
                "error": str(e),
            })
        finally:
            self.running_phases.discard(phase.phase_id)

    async def _drain_running(self) -> None:
        """等待所有在跑任务收尾（失败中止时避免孤儿任务）"""
        pending = [t for t in self._tasks.values() if not t.done()]
        if pending:
            await asyncio.wait(pending)

    async def run(self) -> bool:
        """执行整个工作流（批处理模式，CLI 用）。返回是否全部成功（skipped 计入成功）。"""
        logger.info(f"Starting workflow: {self.workflow_def.name}")
        max_parallel = max(1, self.workflow_def.context.max_parallel_tasks)

        while len(self.completed_phases) + len(self.failed_phases) < len(self.phases):
            if self.failed_phases:
                logger.error("Workflow halted due to phase failures.")
                await self._drain_running()
                break

            executable = self._get_executable_phases()

            slots = max_parallel - len(self.running_phases)
            for phase in executable[: max(0, slots)]:
                # 在 create_task 之前登记，保证同一批调度不会突破并发上限
                self.running_phases.add(phase.phase_id)
                self._tasks[phase.phase_id] = asyncio.create_task(self._run_phase(phase))

            active = [t for t in self._tasks.values() if not t.done()]
            if not active:
                if not executable:
                    logger.error(
                        "Workflow deadlock! Cannot resolve dependencies for remaining phases."
                    )
                    break
                continue

            await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)

        await self._drain_running()

        success = (
            len(self.completed_phases) == len(self.phases) and not self.failed_phases
        )
        if success:
            logger.info(
                f"Workflow completed. "
                f"({len(self.skipped_phases)} skipped / {len(self.phases)} total)"
            )
        else:
            logger.warning("Workflow finished with failed/unresolved phases.")
        return success

    # ---------- 交互模式（Web 用） ----------

    @property
    def current_phase(self) -> Optional[str]:
        """返回下一个可执行阶段的 phase_id，全部完成时返回 None"""
        executable = self._get_executable_phases()
        if executable:
            return executable[0].phase_id
        if len(self.completed_phases) + len(self.failed_phases) >= len(self.phases):
            return None
        return None

    @property
    def is_awaiting_confirmation(self) -> bool:
        """是否正在等待用户确认"""
        return self._awaiting_confirmation

    async def step(self) -> Dict[str, Any]:
        """交互模式：执行当前阶段的下一步，完成后暂停等待确认。

        返回 PhaseResult dict：
        - {"status": "completed", "phase": "story", "detail": "..."}
        - {"status": "skipped", "phase": "audio", "detail": "..."}
        - {"status": "failed", "phase": "image", "error": "..."}
        - {"status": "done"}  # 所有阶段已完成
        """
        if self._awaiting_confirmation:
            return {"status": "waiting", "detail": "等待用户确认后才能继续"}

        executable = self._get_executable_phases()
        if not executable:
            if len(self.completed_phases) + len(self.failed_phases) >= len(self.phases):
                return {"status": "done", "detail": "所有阶段已完成"}
            return {"status": "blocked", "detail": "无法确定下一步（依赖未满足或死锁）"}

        phase = executable[0]
        self.running_phases.add(phase.phase_id)
        try:
            await self._run_phase(phase)
        finally:
            self.running_phases.discard(phase.phase_id)

        result = self.phase_results.get(phase.phase_id, {})
        status = result.get("status", "unknown")

        # 执行完成后暂停，等待用户确认
        self._awaiting_confirmation = True
        logger.info(f"[Workflow] 交互模式：phase '{phase.phase_id}' {status}，等待确认")

        return {
            "status": status,
            "phase": phase.phase_id,
            "detail": result.get("detail", ""),
            "error": result.get("error", ""),
        }

    def advance(self) -> None:
        """用户确认后调用，推进到下一阶段"""
        self._awaiting_confirmation = False
        logger.info("[Workflow] 用户已确认，推进到下一阶段")
