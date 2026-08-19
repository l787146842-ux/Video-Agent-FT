# -*- coding: utf-8 -*-
"""0818 架构板正批 B1：状态驱动编排器黄金回归。

钉死：
① 阶段表 = 平台规范表 + sidecar 覆盖（skip/同批执行器）；
② current_stage 按客观探针推进（analysis→spec→structure→创作型交接）；
③ run_deterministic_stage 按批直调 + 确定性重试；
④ 暂停卡纯客观事实，总结入卡随 sidecar 声明；
⑤ orchestrate_turn：分析完成即边界暂停；flow_directive 豁免则续进至 spec_pending。
   （3A DAG 化后：已声明 dependencies 的阶段以声明为准可并行——audio 只依赖
   structure，会与创作型 ke_media 竞争就绪；未声明阶段回落线性前置。）
"""
import asyncio

import pytest

from src.video_agent.core import pipeline_orchestrator as po
from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime.exec_common import SkillToolResult

SKILL = "AI-短剧一站式生成"


def _strip_demo_media(svc) -> None:
    """批 6：assembly 探针与 shot_media 解耦后（看组装产物），demo 自带分镜
    媒体会让 assembly 与分析同批就绪；本文件用例聚焦分析边界，剥离媒体
    使初始状态确定（只剩 structure 完成）。"""
    for cat in ("keyElements", "shots", "audioItems"):
        for g in svc.state_dict.get(cat) or []:
            for d in g.get("drafts") or []:
                d.pop("videoUrl", None)
                d.pop("imgUrl", None)
                d.pop("audioUrl", None)


# ---------- ① 阶段表 ----------

def test_stage_table_canonical_order():
    table = po.stage_table(SKILL)
    keys = [s.key for s in table]
    assert keys == ["analysis", "spec", "structure", "ke_media",
                    "shot_media", "audio_assets", "assembly"]
    assert table[0].deterministic is True
    assert table[3].deterministic is False  # 创作型交接模型


def test_stage_table_sidecar_override_skip_and_executors(monkeypatch):
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {
        "flow": {"stages": {
            "assembly": {"skip": True},
            "structure": {"executors": ["storyboard_key_elements"]},
        }}})
    table = po.stage_table(SKILL)
    keys = [s.key for s in table]
    assert "assembly" not in keys
    structure = next(s for s in table if s.key == "structure")
    assert structure.executors == ("storyboard_key_elements",)


# ---------- ② 客观探针推进 ----------

def _state_with(**kw):
    state = {}
    if kw.get("analysis"):
        state["analysis"] = {"summary": "木星掩体时代的降维打击。"}
    if kw.get("spec"):
        state["documents"] = [
            {"name": "Final_Video_Spec.md", "content": "- 画幅：16:9\n"}]
    if kw.get("structure"):
        state["keyElements"] = [{"id": "ke1", "drafts": []}]
        state["shots"] = [{"id": "s1", "drafts": []}]
        state["audioItems"] = [{"id": "a1", "drafts": []}]
    if kw.get("ke_media"):
        state["keyElements"][0]["drafts"] = [{"imgUrl": "http://x/i.png"}]
    return state


def test_current_stage_progression():
    assert po.current_stage(_state_with(), SKILL).key == "analysis"
    assert po.current_stage(_state_with(analysis=True), SKILL).key == "spec"
    assert po.current_stage(
        _state_with(analysis=True, spec=True), SKILL).key == "structure"
    st = _state_with(analysis=True, spec=True, structure=True)
    assert po.current_stage(st, SKILL).key == "ke_media"
    assert po.current_stage(st, SKILL).deterministic is False


# ---------- ③ 按批直调 + 确定性重试 ----------

def test_run_deterministic_stage_dispatch_order_and_retry(monkeypatch):
    from src.video_agent.skill_runtime import exec_tools

    calls = []

    class FakeTool:
        def __init__(self, name, fail_first):
            self.name = name
            self.fail_first = fail_first

        def get_input_schema(self):
            import pydantic

            class Schema(pydantic.BaseModel):
                skill_name: str = ""
            return Schema

        async def aexecute(self, params):
            calls.append(self.name)
            if self.fail_first and calls.count(self.name) == 1:
                return SkillToolResult(success=False, error="瞬时故障")
            return SkillToolResult(success=True, data={})

    built = {"script_analyze": FakeTool("script_analyze", True)}
    monkeypatch.setattr(po, "build_executor_tool",
                        lambda name: built.get(name))
    spec = po.StageSpec("analysis", "剧本分析", ("script_analyze",))
    results = asyncio.run(po.run_deterministic_stage(SKILL, spec))
    assert calls == ["script_analyze", "script_analyze"], "失败必须确定性重试一次"
    assert results[0].success


# ---------- ④ 暂停卡客观性 ----------

def test_pause_card_summary_follows_sidecar_declaration(monkeypatch):
    state = _state_with(analysis=True)
    done = po.StageSpec("analysis", "剧本分析")
    nxt = po.StageSpec("spec", "成片规格")

    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {"pause": {}})
    msg, opts = po.compose_pause_card(state, SKILL, done, nxt)
    assert "一句话总结" not in msg, "未声明不得强注入总结"
    assert "下一阶段：「成片规格」" in msg

    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {
        "pause": {"include_summary_in_pause": True}})
    msg2, _ = po.compose_pause_card(state, SKILL, done, nxt)
    assert "剧本一句话总结：木星掩体时代的降维打击。" in msg2
    assert opts[0]["label"] == "确认，继续"


# ---------- ⑤ orchestrate_turn ----------

@pytest.mark.asyncio
async def test_orchestrate_turn_pauses_at_analysis_boundary(tmp_path, monkeypatch):
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_tools

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：程心苏醒。"}]
    _strip_demo_media(svc)

    async def fake_aexecute(self, params):
        svc.state_dict["analysis"] = {"summary": "程心苏醒与掩体失效。"}
        return SkillToolResult(success=True, data={"summary": "程心苏醒与掩体失效。"})

    monkeypatch.setattr(exec_tools.ScriptAnalyzeTool, "aexecute", fake_aexecute)
    outcome = await po.orchestrate_turn(svc, SKILL)
    assert outcome is not None and outcome.kind == "paused"
    assert "剧本分析" in outcome.message and "成片规格" in outcome.message


@pytest.mark.asyncio
async def test_orchestrate_turn_auto_continue_reaches_spec_pending(tmp_path, monkeypatch):
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_tools

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：程心苏醒。"}]
    svc.state_dict.setdefault("interaction", {})["auto_continue"] = True

    async def fake_aexecute(self, params):
        svc.state_dict["analysis"] = {"summary": "程心苏醒与掩体失效。"}
        return SkillToolResult(success=True, data={})

    monkeypatch.setattr(exec_tools.ScriptAnalyzeTool, "aexecute", fake_aexecute)
    outcome = await po.orchestrate_turn(svc, SKILL)
    assert outcome is not None and outcome.kind == "spec_pending", \
        "flow_directive 豁免：分析后不暂停，续进至规格收集"


@pytest.mark.asyncio
async def test_orchestrate_turn_handoff_at_creative_stage(tmp_path):
    """3A DAG 语义：audio 已完（只依赖 structure）且 ke_media 未完成 →
    创作型 ke_media 就绪 → 交接模型循环。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["analysis"] = {"summary": "x"}
    svc.state_dict["documents"] = [
        {"name": "Final_Video_Spec.md", "content": "- 画幅：16:9\n"}]
    svc.state_dict["keyElements"] = [{"id": "ke1", "drafts": []}]
    svc.state_dict["shots"] = [{"id": "s1", "drafts": []}]
    # audio 阶段已完成（DAG 下它与 ke_media 并行，先完不等）
    svc.state_dict["audioItems"] = [{"id": "a1", "drafts": [{"prompt": "BGM：低沉"}]}]
    outcome = await po.orchestrate_turn(svc, SKILL)
    assert outcome is None, "创作型阶段交接模型循环（混合模式）"


# ---------- B2 接线：planner 主路径路由 ----------

@pytest.mark.asyncio
async def test_planner_routes_first_turn_to_orchestrator(tmp_path, monkeypatch):
    """首轮非提问+有素材 → 编排器快路径（模型循环零调用）。"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_tools

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：程心苏醒。"}]
    _strip_demo_media(svc)

    async def fake_aexecute(self, params):
        svc.state_dict["analysis"] = {"summary": "程心苏醒与掩体失效。"}
        return SkillToolResult(success=True, data={})

    monkeypatch.setattr(exec_tools.ScriptAnalyzeTool, "aexecute", fake_aexecute)
    planner = Planner(state_manager=svc, llm_adapter=None, tool_manager=None)
    result = await planner.handle_message(
        "AI-短剧一站式生成", PlannerContext(skill_name=SKILL))
    assert result.steps == 1
    assert "剧本分析" in (result.confirmation or ""), "阶段边界机械暂停卡"
    assert (svc.state_dict.get("interaction") or {}).get("awaiting_confirmation")
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_planner_question_stays_in_model_loop(tmp_path, monkeypatch):
    """自由提问不错抓：路由回落模型循环（adapter 被调用）。"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager
    from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse

    class ProbeAdapter(BaseChatAdapter):
        def __init__(self):
            self.calls = 0

        @property
        def supports_function_calling(self):
            return False

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return ChatResponse(content="我是创作助手。", finish_reason="stop")

        async def chat_stream(self, messages, **kwargs):
            yield ChatResponse(content="我是创作助手。", finish_reason="stop")

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文。"}]
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=None)
    await planner.handle_message(
        "这个剧本讲什么？", PlannerContext(skill_name=SKILL))
    assert adapter.calls >= 1, "提问必须回落模型循环"
    StateManager.reset_instance()
