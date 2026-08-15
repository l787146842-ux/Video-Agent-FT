"""B8：模型分层策略表——编排/生成/摘要/执行器四角色自动路由的单一事实源。

业界对标（13.9 模型分层 + Codex/DSH 模型路由实践）：
- orchestration  主对话/规划（跟随主模型；策略仅作显式覆盖）
- generation_strong  执行器长文生成/纠正升级（缺省跟随主模型）
- summary       记忆摘要/会话压缩（便宜模型，缺省回落链末位）
- executor      执行器机械调用/誊写批快模型（缺省 settings.executor_fast_model）

策略存于 data/runtime_settings.json 的 model_policy 节，经 /api/settings/runtime
热更新生效；角色取值 {"provider","model","thinking_level"}，未配置 = 跟随主模型。
"""
from typing import Any, Dict, Optional

ROLES = ("orchestration", "generation_strong", "summary", "executor")
_ROLE_KEYS = ("provider", "model", "thinking_level")
_THINKING_VALUES = ("", "low", "medium", "high")


def _policy() -> Dict[str, Dict[str, str]]:
    from src.video_agent.config import settings

    p = getattr(settings, "model_policy", None) or {}
    if not isinstance(p, dict):
        return {}
    return {r: (p.get(r) or {}) for r in ROLES if isinstance(p.get(r) or {}, dict)}


def resolve_role(role: str) -> Optional[Dict[str, str]]:
    """返回角色策略 {provider, model, thinking_level}；未配置返回 None（跟随主模型）。"""
    if role not in ROLES:
        return None
    entry = _policy().get(role) or {}
    provider = str(entry.get("provider") or "").strip()
    if not provider:
        return None
    model = str(entry.get("model") or "").strip()
    level = str(entry.get("thinking_level") or "").strip().lower()
    return {
        "provider": provider,
        "model": model,
        "thinking_level": level if level in _THINKING_VALUES else "",
    }


def thinking_for(role: str, fallback: str = "") -> str:
    """角色思考档位：策略值优先，未配置回落调用方给的 fallback（如 settings.aux_thinking_level）。"""
    entry = resolve_role(role)
    if entry and entry["thinking_level"]:
        return entry["thinking_level"]
    return fallback or ""


def normalize_policy(payload: Any) -> Dict[str, Dict[str, str]]:
    """清洗前端提交的策略对象（结构白名单：4 角色 × 3 键）。"""
    out: Dict[str, Dict[str, str]] = {}
    if not isinstance(payload, dict):
        return out
    for role in ROLES:
        entry = payload.get(role)
        if not isinstance(entry, dict):
            continue
        cleaned: Dict[str, str] = {}
        for key in _ROLE_KEYS:
            val = str(entry.get(key) or "").strip()
            if key == "thinking_level":
                cleaned[key] = val.lower() if val.lower() in _THINKING_VALUES else ""
            else:
                cleaned[key] = val
        if cleaned.get("provider"):
            out[role] = cleaned
    return out


def current_policy() -> Dict[str, Dict[str, str]]:
    """当前生效策略（供 /api/settings/runtime 返回与前端渲染）。"""
    return {role: (_policy().get(role) or {}) for role in ROLES}
