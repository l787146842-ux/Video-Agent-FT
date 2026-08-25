import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field

# 风险分级合法枚举（宪法 §2.7 单一事实源；注册校验/闸机消费同引用）
RISK_TIERS = ("low", "medium", "high")

# 前端时间线展示档合法枚举（展示档元数据驱动，前端不硬编码工具名）：
# expand=可展开看输入参数预览+执行结果；output=仅输出留痕（不显示输入）。
# 未声明者前端默认归 output（新工具至少留输出痕迹）；非工具内部条目
# （如 model_reasoning）不经本属性，由 sidecar 独立名单登记 none。
DETAIL_TIERS = ("expand", "output")


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
    # 工具风险分级（宪法 §2.7）：low=只读/可逆；medium=写状态但可撤销；
    # high=生成/文档写入/跨阶段建结构/外部副作用。
    # 必须由子类显式声明；未声明者在 ToolManager.register 被拒绝注册
    # （deny-by-default，不得静默放行）。
    risk: str = ""
    # 前端时间线展示档：取值见 DETAIL_TIERS；空 = 未声明，
    # 前端默认 output（展示档非安全闸，不 deny-by-default，但声明优先）。
    detail_tier: str = ""

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
