import asyncio
from typing import Dict, Set, List
from loguru import logger

from .models import WorkflowDefinition, PhaseDefinition

class WorkflowEngine:
    def __init__(self, workflow_def: WorkflowDefinition):
        self.workflow_def = workflow_def
        self.phases: Dict[str, PhaseDefinition] = {p.phase_id: p for p in workflow_def.phases}
        self.completed_phases: Set[str] = set()
        self.failed_phases: Set[str] = set()
        self.running_phases: Set[str] = set()

    def _build_dependency_graph(self) -> Dict[str, List[str]]:
        graph = {}
        for phase_id, phase in self.phases.items():
            graph[phase_id] = phase.depends_on
        return graph

    def _get_executable_phases(self) -> List[PhaseDefinition]:
        executable = []
        for phase_id, phase in self.phases.items():
            if phase_id in self.completed_phases or phase_id in self.failed_phases or phase_id in self.running_phases:
                continue
            
            # Check if all dependencies are met
            can_run = True
            for dep in phase.depends_on:
                if dep not in self.completed_phases:
                    can_run = False
                    break
            
            if can_run:
                executable.append(phase)
        return executable

    async def _execute_phase(self, phase: PhaseDefinition) -> bool:
        """
        Mock execution of a single phase. 
        In real integration, this maps inputs, invokes skills, outputs mappings and validates.
        """
        logger.info(f"[Workflow] Starting Phase: {phase.name} ({phase.phase_id})")
        self.running_phases.add(phase.phase_id)
        
        try:
            # TODO: Integrate with StateManager and Skill execution layer here
            await asyncio.sleep(1)  # Simulating work
            
            self.running_phases.remove(phase.phase_id)
            self.completed_phases.add(phase.phase_id)
            logger.info(f"[Workflow] Completed Phase: {phase.name} ({phase.phase_id})")
            return True
        except Exception as e:
            logger.error(f"[Workflow] Failed Phase: {phase.name} - Error: {e}")
            self.running_phases.remove(phase.phase_id)
            self.failed_phases.add(phase.phase_id)
            return False

    async def run(self):
        logger.info(f"Starting workflow: {self.workflow_def.name}")
        
        while len(self.completed_phases) + len(self.failed_phases) < len(self.phases):
            # If there are failures, halt pipeline depending on strategy. Currently we abort.
            if self.failed_phases:
                logger.error("Workflow halted due to phase failures.")
                break

            executable = self._get_executable_phases()
            
            if not executable and self.running_phases:
                # Wait a bit if things are still running but no new ones can start
                await asyncio.sleep(0.5)
                continue
            elif not executable and not self.running_phases:
                # Deadlock detected!
                logger.error("Workflow deadlock! Cannot resolve dependencies for remaining phases.")
                break

            # Execute available phases up to max_parallel_tasks concurrency
            tasks = []
            for phase in executable:
                if len(self.running_phases) >= self.workflow_def.context.max_parallel_tasks:
                    break
                tasks.append(asyncio.create_task(self._execute_phase(phase)))

            # Note: We process tasks asynchronously, loop will pick up new ones sequentially.
            # waiting for at least one to finish before checking again
            if tasks:
                 done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        if len(self.completed_phases) == len(self.phases):
            logger.info("Workflow completed successfully!")
        else:
            logger.warning("Workflow completely finished with pending/failed items.")
