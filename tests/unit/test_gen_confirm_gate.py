"""B4 双轨收敛一期回归：生成确认闸双轨单一实现、语义逐字节一致。

事故溯源：三轮审核 B4（双轨镜像漂移——FC 全拒 vs 文本轨跳过未确认项）。
收敛落点：core/guard_pipeline.evaluate_gen_confirm（唯一实现），
两轨适配器只注入参数（Rule 2 双轨一致）。
批 B：执行偏好三档前置分支也归该唯一实现（默认档行为与现状逐字节一致）。
"""
import json

from src.video_agent.config import settings
from src.video_agent.core import guard_pipeline
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.tracer import AgentTracer

CONF = {"id": "d1", "prompt": "x", "tag": "已确认"}
UNCONF = {"id": "d2", "prompt": "y", "tag": "Agent"}


def _fc_runner(state, override=False):
    r = object.__new__(FCToolRunner)
    r.gate_override = override
    r.gate_warnings = []
    r._raw_state = lambda: state
    return r


def _text_executor(override=False):
    e = object.__new__(StateOperationExecutor)
    e.gate_enabled = True
    e.gate_override = override
    e.gate_warnings = []
    return e


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


def test_dual_track_semantics_identical(monkeypatch):
    """同一输入下 FC 轨与文本轨判定/警告逐字节一致（宪法 Rule 2）。"""
    monkeypatch.setattr("src.video_agent.core.prompt_gates.gate_mode", lambda: "strict")

    # 拦截场景：存在未确认草稿 → FC 硬拒、文本轨返回空（调用方拒执行），警告一致
    state = {"keyElements": [{"drafts": [CONF, UNCONF]}]}
    fc = _fc_runner(state)
    fc_err = fc._gen_confirm_gate("image_generate", {"target": "all_keyElements"}, "some-skill")
    tx = _text_executor()
    tx_out = tx._gen_confirm_gate([(None, CONF), (None, UNCONF)])
    assert fc_err is not None
    assert tx_out == []
    assert fc.gate_warnings == tx.gate_warnings
    assert fc.gate_warnings and "生成确认闸拦截" in fc.gate_warnings[0]

    # 放行场景：全部已确认 → 两轨均放行且无警告
    state2 = {"keyElements": [{"drafts": [CONF]}]}
    fc2 = _fc_runner(state2)
    assert fc2._gen_confirm_gate("image_generate", {"target": "all_keyElements"}, "s") is None
    tx2 = _text_executor()
    pairs = [(None, CONF)]
    assert tx2._gen_confirm_gate(pairs) == pairs
    assert fc2.gate_warnings == tx2.gate_warnings == []

    # 豁免场景：override → 两轨放行且豁免警告一致
    fc3 = _fc_runner(state, override="all")
    assert fc3._gen_confirm_gate("image_generate", {"target": "all_keyElements"}, "s") is None
    tx3 = _text_executor(override="all")
    assert tx3._gen_confirm_gate([(None, UNCONF)]) == [(None, UNCONF)]
    assert fc3.gate_warnings == tx3.gate_warnings


# ---------- 批 B：执行偏好三档前置分支（唯一实现内，双轨自动同语义） ----------

def _recent_gates():
    return AgentTracer.get_instance().get_recent_gates(20)


def _trigger_lines():
    # conftest 夹具已把遥测落盘点隔离到临时目录（读模块属性即当前值）
    try:
        return [
            json.loads(ln)
            for ln in guard_pipeline.GATE_TRIGGER_COUNTS.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    except FileNotFoundError:
        return []


class TestExecPreferenceGenConfirm:
    """默认档 = 现状；非默认档放行必须代发同意并留痕（tracer + 遥测账本双源）。"""

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
            assert any(r["rule_id"] == "platform.gen_confirm" and r["ok"]
                       and r["overridden"] for r in _trigger_lines()), \
                "偏好放行必须入遥测账本（gate_trigger_counts）"
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

    def test_dual_track_preference_semantics_identical(self, monkeypatch):
        """generate_directly 下 FC 轨与文本轨放行警告逐字节一致（同源判定）。"""
        monkeypatch.setattr("src.video_agent.core.prompt_gates.gate_mode", lambda: "strict")
        old = settings.execution_preference
        object.__setattr__(settings, "execution_preference", "generate_directly")
        try:
            state = {"keyElements": [{"drafts": [UNCONF]}]}
            fc = _fc_runner(state)
            assert fc._gen_confirm_gate(
                "image_generate", {"target": "all_keyElements"}, "s") is None
            tx = _text_executor()
            pairs = [(None, UNCONF)]
            assert tx._gen_confirm_gate(pairs) == pairs
            assert fc.gate_warnings == tx.gate_warnings
            assert fc.gate_warnings and "直接生成" in fc.gate_warnings[0]
        finally:
            object.__setattr__(settings, "execution_preference", old)
