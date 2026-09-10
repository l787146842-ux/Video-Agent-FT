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
    # 旧 `executor` 行经 migrate_legacy_roles 归入 `subagent`（非法档位清洗）
    assert out["subagent"] == {"provider": "p2", "model": "", "thinking_level": ""}
    assert "executor" not in out
    assert "evil_role" not in out
    assert "orchestration" not in out


def test_migrate_legacy_roles():
    # 旧 executor 行 → subagent；新键已配则旧键让位；无关键原样
    assert mp.migrate_legacy_roles({"executor": {"provider": "p"}}) == {
        "subagent": {"provider": "p"}}
    assert mp.migrate_legacy_roles({
        "executor": {"provider": "old"}, "subagent": {"provider": "new"},
    }) == {"subagent": {"provider": "new"}}
    assert mp.migrate_legacy_roles({"summary": {"provider": "s"}}) == {
        "summary": {"provider": "s"}}


def test_b8_resolve_role_and_thinking_fallback():
    _set_policy({
        "subagent": {"provider": "p1", "model": "fast", "thinking_level": "low"},
        "summary": {"provider": "p2", "model": "cheap"},
    })
    try:
        assert mp.resolve_role("subagent") == {
            "provider": "p1", "model": "fast", "thinking_level": "low",
        }
        assert mp.resolve_role("orchestration") is None  # 未配置 = 跟随主模型
        assert mp.thinking_for("summary", "medium") == "medium"  # 策略无档位 → fallback
        assert mp.thinking_for("subagent", "high") == "low"      # 策略档位优先
    finally:
        _restore_policy()


# test_b8_cascade_fast_prefers_policy_executor（executors._resolve_cascade_fast
# 快模型级联优先策略表）已随任务#36 B5 执行器一步退役删除；
# executor 角色策略行本身保留（前端设置页契约，与 STAGE_LABELS 同裁决）。


# ---------- audit-0819f：档位独立于供应商 + 通用搭配默认 ----------

def test_0819f_thinking_only_row_kept_and_effective():
    """补洞：跟随主模型也可单独定档（旧实现无 provider 即丢弃整行）"""
    out = mp.normalize_policy({"subagent": {"provider": "", "thinking_level": "high"}})
    assert out["subagent"]["thinking_level"] == "high"
    _set_policy(out)
    try:
        assert mp.thinking_for("subagent") == "high"
        # 路由语义不变：无 provider 仍不接管模型路由
        assert mp.resolve_role("subagent") is None
    finally:
        _restore_policy()


def test_0819f_universal_defaults_summary_low_subagent_follows():
    """通用搭配（用户裁决）：摘要默认 low；子代理缺省跟随主模型（不预置降档，
    与「思考必须展示」一致）；编排/生成默认原生。"""
    _restore_policy()
    assert mp.thinking_for("subagent") == ""      # 无预置降档 = 跟随主模型
    assert mp.thinking_for("summary") == "low"
    assert mp.thinking_for("orchestration") == ""
    assert mp.thinking_for("generation_strong") == ""
    # UI 所见即生效：current_policy 含摘要 low 默认；子代理无预置降档（跟随主模型）
    cur = mp.current_policy()
    assert cur["summary"]["thinking_level"] == "low"
    assert cur["subagent"].get("thinking_level", "") == ""


def test_0819f_user_policy_overrides_default():
    _set_policy({"subagent": {"provider": "", "model": "", "thinking_level": "high"}})
    try:
        assert mp.thinking_for("subagent") == "high"
        assert mp.current_policy()["subagent"]["thinking_level"] == "high"
    finally:
        _restore_policy()
