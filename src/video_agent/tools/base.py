import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, Field
from loguru import logger

class ToolResult(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[int] = None

class BaseTool(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def get_input_schema(self) -> Type[BaseModel]:
        pass

    def execute(self, params: BaseModel) -> ToolResult:
        """
        同步执行方法。如果子类实现了异步版本，默认将其作为 aexecute 执行，同步可包装事件循环
        """
        raise NotImplementedError("Subclasses should implement 'execute' or 'aexecute'.")

    async def aexecute(self, params: BaseModel) -> ToolResult:
        """
        异步执行版本。如果未覆盖，则回退到线程池/事件循环里运行 execute()
        """
        return await asyncio.to_thread(self.execute, params)
