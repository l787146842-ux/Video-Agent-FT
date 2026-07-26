import json
import yaml
from pathlib import Path
from pydantic import ValidationError
from typing import Union

from .models import WorkflowDefinition

class WorkflowParser:
    @classmethod
    def load_from_file(cls, file_path: Union[str, Path]) -> WorkflowDefinition:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow config file not found: {path}")
            
        with open(path, 'r', encoding='utf-8') as f:
            if path.suffix in ('.yaml', '.yml'):
                data = yaml.safe_load(f)
            elif path.suffix == '.json':
                data = json.load(f)
            else:
                raise ValueError("Unsupported configuration file format. Use .json or .yaml")
                
        try:
            return WorkflowDefinition.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"Workflow config validation failed: {str(e)}")
