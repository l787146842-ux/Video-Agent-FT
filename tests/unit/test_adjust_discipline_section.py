"""微调任务纪律段（批 S2）：_sec_adjust_discipline 段函数与组装注入定点测试。

钉死三分支：非 scope 任务返空 / scope 任务注入外置纪律文案（内容恒定不嵌
目标编号，保前缀缓存）/ 文案读取失败降级返空不阻断对话；段注册表序位与
system prompt 组装载入同批断言（恢复 core 覆盖率棘轮基线）。"""
import pytest

import src.video_agent.core.prompt_builder as pb_mod
import src.video_agent.web.skill_docs as sd
from src.video_agent.core.planner import PlannerContext
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    # 隔离注册表：懒同步只扫本临时目录；用例后重置防污染
    registry.reset_registry()
    yield d
    registry.reset_registry()


def _pb():
    return PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )


def _ctx(**overrides):
    return PlannerContext(use_studio_context=False, skill_name="", **overrides)


def test_adjust_discipline_empty_when_no_scope(skills_dir):
    """非 scope 任务（无/空 adjust_scope）：不注入纪律段"""
    assert pb_mod._sec_adjust_discipline(_pb(), _ctx()) == ""
    assert pb_mod._sec_adjust_discipline(_pb(), _ctx(adjust_scope={})) == ""


def test_adjust_discipline_injects_external_text_for_scope(skills_dir):
    """scope 任务：注入外置纪律文案，内容恒定不嵌目标编号（保前缀缓存）"""
    text = pb_mod._sec_adjust_discipline(
        _pb(), _ctx(adjust_scope={"kind": "adjust", "draft_id": "d1"}))
    assert "微调任务纪律" in text
    assert "d1" not in text  # 目标信息由状态裁剪面携带，段内不嵌编号


def test_adjust_discipline_read_failure_degrades_to_empty(skills_dir, monkeypatch):
    """文案读取失败：降级返空不阻断对话（纪律降级遥测可见）"""

    def boom(_path, **_kw):
        raise RuntimeError("prompts unavailable")

    monkeypatch.setattr(pb_mod, "load_prompt", boom)
    assert pb_mod._sec_adjust_discipline(_pb(), _ctx(adjust_scope={"k": 1})) == ""


def test_adjust_discipline_registered_and_assembled(skills_dir):
    """段注册表序位钉死 + system prompt 组装：仅 scope 任务注入"""
    orders = {s.name: s.order for s in pb_mod.PROMPT_SECTIONS}
    assert orders["adjust_discipline"] == 80  # selected_draft(75) 与 selected_skill(100) 之间
    # 遥测别名表锁死不新增分项（只计 total）
    assert pb_mod._SECTION_TELEMETRY_ALIAS["adjust_discipline"] is None

    text = _pb().build_system_prompt(_ctx(adjust_scope={"kind": "adjust"}))
    assert "微调任务纪律" in text
    text_plain = _pb().build_system_prompt(_ctx())
    assert "微调任务纪律" not in text_plain
