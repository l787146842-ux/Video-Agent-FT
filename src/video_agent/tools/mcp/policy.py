"""MCP 接入层：deny 规则、risk 解析与启用集读写。

政策单一源（用户裁决 2026-09-02；P1 唯一表述处，勿在别处复述）：
工具侧外部能力 = 黑名单模型（控制面 = deny 名单 deny_servers/deny_tools
+ server 级 risk_default + 审计遥测）+ 装载者审核责任——模型可自助启用
外部 MCP 工具、不逐次征求用户同意，「装坏了怪装载者没审核」是有意政策；
Skill 侧 = 白名单门户（须显式装载）。二者差异为有意设计，不是缺陷。

deny-first（宪法 §2.7 同口径，外部工具统一风控）：
- deny_servers（整批 deny）→ deny_tools（单个 deny）→ deny 命中的工具
  连注册都不进（fail-closed）；
- 未声明 risk 一律 high（执行前须用户显式确认）；
- 花钱/不可逆底线：costly 声明的外部工具 risk 地板恒为 high，server 级
  risk_default/tool_risk 只能向上抬、不得向下把 costly 工具静默降为无确认
  （见 resolve_tool_risk / resolve_tool_costly）；
- 未启用的 MCP 工具默认不可用：schema 不进 FC payload，直调也被拒。

启用集（interaction.mcp_enabled）= 会话级已启用集（模型自助写入的注入
可见性面，非用户审批门户）：mcp_tool_catalog enable 写入后，次回合
planner 才把这些工具的完整 schema 注入 FC tools。
本模块保持轻依赖（纯判定 + 状态读写），供 fc_gates 闸机接线直接引用。
"""
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import RISK_TIERS

# 全限定命名空间：mcp__<server>__<tool>（双下划线三段式，业界事实标准）
MCP_TOOL_PREFIX = "mcp__"
# 目录/启停内置工具名（平台工具，不占用 mcp__ 命名空间）
CATALOG_TOOL_NAME = "mcp_tool_catalog"
# 未声明 risk 的兜底等级（deny-by-default：外部工具不可信）
DEFAULT_RISK = "high"
# 花钱/不可逆底线（用户裁决 2026-09-02）：costly 声明的外部工具 risk 地板
# 恒为 high（→ 生效审批档 confirm）；server 级 risk_default/tool_risk 只能
# 向上抬，不得向下把 costly 工具静默降为无确认。
COSTLY_RISK_FLOOR = "high"
# 名称净化：FC 工具名只保留 [a-z0-9_]（server/tool 名注册期 sanitize）
_NAME_SAFE_RE = re.compile(r"[^a-z0-9_]+")

# 会话级启用集在状态树中的位置（单次写入经 StateManager 持久化）
_ENABLED_KEY = "mcp_enabled"


def is_mcp_tool(name: str) -> bool:
    """是否为 MCP 外部工具（命名空间判定唯一出口，fc_gates 风险闸消费）。"""
    return str(name or "").startswith(MCP_TOOL_PREFIX)


def sanitize_name(raw: str) -> str:
    """server/tool 名净化为 [a-z0-9_]（非法字符折叠为单下划线，首尾去空）。"""
    s = _NAME_SAFE_RE.sub("_", str(raw or "").strip().lower())
    return s.strip("_")


def qualified_name(server: str, tool: str) -> str:
    """全限定工具名 mcp__<server>__<tool>（两侧均 sanitize）。"""
    return f"{MCP_TOOL_PREFIX}{sanitize_name(server)}__{sanitize_name(tool)}"


def parse_server_key(entry: str) -> Optional[str]:
    """从全限定名解析 server 段；非 MCP 命名返回 None。"""
    if not is_mcp_tool(entry):
        return None
    parts = entry.split("__")
    return parts[1] if len(parts) >= 3 and parts[1] else None


def resolve_tool_costly(server_cfg: Dict[str, Any], tool_name: str) -> bool:
    """外部工具花钱/不可逆声明（server_cfg.tool_costly 单工具映射，与
    tool_risk 同款结构）。仅显式真值算数；未声明/非法一律 False（不误抬
    也不放宽）。声明为 costly 者其 risk 地板恒为 high（见 resolve_tool_risk），
    server 配置只能上抬、不得向下取消确认。"""
    cfg = server_cfg if isinstance(server_cfg, dict) else {}
    per_tool = cfg.get("tool_costly")
    if isinstance(per_tool, dict):
        return bool(per_tool.get(tool_name))
    return False


def resolve_tool_risk(server_cfg: Dict[str, Any], tool_name: str) -> str:
    """risk 解析（fail-closed）：tool_risk 单工具声明 > risk_default 服务器
    默认 > high。非法取值一律按 high 对待（外部工具不可信，禁止静默放行）。
    花钱/不可逆底线（用户裁决 2026-09-02）：costly 工具 risk 地板恒为
    high——server 级 risk_default/tool_risk 只能向上抬，不得向下把 costly
    工具静默降为无确认（控制面仍是 deny 名单 + server 配置 + 遥测）。"""
    cfg = server_cfg if isinstance(server_cfg, dict) else {}
    declared = ""
    per_tool = cfg.get("tool_risk")
    if isinstance(per_tool, dict):
        declared = str(per_tool.get(tool_name) or "").strip().lower()
    if not declared:
        declared = str(cfg.get("risk_default") or "").strip().lower()
    risk = DEFAULT_RISK
    if declared:
        risk = declared if declared in RISK_TIERS else DEFAULT_RISK
    # 花钱/不可逆底线：costly 工具地板 high（只升不降，堵 server 静默降级）
    if resolve_tool_costly(cfg, tool_name):
        risk = COSTLY_RISK_FLOOR
    return risk


def is_server_denied(policy: Dict[str, Any], server_name: str) -> bool:
    """整批 deny 判定：deny_servers 命中原始名或净化名即拒。"""
    deny = _deny_list(policy, "deny_servers")
    if not deny:
        return False
    safe = sanitize_name(server_name)
    for entry in deny:
        if entry == server_name or sanitize_name(entry) == safe:
            return True
    return False


def is_tool_denied(policy: Dict[str, Any], name: str) -> bool:
    """单个 deny 判定：deny_tools 命中全限定名（mcp__server__tool）即拒。"""
    deny = _deny_list(policy, "deny_tools")
    if not deny:
        return False
    safe = sanitize_name(name) if is_mcp_tool(name) else str(name)
    for entry in deny:
        entry = str(entry or "").strip()
        if not entry:
            continue
        if entry == name or (is_mcp_tool(entry) and sanitize_name(entry) == safe):
            return True
    return False


def max_active_tools(policy: Dict[str, Any]) -> int:
    """活动工具上限：policy.max_active_tools 覆写 settings 默认值。"""
    try:
        n = int((policy or {}).get("max_active_tools") or 0)
    except (TypeError, ValueError):
        n = 0
    return n if n > 0 else int(getattr(settings, "mcp_max_active_tools", 8))


def _deny_list(policy: Dict[str, Any], key: str) -> List[str]:
    val = (policy or {}).get(key)
    if not isinstance(val, (list, tuple)):
        return []
    return [str(v).strip() for v in val if str(v or "").strip()]


# ---------- 启用集（白名单）读写 ----------

def _state_dict(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """未显式提供 state 时读当前 StateManager（读失败保守返回空）。"""
    if state is not None:
        return state
    try:
        return StateManager.get_instance().state_dict
    except Exception:
        return {}


def enabled_tool_names(state: Optional[Dict[str, Any]] = None) -> Set[str]:
    """当前会话已启用的 MCP 工具全限定名集合（deny-first 的白名单面）。"""
    inter = _state_dict(state).get("interaction") or {}
    raw = inter.get(_ENABLED_KEY)
    if not isinstance(raw, (list, tuple)):
        return set()
    return {str(n) for n in raw if is_mcp_tool(str(n or ""))}


def write_enabled_tools(
    names: Iterable[str],
    state: Optional[Dict[str, Any]] = None,
    *,
    save: bool = True,
) -> None:
    """启用集整体落状态树（interaction.mcp_enabled；只保留 mcp__ 命名）。"""
    cleaned = sorted({str(n) for n in names if is_mcp_tool(str(n or ""))})
    svc_state = _state_dict(state)
    try:
        inter = svc_state.setdefault("interaction", {})
        inter[_ENABLED_KEY] = cleaned
        if save and state is None:
            StateManager.get_instance().save()
    except Exception as e:
        logger.debug(f"[mcp.policy] 启用集写入忽略异常: {e}")
