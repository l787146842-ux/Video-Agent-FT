from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel
from loguru import logger
from .base import BaseTool, ToolResult

class ToolManager:
    _tools: Dict[str, BaseTool] = {}
    _schema_cache: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def register(cls, tool: BaseTool):
        if not tool.name:
            raise ValueError("Tool must have a valid 'name' attribute.")
        cls._tools[tool.name] = tool
        cls._schema_cache = None  # 注册新工具时失效缓存
        logger.debug(f"Registered tool: {tool.name}")

    @classmethod
    def reset(cls):
        """清空注册表（测试用）"""
        cls._tools = {}
        cls._schema_cache = None

    @classmethod
    def get_tool(cls, name: str) -> BaseTool:
        tool = cls._tools.get(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found.")
        return tool

    @classmethod
    def get_all_tool_schemas(cls, exclude=None) -> List[Dict[str, Any]]:
        """返回全部工具的 schema（全集结果缓存，注册变化时失效）。

        exclude: 可选工具名集合，按上下文动态裁剪下发给 LLM 的工具列表
        （如工作台上下文关闭时不发 storyboard/document 工具、画布离线时不发 canvas_*），
        直接减少每轮 payload 的 schema token。裁剪在全集缓存之上过滤，不污染缓存。
        """
        full = cls._full_schemas()
        if not exclude:
            return full
        return [s for s in full if s.get("function", {}).get("name") not in exclude]

    @classmethod
    def _full_schemas(cls) -> List[Dict[str, Any]]:
        if cls._schema_cache is not None:
            return cls._schema_cache
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
        cls._schema_cache = schemas
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
