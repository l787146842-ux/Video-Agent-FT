"""MCP 接入层：目录工具与两段式注入。

懒加载/目录摘要策略（两阶段，防上下文膨胀）：
- 阶段 1（system prompt 常驻）：catalog_block() 只给「外部工具目录」
  文本块——server 名 + 工具名列表 + 单句摘要；schema 不进 FC tools。
- 阶段 2（按需）：模型调 mcp_tool_catalog(action="enable") 写入
  interaction.mcp_enabled（会话级白名单）→ 次回合 planner 把这些工具
  的完整 schema 注入 FC tools（_compute_excluded_tools 消费
  inactive_tool_names()）；活动工具数超上限时结构化拒收引导 disable。
"""
from typing import Any, Dict, List, Optional, Set

from loguru import logger
from pydantic import BaseModel, Field

from src.video_agent.config import settings
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.mcp import policy as mcp_policy
from src.video_agent.tools.mcp.adapter import ADAPTERS, get_adapter

_ALLOWED_ACTIONS = ("list", "detail", "enable", "disable")

# 注册期加载的 policy 配置上下文（register_mcp_tools 写入 / unregister 清空）：
# 目录工具的上限判定消费真实配置
_POLICY_CFG: Dict[str, Any] = {}


def set_policy_cfg(cfg: Optional[Dict[str, Any]]) -> None:
    """注册期 policy 配置注入（非 dict 一律归零为空配置）。"""
    global _POLICY_CFG
    _POLICY_CFG = cfg if isinstance(cfg, dict) else {}


class McpCatalogInput(BaseModel):
    action: str = Field(
        default="list",
        description="list=目录总览；detail=查看指定工具完整 schema；"
                    "enable=启用（次回合注入 schema）；disable=停用")
    tools: List[str] = Field(
        default_factory=list,
        description="全限定工具名列表（mcp__<server>__<tool>），detail/enable/disable 用")


class McpToolCatalogTool(BaseTool):
    """外部工具目录与启停闸口（平台工具：只改白名单，不产生外部副作用）。"""

    name = mcp_policy.CATALOG_TOOL_NAME
    description = (
        "MCP 外部工具目录：action=list 查看可用外部工具；action=detail 查看"
        "指定工具完整参数；action=enable 启用工具（次回合其 schema 才可用）；"
        "action=disable 停用。外部工具默认拒绝，必须先 enable 再调用。")
    risk = "low"
    detail_tier = "output"  # 平台闸口：仅输出留痕

    def get_input_schema(self):
        return McpCatalogInput

    async def aexecute(self, params: McpCatalogInput) -> ToolResult:
        action = str(params.action or "list").strip().lower()
        wanted = [str(t).strip() for t in (params.tools or []) if str(t or "").strip()]
        if action not in _ALLOWED_ACTIONS:
            return ToolResult(success=False, error=(
                f"未知 action '{action}'，可选：{', '.join(_ALLOWED_ACTIONS)}"))
        if action == "list":
            return _action_list()
        if action == "detail":
            return _action_detail(wanted)
        if action == "enable":
            return _action_enable(wanted)
        return _action_disable(wanted)


def _action_list() -> ToolResult:
    enabled = mcp_policy.enabled_tool_names()
    servers: Dict[str, List[Dict[str, Any]]] = {}
    for name, ad in ADAPTERS.items():
        servers.setdefault(ad.server, []).append({
            "name": name,
            "description": ad.description,
            "risk": ad.risk,
            "enabled": name in enabled,
        })
    return ToolResult(success=True, data={
        "servers": servers,
        "max_active_tools": mcp_policy.max_active_tools(_POLICY_CFG),
        "hint": "enable 后次回合工具 schema 才会注入；high 级工具执行前需用户确认",
    })


def _action_detail(wanted: List[str]) -> ToolResult:
    if not wanted:
        return ToolResult(success=False, error="detail 需要 tools 参数（全限定工具名）")
    details, missing = [], []
    for name in wanted:
        ad = get_adapter(name)
        if ad is None:
            missing.append(name)
            continue
        details.append({
            "name": ad.name,
            "description": ad.description,
            "risk": ad.risk,
            "parameters": ad.remote_schema or {},
        })
    data: Dict[str, Any] = {"tools": details}
    if missing:
        data["unknown"] = missing
    return ToolResult(success=bool(details), data=data,
                      error="未找到任何指定工具" if not details else None)


def _action_enable(wanted: List[str]) -> ToolResult:
    if not wanted:
        return ToolResult(success=False, error="enable 需要 tools 参数（全限定工具名）")
    unknown = [t for t in wanted if get_adapter(t) is None]
    valid = [t for t in wanted if get_adapter(t) is not None]
    if not valid:
        return ToolResult(success=False, error=(
            f"没有可启用的工具（未注册或被 deny）：{', '.join(unknown)}"))
    current = mcp_policy.enabled_tool_names()
    merged = sorted(current | set(valid))
    limit = mcp_policy.max_active_tools(_POLICY_CFG)
    if len(merged) > limit:
        return ToolResult(success=False, error=(
            f"活动 MCP 工具数将达 {len(merged)} 个，超过上限 {limit}。"
            f"请先 mcp_tool_catalog(action=\"disable\") 停用不再需要的工具。"))
    mcp_policy.write_enabled_tools(merged)
    logger.info(f"[mcp.catalog] 启用 MCP 工具: {valid}")
    data: Dict[str, Any] = {
        "enabled": sorted(valid),
        "active": merged,
        "hint": "次回合起这些工具的完整 schema 注入 FC tools，届时可直接调用",
    }
    if unknown:
        data["unknown"] = unknown
    return ToolResult(success=True, data=data)


def _action_disable(wanted: List[str]) -> ToolResult:
    if not wanted:
        return ToolResult(success=False, error="disable 需要 tools 参数（全限定工具名）")
    current = mcp_policy.enabled_tool_names()
    remaining = sorted(current - set(wanted))
    mcp_policy.write_enabled_tools(remaining)
    return ToolResult(success=True, data={
        "disabled": sorted(current & set(wanted)),
        "active": remaining,
    })


# ---------- 两段式注入的接线出口 ----------

def catalog_block(state: Optional[Dict[str, Any]] = None) -> str:
    """阶段 1 文本块：server 名 + 工具名 + 单句摘要（预算 ~50 token/server）。

    无已注册 MCP 工具时返回空串（不注入，零预设）。schema 不进 FC tools：
    未启用工具的裁剪由 planner 消费 inactive_tool_names()。
    """
    if not ADAPTERS or not bool(getattr(settings, "mcp_enabled", True)):
        return ""
    enabled = mcp_policy.enabled_tool_names(state)
    lines: List[str] = ["外部工具目录（MCP，外部来源默认拒绝、按需启用）："]
    by_server: Dict[str, List[str]] = {}
    desc_by_server: Dict[str, str] = {}
    for name, ad in ADAPTERS.items():
        mark = "✓" if name in enabled else ""
        by_server.setdefault(ad.server, []).append(f"{name}{mark}")
        if ad.description and not desc_by_server.get(ad.server):
            desc_by_server[ad.server] = ad.description.split("\n")[0][:60]
    for server, names in by_server.items():
        desc = desc_by_server.get(server) or ""
        lines.append(f"- {server}: {', '.join(names)}" + (f"（{desc}）" if desc else ""))
    lines.append(
        "需要时先调用 mcp_tool_catalog(action=\"enable\", tools=[...]) 启用，"
        "次回合工具 schema 注入后方可调用；high 级外部工具执行前须经用户确认。")
    return "\n".join(lines)


def inactive_tool_names(state: Optional[Dict[str, Any]] = None) -> "frozenset[str]":
    """未启用的 MCP 工具名集合（planner 裁剪：schema 不进 FC payload）。

    deny-first 的可见性面：未白名单放行前对模型不可调用。
    """
    if not ADAPTERS:
        return frozenset()
    enabled = mcp_policy.enabled_tool_names(state)
    return frozenset(n for n in ADAPTERS if n not in enabled)
