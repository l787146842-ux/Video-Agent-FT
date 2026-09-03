from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError
from loguru import logger
from src.video_agent.utils.cancel_token import GenerationCancelled
from .base import BaseTool, DETAIL_TIERS, PROVIDER_KINDS, RISK_TIERS, ToolResult


def detect_unknown_fields(schema_class: Type[BaseModel], kwargs: Dict[str, Any]) -> List[str]:
    """model_validate 前的未知字段检测（T2 第一步「错误可见」，模块级纯函数）。

    Pydantic v2 默认 extra='ignore'：未知字段被静默丢弃且不产生 ValidationError，
    必须在校验前主动比对键集。返回排序后的被丢弃字段名列表，便于单测与文案渲染。
    """
    if not isinstance(kwargs, dict):
        return []
    return sorted(set(kwargs) - set(schema_class.model_fields))


def format_validation_error(exc: ValidationError, schema_class: Type[BaseModel]) -> str:
    """ValidationError 字段级渲染：解析 loc/type/msg 生成可读清单（替换裸 str(e)），
    并附该 schema 合法字段清单，帮助模型一次改对。"""
    lines: List[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in (err.get("loc") or ()) if str(p) != "__root__")
        msg = str(err.get("msg") or "").strip()
        etype = str(err.get("type") or "")
        lines.append(f"- {loc or '(root)'}: {msg} ({etype})")
    detail = "\n".join(lines) if lines else str(exc)
    allowed = ", ".join(schema_class.model_fields)
    return f"Validation Error: 入参校验失败，请修正以下字段后重试：\n{detail}\n合法字段: {allowed}"


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
        # （F1 裁决 2026-08-31：approval_tier 独立声明轴退役——生效档由 risk 单轴推导，
        # 注册期不再校验审批声明。）
        # 花钱生成声明轴（批 B）：允许不声明（默认非花钱，偏好不放宽），
        # 但声明了非 bool 取值同样拒收（注册期校验，不静默放行）
        costly = getattr(tool, "costly", False)
        if not isinstance(costly, bool):
            logger.error(
                f"拒绝注册工具 '{tool.name}'：costly 取值非法（仅支持 bool，"
                "Skill 系统修复批 B 花钱生成声明轴）"
            )
            raise ValueError(
                f"Tool '{tool.name}' declares invalid costly {costly!r}; must be bool."
            )
        # Provider 注入声明轴（I-3 裁决 2026-09-03）：允许不声明（默认无需注入），
        # 但声明了非法取值（不在 PROVIDER_KINDS）同样拒收（注册期校验，不静默放行）
        provider_kind = str(getattr(tool, "provider_kind", "") or "").strip()
        if provider_kind and provider_kind not in PROVIDER_KINDS:
            logger.error(
                f"拒绝注册工具 '{tool.name}'：provider_kind 取值非法（仅支持 {PROVIDER_KINDS} 或空，"
                "I-3 provider 注入声明轴）"
            )
            raise ValueError(
                f"Tool '{tool.name}' declares invalid provider_kind {provider_kind!r}; "
                f"must be one of {PROVIDER_KINDS} or empty."
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
        """工具生效的审批档（F1 裁决 2026-08-31 双轴并单轴：由 risk 单轴推导，
        确认只挂高危）：high → confirm；low/medium → none（自动过）；
        未注册工具按最严口径 confirm（deny-by-default，未声明=最严）。"""
        tool = cls._tools.get(name)
        if tool is None:
            return "confirm"
        return "confirm" if cls.get_tool_risk(name) == "high" else "none"

    @classmethod
    def get_tool_approval_tiers(cls) -> Dict[str, str]:
        """全部已注册工具的生效审批档（sidecar 导出的单一事实源）：
        risk 单轴推导档统一收录，前端确认卡/审批交互按本表映射。"""
        return {name: cls.get_tool_approval_tier(name) for name in cls._tools}

    @classmethod
    def is_costly_tool(cls, name: str) -> bool:
        """工具是否花钱生成（批 B costly 声明轴）：仅显式声明 True 者算数。
        未声明者默认非花钱（执行偏好不放宽其确认闸）；未注册工具同判非花钱，
        照 high 口径兜底拦截（兜底语义零改动，偏好不放宽未注册者）。"""
        tool = cls._tools.get(name)
        if tool is None:
            return False
        return bool(getattr(tool, "costly", False))

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
            
            # T2 第一步「错误可见」：Pydantic v2 默认 extra='ignore' 会静默丢弃未知字段，
            # model_validate 前主动比对键集，非空即拒收（对全部工具生效，新工具自动继承）。
            # 平台容忍路径：显式声明 extra='allow' 的自由入参模型（如 MCP 适配器，
            # 参数按远端 JSON Schema 自校验）与零声明字段模型不参与比对。
            extra_mode = schema_class.model_config.get("extra", "ignore")
            if extra_mode != "allow" and schema_class.model_fields:
                unknown = detect_unknown_fields(schema_class, kwargs)
                if unknown:
                    allowed = ", ".join(schema_class.model_fields)
                    return ToolResult(
                        success=False,
                        error=(f"Validation Error: 入参含未知字段（已拒收，未执行）: "
                               f"{', '.join(unknown)}；该工具合法字段: {allowed}"),
                        error_code="validation", retryable=False,
                    )

            # Pydantic validation
            try:
                params = schema_class.model_validate(kwargs)
            except ValidationError as e:
                # T5 结构化错误轴：入参校验失败不可用原参重试，须改参（字段级渲染）
                return ToolResult(
                    success=False, error=format_validation_error(e, schema_class),
                    error_code="validation", retryable=False,
                )
            except Exception as e:
                # 非 pydantic 校验异常兜底，保持 validation 口径不变
                return ToolResult(
                    success=False, error=f"Validation Error: {str(e)}",
                    error_code="validation", retryable=False,
                )

            return await tool.aexecute(params)
        except GenerationCancelled:
            # 协作式取消不得被兜底吞咽：穿透上抛，收敛至 agent_loop 停止分支
            raise
        except Exception as e:
            logger.error(f"Error invoking tool {name}: {e}")
            # T5 结构化错误轴：未捕获异常兜底（未标可重试，重试与否留待回喂侧判断）
            return ToolResult(success=False, error=str(e), error_code="exception")
