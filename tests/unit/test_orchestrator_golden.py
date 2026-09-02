# -*- coding: utf-8 -*-
"""状态驱动管线知识源 + 闸预检 + Workflow Runtime 黄金回归。

钉死：
① 阶段表 = 平台规范表 + frontmatter 声明覆盖（skip/同批执行器）；
② current_stage 按客观探针推进（analysis→spec→structure→创作型交接）；
③ 闸预检只装配兜底卡（原料闸/规格闸），永不执行阶段、永不抢先对话；
④ 首轮有素材 + 推进信号 → 交接模型循环（宪法 Rule2 主体回归：
   runtime 不自主代跑执行器，模型永远唯一行动主体；决策史见 git tag adr-archive-20260901）；
⑤ 提问/自由消息（无推进信号）→ 模型循环。
"""
import pytest

from src.video_agent.core import stage_probes as po
from src.video_agent.skill_runtime import registry

SKILL = "AI-短剧一站式生成"


# ---------- ① 阶段表 ----------

def test_stage_table_canonical_order():
    table = po.stage_table(SKILL)
    keys = [s.key for s in table]
    # 2026-08-31 用户裁决：spec 机械阶段退役（Flova 对齐，规格归散文驱动）
    assert keys == ["analysis", "structure", "ke_media",
                    "shot_media", "audio_assets", "assembly"]
    assert table[0].deterministic is True
    assert table[2].deterministic is False  # 创作型交接模型


def test_stage_table_manifest_override_retired(monkeypatch):
    """C1b 裁决 2026-08-31：flow.stages dict 覆盖声明退役——
    skip/executors 声明忽略，阶段表恒为平台规范表。"""
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {
        "flow": {
            "spec_wizard": True,
            "stages": {
                "assembly": {"skip": True},
                "structure": {"executors": ["storyboard_key_elements"]},
            }}})
    table = po.stage_table(SKILL)
    keys = [s.key for s in table]
    assert "assembly" in keys
    structure = next(s for s in table if s.key == "structure")
    # 覆盖忽略：执行器恒为平台默认三元组（非声明的单执行器）
    assert structure.executors == (
        "storyboard_key_elements", "storyboard_shots", "storyboard_audio")


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
    assert po.current_stage(_state_with(analysis=True), SKILL).key == "structure"
    st = _state_with(analysis=True, structure=True)
    assert po.current_stage(st, SKILL).key == "ke_media"
    assert po.current_stage(st, SKILL).deterministic is False


# ---------- ③ 闸预检：只装配兜底卡，永不执行/抢先 ----------

@pytest.mark.asyncio
async def test_precheck_handoff_at_creative_stage(tmp_path):
    """创作型阶段就绪 → None = 交接模型循环（模型持主动权）"""
    from src.video_agent.state.manager import StateManager

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["analysis"] = {"summary": "x"}
    svc.state_dict["documents"] = [
        {"name": "Final_Video_Spec.md", "content": "- 画幅：16:9\n"}]
    svc.state_dict["keyElements"] = [{"id": "ke1", "drafts": []}]
    svc.state_dict["shots"] = [{"id": "s1", "drafts": []}]
    svc.state_dict["audioItems"] = [{"id": "a1", "drafts": [{"prompt": "BGM：低沉"}]}]
    outcome = await po.gate_precheck(svc, SKILL, "继续")
    assert outcome is None
    StateManager.reset_instance()


# ---------- ④⑤ planner 主路径：主体回归后一律交接模型循环 ----------

@pytest.mark.asyncio
async def test_planner_first_turn_handed_to_model(tmp_path, monkeypatch):
    """主体回归：首轮有素材 + 推进信号也交接模型
    （模型永远唯一行动主体；原 ScriptAnalyzeTool 代跑探针已随任务#36 B5
    执行器一步退役删除，系统代跑路径不复存在）。"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager
    from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
    from src.video_agent.tools.manager import ToolManager

    class ProbeAdapter(BaseChatAdapter):
        def __init__(self):
            self.calls = 0

        @property
        def supports_function_calling(self):
            return False

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return ChatResponse(content="收到剧本，我来分析。", finish_reason="stop")

        async def chat_stream(self, messages, **kwargs):
            self.calls += 1
            yield ChatResponse(content="收到剧本，我来分析。", finish_reason="stop")

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：程心苏醒。"}]
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter,
                      tool_manager=ToolManager)
    result = await planner.handle_message(
        "请查看我上传的素材",
        PlannerContext(skill_name=SKILL, advance_signal="attachment"))
    assert adapter.calls >= 1, "主体回归：首轮也必须交接模型"
    assert result.text.strip()
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_planner_question_stays_in_model_loop(tmp_path):
    """自由提问不错抓：回落模型循环（adapter 被调用）"""
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
            self.calls += 1
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


@pytest.mark.asyncio
async def test_planner_script_missing_mechanical_card(tmp_path):
    """需剧本 Skill 且剧本缺失 → 机械提醒（模型零调用；批 B 出槽：
    正文 + quick-actions 芯片，不签发确认卡）"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    planner = Planner(state_manager=svc, llm_adapter=None, tool_manager=None)
    result = await planner.handle_message(
        "开始制作", PlannerContext(skill_name=SKILL))
    assert result.steps == 1
    assert result.text.strip(), "原料闸兜底提醒归正文通道（禁空正文）"
    assert not result.confirmation, "提醒出槽：不再机械签发确认卡"
    assert result.suggested_actions, "提醒选项转为 quick-actions 芯片"
    StateManager.reset_instance()
