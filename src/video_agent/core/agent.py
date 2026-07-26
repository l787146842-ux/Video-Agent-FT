from loguru import logger
from typing import Optional
from pathlib import Path

from src.video_agent.state.manager import StateManager
from src.video_agent.core.planner import Planner
from src.video_agent.workflows.parser import WorkflowParser
from src.video_agent.workflows.engine import WorkflowEngine

class VideoAgent:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize sub-components
        self.state_manager = StateManager(str(self.workspace_dir / "state.json"))
        self.state_manager.initialize_project("proj_001", "Auto Goal")
        
        self.planner = Planner(self.state_manager)
        
        logger.info(f"VideoAgent Initialized in workspace: {self.workspace_dir}")

    async def run(self, user_goal: str, workflow_config_path: str):
        """
        Main execution loop for user request.
        """
        logger.info(f"== Starting Agent Execution for goal: '{user_goal}' ==")
        
        # 1. Plan Phase
        await self.planner.analyze_request(user_goal)
        
        # 2. Parse & Resolve Workflow Blueprint
        blueprint_id = await self.planner.auto_resolve_workflow()
        logger.info(f"Planner selected blueprint ID: {blueprint_id}")
        
        # 3. Load Workflow Definition
        try:
            workflow_def = WorkflowParser.load_from_file(workflow_config_path)
            logger.info(f"Loaded workflow definition: {workflow_def.name}")
        except Exception as e:
            logger.error(f"Failed to load workflow configuration: {e}")
            return

        # 4. Initialize and Run Workflow Engine
        engine = WorkflowEngine(workflow_def)
        await engine.run()
        
        logger.info("== Agent Execution Completed ==")
        
