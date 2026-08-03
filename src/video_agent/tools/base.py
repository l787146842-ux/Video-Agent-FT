import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field


class ToolEvent(BaseModel):
    """工具执行过程中向前端推送的结构化事件。

    示例：
        ToolEvent(type="generation_progress", payload={"draft_id": "...", "progress": 0.5})
        ToolEvent(type="canvas_node_added", payload={"node_id": "...", "canvas_id": "..."})
    """
    type: str = ""       # 事件类型标识（前端根据此字段决定如何处理）
    payload: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具执行结果。

    - success: 是否成功
    - data: 业务数据（供 LLM 或前端使用）
    - error: 失败时的错误信息
    - events: 执行过程中产生的结构化事件（可选，供前端实时反馈）
    """
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    events: List[ToolEvent] = Field(default_factory=list)

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
