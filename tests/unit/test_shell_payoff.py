"""五轮 S4：兼容壳 100% 清偿回归（#10/N2，防回潮 + 承重壳保护）。

清偿对象（未登记壳）：web/state_service.py、web/actions.py、planner 委托壳、
models_legacy.py（plan/story 字段）；委托/别名符号防复活由
check_legacy_orchestration 门禁承接（P2d 结构性测试减负）。
保护对象（宪法 §12 登记承重壳）：prompt_gates 尾部、chat_service 尾部
——monkeypatch 调用方命名空间策略锚点，不得删除。
（executors/__init__ 承重壳已随任务#36 B5 执行器一步退役物理删除。）
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src/video_agent"


# ---------- 已清偿壳不得复活 ----------

def test_s4_unregistered_shells_deleted():
    assert not (SRC / "web/state_service.py").exists()
    assert not (SRC / "web/actions.py").exists()
    assert not (SRC / "state/models_legacy.py").exists()


def test_s4_models_legacy_fields_removed():
    models = (SRC / "state/models.py").read_text(encoding="utf-8")
    assert "models_legacy" not in models
    assert "PlanState" not in models and "StoryState" not in models
    # extra=ignore 仍在（旧 state.json 残留键静默忽略，加载不报错）
    assert 'extra="ignore"' in models


def test_s4_planner_direct_call_wired():
    # 委托方法组/别名符号的防复活由 check_legacy_orchestration 门禁承接；
    # 此处只钉正向接线：真实消费直调新命名空间
    planner = (SRC / "core/planner.py").read_text(encoding="utf-8")
    assert "format_tool_results(tool_results)" in planner


def test_s4_planner_suggested_retry_present():
    """S3/S4 同批防丢：建议动作字段仍在（防重构误删）"""
    import dataclasses
    from src.video_agent.core.agent_loop import AgentLoopResult
    names = {f.name for f in dataclasses.fields(AgentLoopResult)}
    assert "suggested_actions" in names


# ---------- 宪法 §12 承重壳不得误删 ----------

def test_s4_registered_shells_kept():
    # skill_runtime/executors/__init__.py 承重壳保护已随任务#36 B5 执行器
    # 一步退役删除（模块物理删除，见 coupling_registry R13 留痕）
    assert not (SRC / "skill_runtime/executors/__init__.py").exists()
    pg = (SRC / "core/prompt_gates.py").read_text(encoding="utf-8")
    assert "from src.video_agent.core.gates_spec import" in pg
    cs = (SRC / "web/chat_service.py").read_text(encoding="utf-8")
    assert "from src.video_agent.web.chat_opening import" in cs
    assert "from src.video_agent.web.chat_consume import" in cs
