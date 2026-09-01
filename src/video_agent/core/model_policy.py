"""：模型分层策略表——编排/生成/摘要/执行器四角色自动路由的单一事实源。

业界对标（模型分层 + Codex/DSH 模型路由实践；原对标卷见 git tag `governance-archive-20260901` §13.9）：
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

# 通用搭配默认：
# 摘要/执行器机械 = 照章办事的结构化产出，不需要深推理——低档防思考
# 吃光输出预算（根因）；编排/生成跟随主模型全力。用户可在全局
# 设置页覆盖（UI 可见可改）。
DEFAULT_POLICY: Dict[str, Dict[str, str]] = {
    "summary": {"provider": "", "model": "", "thinking_level": "low"},
    "executor": {"provider": "", "model": "", "thinking_level": "low"},
}


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
    """角色思考档位：用户配置 > env 覆写（调用方 fallback）
    > 通用搭配默认；**不要求 provider 已设**（跟随主模型也可单独定档）。
    """
    entry = _policy().get(role) or {}
    level = str(entry.get("thinking_level") or "").strip().lower()
    if level and level in _THINKING_VALUES:
        return level
    fb = str(fallback or "").strip().lower()
    if fb and fb in _THINKING_VALUES:
        return fb
    return str((DEFAULT_POLICY.get(role) or {}).get("thinking_level") or "")


def effective_policy() -> Dict[str, Dict[str, str]]:
    """通用搭配默认 + 用户配置叠加：用户值非空即覆盖默认。
    供 current_policy（UI 渲染）与 thinking_for 共用——UI 所见即生效。"""
    out: Dict[str, Dict[str, str]] = {
        r: dict(v) for r, v in DEFAULT_POLICY.items()
    }
    for role, entry in _policy().items():
        cur = out.setdefault(role, {})
        for key, val in (entry or {}).items():
            if str(val or "").strip():
                cur[key] = val
    return out


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
        if cleaned.get("provider") or cleaned.get("thinking_level"):
            # 档位可独立于供应商设置（跟随主模型也可定档）
            out[role] = cleaned
    return out


def current_policy() -> Dict[str, Dict[str, str]]:
    """当前生效策略（供 /api/settings/runtime 返回与前端渲染；：
    含通用搭配默认，UI 所见即生效）。"""
    return effective_policy()
