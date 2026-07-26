import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from loguru import logger

from .models import (
    ProjectState,
    TaskStatus,
    AssetState,
    AssetStatus
)

class StateManager:
    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.state_file = os.path.join(project_dir, "state.json")
        self.state: Optional[ProjectState] = None
        self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.state = ProjectState.model_validate(data)
                logger.info(f"Loaded existing state from {self.state_file}")
            except Exception as e:
                logger.error(f"Failed to load state from {self.state_file}: {e}")
                raise e
        else:
            logger.info("No existing state found. State will be initialized upon first save.")

    def initialize_project(self, project_id: str, user_goal: str, project_name: str = "New Project") -> ProjectState:
        if self.state:
            logger.warning("Overwriting existing project state.")
            
        self.state = ProjectState(
            project_id=project_id,
            project_name=project_name,
            user_goal=user_goal
        )
        # Setup metadata directory info
        self.state.metadata.workspace_dir = self.project_dir
        self.state.metadata.output_dir = os.path.join(self.project_dir, "outputs")
        
        # Ensure output dir exists
        os.makedirs(self.state.metadata.output_dir, exist_ok=True)
        
        self.save_state()
        return self.state

    def save_state(self):
        if not self.state:
            logger.error("No state to save.")
            return
            
        self.state.updated_at = datetime.utcnow()
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                # dump models utilizing Pydantic v2 conventions
                json_data = self.state.model_dump_json(indent=2)
                f.write(json_data)
            logger.debug(f"State saved to {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            raise e

    def get(self) -> ProjectState:
        if not self.state:
            raise ValueError("State is not initialized.")
        return self.state

    def update_task_status(self, task_id: str, status: TaskStatus, output_asset_id: Optional[str] = None, error: Optional[str] = None):
        if not self.state:
            return
            
        for task in self.state.tasks:
            if task.task_id == task_id:
                task.status = status
                if status == TaskStatus.completed:
                    task.completed_at = datetime.utcnow()
                if output_asset_id:
                    task.output.asset_id = output_asset_id
                if error:
                    task.error = error
                self.save_state()
                logger.debug(f"Task {task_id} status updated to {status}")
                return
        logger.warning(f"Task {task_id} not found.")

    def add_asset(self, asset: AssetState):
        if not self.state:
            return
        # Ensure no duplicates (or update existing)
        for i, a in enumerate(self.state.assets):
            if a.asset_id == asset.asset_id:
                self.state.assets[i] = asset
                self.save_state()
                logger.debug(f"Asset {asset.asset_id} updated.")
                return
                
        self.state.assets.append(asset)
        self.save_state()
        logger.debug(f"Asset {asset.asset_id} added.")
        
    def update_asset_status(self, asset_id: str, status: AssetStatus, file_path: Optional[str] = None):
        if not self.state:
            return
            
        for asset in self.state.assets:
            if asset.asset_id == asset_id:
                asset.status = status
                if file_path:
                    asset.file_path = file_path
                self.save_state()
                logger.debug(f"Asset {asset_id} status updated to {status}")
                return
        logger.warning(f"Asset {asset_id} not found.")
