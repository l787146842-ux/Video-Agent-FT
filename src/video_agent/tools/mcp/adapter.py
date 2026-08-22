"""MCP 接入层：工具适配器（任务#37 B4 §2.5 adapter.py）。

McpToolAdapter 就是 BaseTool：复用 ToolManager.register（注册期 risk
强制校验同口径），name = mcp__<server>__<tool>（双下划线三段式）。

参数校验口径：远端 JSON Schema 存原始 dict，invoke 时按 required+type
最小自校验（零新依赖，与 sidecar 校验同款口径），不做 pydantic 动态建模；
get_input_schema 返回宽松模型保 ToolManager schema 装配链路不断。

deny-first 运行时面：未启用（interaction.mcp_enabled 白名单未含）的
MCP 工具即使被直调也拒执行——schema 不进 FC payload 只是第一道。
结果通道：单结果字符上限 settings.mcp_result_max_chars，超限截断附警告，
随后走既有 fc_feedback 回喂管线。
"""
import json
from typing import Any, Dict, Optional, Type

from loguru import logger
from pydantic import BaseModel, ConfigDict

from src.video_agent.config import settings
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.mcp import policy as mcp_policy
from src.video_agent.tools.mcp.client import BaseMcpClient, McpClientError

# description 注入上限（防远端超长描述撑爆 schema token）
DESCRIPTION_MAX_CHARS = 200

# JSON Schema type → Python 类型最小映射（只校验声明过的字段）
_TYPE_MAP: Dict[str, tuple] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


class _PermissiveInput(BaseModel):
    """宽松入参模型：参数原样透传，真校验在 aexecute 内按远端 schema 自校。"""

    model_config = ConfigDict(extra="allow")


class McpToolAdapter(BaseTool):
    """单个远端 MCP 工具的平台侧代理（risk 经 policy 解析，注册期声明）。"""

    def __init__(
        self,
        server: str,
        remote_tool: str,
        *,
        description: str = "",
        risk: str,
        remote_schema: Optional[Dict[str, Any]] = None,
        client: BaseMcpClient,
    ) -> None:
        self.server = mcp_policy.sanitize_name(server)
        self.remote_tool = str(remote_tool or "")
        self.name = mcp_policy.qualified_name(server, remote_tool)
        self.description = str(description or "").strip()[:DESCRIPTION_MAX_CHARS]
        self.risk = risk
        self.remote_schema = remote_schema if isinstance(remote_schema, dict) else {}
        self._client = client

    def get_input_schema(self) -> Type[BaseModel]:
        return _PermissiveInput

    # ---------- 参数最小自校验（required + type，零新依赖） ----------

    def validate_args(self, kwargs: Dict[str, Any]) -> Optional[str]:
        schema = self.remote_schema or {}
        props = schema.get("properties") if isinstance(schema, dict) else None
        props = props if isinstance(props, dict) else {}
        required = schema.get("required") if isinstance(schema, dict) else None
        required = [str(r) for r in required] if isinstance(required, list) else []
        missing = [r for r in required if r not in kwargs or kwargs[r] is None]
        if missing:
            return f"缺少必填参数: {', '.join(missing)}"
        for key, val in kwargs.items():
            decl = props.get(key)
            if not isinstance(decl, dict):
                continue
            expected = _TYPE_MAP.get(str(decl.get("type") or "").lower())
            if not expected or val is None:
                continue
            if isinstance(val, bool) and bool not in expected:
                return f"参数 '{key}' 类型不符（期望 {decl.get('type')}）"
            if not isinstance(val, expected):
                return f"参数 '{key}' 类型不符（期望 {decl.get('type')}）"
        return None

    # ---------- 执行 ----------

    async def aexecute(self, params: BaseModel) -> ToolResult:
        kwargs = params.model_dump() if hasattr(params, "model_dump") else {}
        # deny-first 运行时面：未在白名单（启用集）内的 MCP 工具拒执行
        if self.name not in mcp_policy.enabled_tool_names():
            return ToolResult(success=False, error=(
                f"MCP 工具 '{self.name}' 未启用（deny-first：外部工具默认拒绝）。"
                f"请先调用 mcp_tool_catalog(action=\"enable\", "
                f"tools=[\"{self.name}\"]) 启用后再调用。"))
        err = self.validate_args(kwargs)
        if err:
            return ToolResult(success=False, error=f"MCP 参数校验未通过：{err}")
        try:
            result = await self._client.call_tool(self.remote_tool, kwargs)
        except McpClientError as e:
            logger.warning(f"[mcp.adapter] {self.name} 调用失败: {e}")
            return ToolResult(success=False, error=(
                f"MCP 工具 '{self.name}' 执行失败（外部服务降级）: {e}"))
        except Exception as e:
            logger.warning(f"[mcp.adapter] {self.name} 未预期异常: {e}")
            return ToolResult(success=False, error=(
                f"MCP 工具 '{self.name}' 执行异常: {e}"))
        return _truncate_result(self.name, result)


def _truncate_result(name: str, result: Any) -> ToolResult:
    """结果通道预算：超 settings.mcp_result_max_chars 截断附警告（B4 §2.5）。"""
    limit = max(200, int(getattr(settings, "mcp_result_max_chars", 4000)))
    try:
        serialized = result if isinstance(result, str) else json.dumps(
            result, ensure_ascii=False, default=str)
    except Exception:
        serialized = str(result)
    if len(serialized) <= limit:
        return ToolResult(success=True, data={"result": result})
    logger.info(f"[mcp.adapter] {name} 结果超长（{len(serialized)} 字符）已截断")
    return ToolResult(success=True, data={
        "result": serialized[:limit],
        "truncated": True,
        "warnings": [
            f"MCP 结果超过 {limit} 字符上限，已截断（完整结果未回喂）"],
    })


# ---------- 注册表（catalog/接线消费的单一事实源） ----------

ADAPTERS: Dict[str, McpToolAdapter] = {}


def remember(adapter: McpToolAdapter) -> None:
    ADAPTERS[adapter.name] = adapter


def forget_all() -> None:
    ADAPTERS.clear()


def get_adapter(name: str) -> Optional[McpToolAdapter]:
    return ADAPTERS.get(name)
