"""B8 回归：模型分层策略表——四角色解析/清洗/路由优先级。"""
from src.video_agent.config import settings
from src.video_agent.core import model_policy as mp


def _set_policy(policy: dict):
    object.__setattr__(settings, "model_policy", policy)


def _restore_policy():
    object.__setattr__(settings, "model_policy", {})


def test_b8_normalize_policy_whitelist():
    out = mp.normalize_policy({
        "summary": {"provider": "p1", "model": "m1", "thinking_level": "low"},
        "executor": {"provider": "p2", "model": "", "thinking_level": "BOGUS"},
        "evil_role": {"provider": "p3"},
        "orchestration": "not-a-dict",
    })
    assert out["summary"] == {"provider": "p1", "model": "m1", "thinking_level": "low"}
    assert out["executor"] == {"provider": "p2", "model": "", "thinking_level": ""}  # 非法档位清洗
    assert "evil_role" not in out
    assert "orchestration" not in out


def test_b8_resolve_role_and_thinking_fallback():
    _set_policy({
        "executor": {"provider": "p1", "model": "fast", "thinking_level": "low"},
        "summary": {"provider": "p2", "model": "cheap"},
    })
    try:
        assert mp.resolve_role("executor") == {
            "provider": "p1", "model": "fast", "thinking_level": "low",
        }
        assert mp.resolve_role("orchestration") is None  # 未配置 = 跟随主模型
        assert mp.thinking_for("summary", "medium") == "medium"  # 策略无档位 → fallback
        assert mp.thinking_for("executor", "high") == "low"      # 策略档位优先
    finally:
        _restore_policy()


def test_b8_cascade_fast_prefers_policy_executor():
    from src.video_agent.skill_runtime.executors import _resolve_cascade_fast

    _set_policy({"executor": {"provider": "polP", "model": "polM"}})
    try:
        prov, model = _resolve_cascade_fast("mainP", "mainM")
        assert (prov, model) == ("polP", "polM")
    finally:
        _restore_policy()
