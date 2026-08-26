from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel
from loguru import logger
from src.video_agent.adapters.cancel_token import GenerationCancelled
from .base import APPROVAL_TIERS, BaseTool, DETAIL_TIERS, RISK_TIERS, ToolResult

class ToolManager:
    _tools: Dict[str, BaseTool] = {}
    _schema_cache: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def register(cls, tool: BaseTool):
        if not tool.name:
            raise ValueError("Tool must have a valid 'name' attribute.")
        # 注册期强制校验风险分级（宪法 §2.7 deny-by-default）：
        # 未声明 risk 的工具直接拒绝注册，杜绝静默放行
        risk = str(getattr(tool, "risk", "") or "").strip().lower()
        if risk not in RISK_TIERS:
            logger.error(
                f"拒绝注册工具 '{tool.name}'：未声明风险分级 risk（宪法 §2.7，"
                "未声明视为 high，不得静默放行）"
            )
            raise ValueError(
                f"Tool '{tool.name}' must declare risk in {RISK_TIERS} "
                "per ARCHITECTURE_RULES §2.7 (deny-by-default)."
            )
        # 审批分级正交轴（任务 P2-5）：允许不声明（生效档按 risk 推导），
        # 但声明了非法取值同样拒收（注册校验强化，不静默放行）
        approval = str(getattr(tool, "approval_tier", "") or "").strip().lower()
        if approval and approval not in APPROVAL_TIERS:
            logger.error(
                f"拒绝注册工具 '{tool.name}'：approval_tier 取值非法（任务 P2-5，"
                f"合法枚举 {APPROVAL_TIERS}）"
            )
            raise ValueError(
                f"Tool '{tool.name}' declares invalid approval_tier {approval!r}; "
                f"must be one of {APPROVAL_TIERS}."
            )
        cls._tools[tool.name] = tool
        cls._schema_cache = None  # 注册新工具时失效缓存
        logger.debug(f"Registered tool: {tool.name} (risk={risk})")

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
    def get_tool_risk(cls, name: str) -> str:
        """工具声明的风险分级；未注册/未声明一律返回 high（deny-by-default，§2.7）。"""
        tool = cls._tools.get(name)
        risk = str(getattr(tool, "risk", "") or "").strip().lower() if tool else ""
        return risk if risk in RISK_TIERS else "high"

    @classmethod
    def get_tool_approval_tier(cls, name: str) -> str:
        """工具生效的审批分级（任务 P2-5 正交轴）：显式声明优先；
        未声明者按 risk 推导——high 默认 confirm（deny-by-default 同口径），
        其余默认 none；未注册工具按 high 口径一律 confirm。"""
        tool = cls._tools.get(name)
        if tool is None:
            return "confirm"
        tier = str(getattr(tool, "approval_tier", "") or "").strip().lower()
        if tier in APPROVAL_TIERS:
            return tier
        return "confirm" if cls.get_tool_risk(name) == "high" else "none"

    @classmethod
    def get_tool_approval_tiers(cls) -> Dict[str, str]:
        """全部已注册工具的生效审批分级（sidecar 导出的单一事实源，任务 P2-5）：
        显式声明与推导档统一收录，前端确认卡/审批交互按本表映射。"""
        return {name: cls.get_tool_approval_tier(name) for name in cls._tools}

    @classmethod
    def get_tool_detail_tiers(cls) -> Dict[str, str]:
        """全部已注册工具的前端时间线展示档（sidecar 导出的单一事实源）。

        仅收录显式声明 detail_tier 的工具；未声明者不入表，前端按默认档
        output 处理（新工具至少留输出痕迹，与 base.DETAIL_TIERS 注释同口径）。
        """
        out: Dict[str, str] = {}
        for name, tool in cls._tools.items():
            tier = str(getattr(tool, "detail_tier", "") or "").strip().lower()
            if tier in DETAIL_TIERS:
                out[name] = tier
        return out

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
        except GenerationCancelled:
            # 协作式取消不得被兜底吞咽：穿透上抛，收敛至 agent_loop 停止分支
            raise
        except Exception as e:
            logger.error(f"Error invoking tool {name}: {e}")
            return ToolResult(success=False, error=str(e))
