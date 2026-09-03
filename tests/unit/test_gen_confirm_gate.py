"""B4 双轨收敛一期回归：生成确认闸单一实现。

事故溯源：三轮审核 B4（双轨镜像漂移——FC 全拒 vs 文本轨跳过未确认项）。
收敛落点：core/guard_pipeline.evaluate_gen_confirm（唯一实现）。
Q2 裁决 2026-09-01：文本轨随执行器家族退役，动作通道唯一 = FC，
原双轨逐字节对照用例改为单轨（FC 适配器 + 唯一实现）钉死。
批 B：执行偏好三档前置分支也归该唯一实现（默认档行为与现状逐字节一致）。
"""
from src.video_agent.config import settings
from src.video_agent.core import fc_gates, guard_pipeline
from src.video_agent.core.tracer import AgentTracer

CONF = {"id": "d1", "prompt": "x", "tag": "已确认"}
UNCONF = {"id": "d2", "prompt": "y", "tag": "Agent"}


def _fc_ctx(state, override=False, injected_skill="some-skill"):
    return fc_gates.GateContext(
        state=lambda: state, gate_override=override,
        injected_skill=injected_skill)


def test_shared_block_on_any_unconfirmed():
    err, warns = guard_pipeline.evaluate_gen_confirm([CONF, UNCONF], active=True)
    assert err and "生成确认闸拦截" in err
    assert warns == [err]


def test_shared_pass_all_confirmed():
    err, warns = guard_pipeline.evaluate_gen_confirm([CONF], active=True)
    assert err is None and warns == []


def test_shared_override_pass_with_warning():
    err, warns = guard_pipeline.evaluate_gen_confirm([UNCONF], active=True, override="all")
    assert err is None and warns and "坚持" in warns[0]


def test_shared_inactive_or_empty_pass():
    err, warns = guard_pipeline.evaluate_gen_confirm([UNCONF], active=False)
    assert err is None and warns == []
    err, warns = guard_pipeline.evaluate_gen_confirm([], active=True)
    assert err is None and warns == []


def test_fc_adapter_matches_shared_semantics(monkeypatch):
    """FC 适配器与唯一实现同语义（Q2 后动作通道唯一 = FC，宪法 Rule 2）。"""
    monkeypatch.setattr("src.video_agent.core.prompt_gates.gate_mode", lambda: "strict")

    # 拦截场景：存在未确认草稿 → 硬拒 + 警告（唯一实现口径，见上方共用用例）
    state = {"keyElements": [{"drafts": [CONF, UNCONF]}]}
    ctx = _fc_ctx(state)
    fc_err = fc_gates.gen_confirm_gate(ctx, "image_generate", {"target": "all_keyElements"})
    assert fc_err is not None
    assert ctx.warnings and "生成确认闸拦截" in ctx.warnings[0]

    # 放行场景：全部已确认 → 放行且无警告
    ctx2 = _fc_ctx({"keyElements": [{"drafts": [CONF]}]})
    assert fc_gates.gen_confirm_gate(
        ctx2, "image_generate", {"target": "all_keyElements"}) is None
    assert ctx2.warnings == []

    # 豁免场景：override → 放行且豁免警告与唯一实现一致（同文案）
    ctx3 = _fc_ctx(state, override="all")
    assert fc_gates.gen_confirm_gate(
        ctx3, "image_generate", {"target": "all_keyElements"}) is None
    err_shared, warns_shared = guard_pipeline.evaluate_gen_confirm(
        [CONF, UNCONF], active=True, override="all")
    assert err_shared is None and ctx3.warnings == warns_shared


# ---------- 批 B：执行偏好三档前置分支（唯一实现内，双轨自动同语义） ----------

def _recent_gates():
    return AgentTracer.get_instance().get_recent_gates(20)


class TestExecPreferenceGenConfirm:
    """默认档 = 现状；非默认档放行必须代发同意并留痕（tracer 审计）。"""

    def test_default_pref_config_value_is_confirm_before_gen(self):
        assert settings.execution_preference == "confirm_before_gen"

    def test_default_pref_still_blocks_unconfirmed(self):
        err, warns = guard_pipeline.evaluate_gen_confirm([UNCONF], active=True)
        assert err and "生成确认闸拦截" in err and warns == [err]

    def test_generate_directly_passes_and_audited(self):
        old = settings.execution_preference
        object.__setattr__(settings, "execution_preference", "generate_directly")
        AgentTracer.reset()
        try:
            err, warns = guard_pipeline.evaluate_gen_confirm(
                [UNCONF], active=True, action="image_generate")
            assert err is None and warns and "直接生成" in warns[0]
            assert any(g["rule_id"] == "platform.gen_confirm"
                       and g["ok"] and g["overridden"] for g in _recent_gates()), \
                "偏好放行必须经 platform.gen_confirm verdict 留痕"
        finally:
            object.__setattr__(settings, "execution_preference", old)
            AgentTracer.reset()

    def test_generate_directly_passes_even_without_skill(self):
        old = settings.execution_preference
        object.__setattr__(settings, "execution_preference", "generate_directly")
        try:
            err, warns = guard_pipeline.evaluate_gen_confirm([UNCONF], active=False)
            assert err is None and warns and "直接生成" in warns[0]
        finally:
            object.__setattr__(settings, "execution_preference", old)

    def test_auto_decide_with_active_skill_passes(self):
        old = settings.execution_preference
        object.__setattr__(settings, "execution_preference", "auto_decide")
        try:
            err, warns = guard_pipeline.evaluate_gen_confirm([UNCONF], active=True)
            assert err is None and warns and "自动决定" in warns[0]
        finally:
            object.__setattr__(settings, "execution_preference", old)

    def test_auto_decide_without_skill_keeps_current_semantics(self):
        """无活跃 Skill 时按现状：闸不激活 → 不拒无警告（与今日逐字节一致）。"""
        old = settings.execution_preference
        object.__setattr__(settings, "execution_preference", "auto_decide")
        try:
            err, warns = guard_pipeline.evaluate_gen_confirm([UNCONF], active=False)
            assert err is None and warns == []
        finally:
            object.__setattr__(settings, "execution_preference", old)

    def test_dirty_pref_falls_back_to_default(self):
        """脏值经白名单清洗回落默认档：未确认仍拦（不破红线）。"""
        object.__setattr__(settings, "execution_preference", "yolo")
        try:
            err, _ = guard_pipeline.evaluate_gen_confirm([UNCONF], active=True)
            assert err and "生成确认闸拦截" in err
        finally:
            object.__setattr__(settings, "execution_preference", "confirm_before_gen")

    def test_fc_preference_semantics_match_shared(self, monkeypatch):
        """generate_directly 下 FC 适配器放行警告与唯一实现同源一致（Q2 后单轨）。"""
        monkeypatch.setattr("src.video_agent.core.prompt_gates.gate_mode", lambda: "strict")
        old = settings.execution_preference
        object.__setattr__(settings, "execution_preference", "generate_directly")
        try:
            state = {"keyElements": [{"drafts": [UNCONF]}]}
            ctx = _fc_ctx(state)
            assert fc_gates.gen_confirm_gate(
                ctx, "image_generate", {"target": "all_keyElements"}) is None
            err_shared, warns_shared = guard_pipeline.evaluate_gen_confirm(
                [UNCONF], active=True, action="image_generate")
            assert err_shared is None and ctx.warnings == warns_shared
            assert ctx.warnings and "直接生成" in ctx.warnings[0]
        finally:
            object.__setattr__(settings, "execution_preference", old)
