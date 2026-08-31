import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, ConfigDict, Field

# 风险分级合法枚举（宪法 §2.7 单一事实源；注册校验/闸机消费同引用）
RISK_TIERS = ("low", "medium", "high")

# 审批行为单轴枚举（F1 裁决 2026-08-31 双轴并单轴：原 risk×approval_tier
# 正交双轴合并——生效档由 risk 单轴推导，不再独立声明）：
# none=自动过；confirm=执行前确认卡；review=执行后复核（保留词汇，
# 当前推导不产出）。未注册工具按最严口径 confirm（deny-by-default）。
APPROVAL_TIERS = ("none", "confirm", "review")

# 前端时间线展示档合法枚举（展示档元数据驱动，前端不硬编码工具名）：
# expand=可展开看输入参数预览+执行结果；output=仅输出留痕（不显示输入）。
# 未声明者前端默认归 output（新工具至少留输出痕迹）；非工具内部条目
# （如 model_reasoning）不经本属性，由 sidecar 独立名单登记 none。
DETAIL_TIERS = ("expand", "output")


class StrictToolInput(BaseModel):
    """写类工具入参共享基类（批 4b，T2 第二步）：extra="forbid" 单一事实源。

    Pydantic 机制层拒收未声明字段，与 manager.detect_unknown_fields（批 4a，
    先于校验给出字段清单文案）构成双保险：即便绕过 manager 直调
    model_validate 也拦得住。只读/交互控制面工具入参与 extra="allow"
    自由入参模型（MCP 适配器等）不继承本基类，豁免路径不变。
    """
    model_config = ConfigDict(extra="forbid")


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
    - error_code: 结构化错误轴（T5）——失败路径的分类码，与
      core/fc_feedback.classify_tool_failure 口径对齐：validation=参数校验失败；
      exception=未捕获异常兜底；upstream=上游/生成失败；timeout=超时；
      canvas=画布读写失败；空串=未标注（消费端回落文本分类），成功结果恒为空。
    - retryable: 生产端标注该失败是否可重试（供失败回喂文案微调；默认 False）
    """
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    events: List[ToolEvent] = Field(default_factory=list)
    error_code: str = ""
    retryable: bool = False

class BaseTool(ABC):
    name: str = ""
    description: str = ""
    # 工具风险分级（宪法 §2.7）：low=只读/可逆；medium=写状态但可撤销；
    # high=生成/文档写入/跨阶段建结构/外部副作用。
    # 必须由子类显式声明；未声明者在 ToolManager.register 被拒绝注册
    # （deny-by-default，不得静默放行）。
    risk: str = ""
    # （F1 裁决 2026-08-31：approval_tier 独立声明轴退役——生效档由 risk
    # 单轴推导（high→confirm 确认只挂高危，其余自动过），见
    # ToolManager.get_tool_approval_tier。）
    # 前端时间线展示档：取值见 DETAIL_TIERS；空 = 未声明，
    # 前端默认 output（展示档非安全闸，不 deny-by-default，但声明优先）。
    detail_tier: str = ""
    # 花钱生成声明轴（Skill 系统修复批 B）：True = 花钱生成动作（生图/生视频）。
    # 执行偏好三档只对声明花钱的工具放宽确认闸；未声明者默认非花钱，
    # 偏好不放宽（不硬编码工具名单，数据驱动）；声明非 bool 值注册期拒收。
    costly: bool = False

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
