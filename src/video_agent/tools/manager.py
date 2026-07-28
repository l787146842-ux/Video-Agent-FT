from typing import Any, Dict, List, Type
from pydantic import BaseModel
from loguru import logger
from .base import BaseTool, ToolResult

class ToolManager:
    _tools: Dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool):
        if not tool.name:
            raise ValueError("Tool must have a valid 'name' attribute.")
        cls._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    @classmethod
    def reset(cls):
        """清空注册表（测试用）"""
        cls._tools = {}

    @classmethod
    def get_tool(cls, name: str) -> BaseTool:
        tool = cls._tools.get(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found.")
        return tool

    @classmethod
    def get_all_tool_schemas(cls) -> List[Dict[str, Any]]:
        schemas = []
        for name, tool in cls._tools.items():
            schema_class = tool.get_input_schema()
            json_schema = schema_class.model_json_schema()
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": json_schema.get("properties", {}),
                        "required": json_schema.get("required", [])
                    }
                }
            })
        return schemas

    @classmethod
    async def invoke_tool(cls, name: str, kwargs: Dict[str, Any]) -> ToolResult:
        try:
            tool = cls.get_tool(name)
            schema_class = tool.get_input_schema()
            
            # Pydantic validation
            try:
                params = schema_class.model_validate(kwargs)
            except Exception as e:
                return ToolResult(success=False, error=f"Validation Error: {str(e)}")

            return await tool.aexecute(params)
        except Exception as e:
            logger.error(f"Error invoking tool {name}: {e}")
            return ToolResult(success=False, error=str(e))
