import time

from loguru import logger
from pathlib import Path

from src.video_agent.state.manager import StateManager
from src.video_agent.core.planner import Planner
from src.video_agent.workflows.parser import WorkflowParser
from src.video_agent.workflows.engine import WorkflowEngine

class VideoAgent:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # StateManager 接收目录（它自己会在其中管理 state.json）；
        # 旧版误传了 state.json 路径，导致创建出 workspace/state.json/state.json
        self.state_manager = StateManager(str(self.workspace_dir))
        self.planner = Planner(self.state_manager)

        logger.info(f"VideoAgent Initialized in workspace: {self.workspace_dir}")

    async def run(self, user_goal: str, workflow_config_path: str) -> bool:
        """
        Main execution loop for user request.
        """
        logger.info(f"== Starting Agent Execution for goal: '{user_goal}' ==")

        # 0. 已有状态则续用（断点续跑），没有才初始化——不再无条件覆盖
        if not self.state_manager.state:
            self.state_manager.initialize_project(
                project_id=f"proj_{int(time.time())}",
                user_goal=user_goal,
            )

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
            return False

        # 4. Initialize and Run Workflow Engine
        # 未注入执行器时引擎使用 demo 执行器，日志会明确标注 demo 模式
        engine = WorkflowEngine(workflow_def)
        success = await engine.run()

        logger.info(f"== Agent Execution Completed (success={success}) ==")
        return success
