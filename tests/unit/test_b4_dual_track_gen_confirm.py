"""B4 双轨收敛一期回归：生成确认闸双轨单一实现、语义逐字节一致。

事故溯源：三轮审核 B4（双轨镜像漂移——FC 全拒 vs 文本轨跳过未确认项）。
收敛落点：core/guard_pipeline.evaluate_gen_confirm（唯一实现），
两轨适配器只注入参数（Rule 2 双轨一致）。
"""
from src.video_agent.core import guard_pipeline
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.web.action_executor import StudioActionExecutor

CONF = {"id": "d1", "prompt": "x", "tag": "已确认"}
UNCONF = {"id": "d2", "prompt": "y", "tag": "Agent"}


def _fc_runner(state, override=False):
    r = object.__new__(FCToolRunner)
    r.gate_override = override
    r.gate_warnings = []
    r._raw_state = lambda: state
    return r


def _text_executor(override=False):
    e = object.__new__(StudioActionExecutor)
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
