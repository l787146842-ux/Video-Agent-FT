"""814H9 钉死回归：剧本原料闸（客观检测/零思考直出/反复提醒/豁免/执行侧拦截）。

事故背景（1111）：剧本缺失是客观事实，却交给模型花 27.8s 规划轮"发现"，
还放行必错的 read_uploaded_doc 调用与空输出重试。宪法 13.5 确定性三问收归系统。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.flow_gates import FlowGateSet
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager


@pytest.fixture()
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    for key in ("keyElements", "shots", "audioItems"):
        instance.state_dict[key] = []
    instance.state_dict["documents"] = []
    yield instance
    StateManager.reset_instance()

SCRIPT_SKILL = (
    "# 需剧本Skill\n> 调用规则：测试\n"
    "```json skill_manifest\n{\"flow\": {}}\n```\n"
    "1. 读取并分析用户上传的剧本文件 → **resource_prepare_and_analyze**\n"
    "2. 拆解关键元素\n"
)
NO_SCRIPT_SKILL = "# 免剧本Skill\n> 调用规则：测试\n正文自由创作。\n"


class _CountingAdapter:
    """记录调用次数的桩适配器；chat 返回无工具调用的纯文本。"""

    supports_function_calling = True

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        from src.video_agent.adapters.base_chat import ChatResponse
        return ChatResponse(content="好的，请上传剧本。", finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):  # pragma: no cover
        # 空异步生成器（本批测试不走流式路径）
        if False:
            yield


@pytest.fixture()
def skills_env(tmp_path, monkeypatch, svc):
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path)
    registry.reset_registry()
    sd.save_skill_doc("需剧本Skill", SCRIPT_SKILL)
    sd.save_skill_doc("免剧本Skill", NO_SCRIPT_SKILL)
    yield svc
    registry.reset_registry()


def test_script_required_detection(skills_env):
    """客观特征检测 + manifest 逃生门（与 spec_wizard_active 同模式）"""
    assert registry.script_required_active("需剧本Skill") is True
    assert registry.script_required_active("免剧本Skill") is False
    assert registry.script_required_active("不存在Skill") is False


async def test_short_circuit_skips_llm(skills_env):
    """S7：推进意图+原料缺失 → 秒发提醒卡，主模型零调用（省规划轮）"""
    adapter = _CountingAdapter()
    planner = Planner(llm_adapter=adapter)
    result = await planner.handle_message(
        "有，我现在上传剧本 中文为主", PlannerContext(use_studio_context=False, skill_name="需剧本Skill"))
    assert adapter.calls == 0, "短路时主模型不得被调用"
    assert "剧本" in result.confirmation and "上传" in result.confirmation
    assert len(result.confirmation_options) == 2


async def test_upload_ack_no_repeat_card(skills_env):
    """点「我去上传」后秒回等待回执，不重复弹提醒卡"""
    adapter = _CountingAdapter()
    planner = Planner(llm_adapter=adapter)
    result = await planner.handle_message(
        "我去上传/粘贴剧本", PlannerContext(use_studio_context=False, skill_name="需剧本Skill"))
    assert adapter.calls == 0
    assert "等你" in result.text
    assert not result.confirmation


async def test_question_falls_through_and_forced_card(skills_env):
    """提问类消息落回 LLM；轮末强制提醒卡（反复提醒）"""
    adapter = _CountingAdapter()
    planner = Planner(llm_adapter=adapter)
    result = await planner.handle_message(
        "你能做什么？", PlannerContext(use_studio_context=False, skill_name="需剧本Skill"))
    assert adapter.calls >= 1, "提问不得被短路"
    assert "剧本" in result.confirmation, "轮末必须强制提醒卡"


async def test_waive_intent_records_and_no_card(skills_env):
    """豁免意图（从零原创）记账 script_waived，本轮不提醒"""
    adapter = _CountingAdapter()
    planner = Planner(llm_adapter=adapter)
    result = await planner.handle_message(
        "从零开始，全中文输出", PlannerContext(use_studio_context=False, skill_name="需剧本Skill"))
    assert not result.confirmation, "豁免后不得弹提醒卡"
    inter = skills_env.state_dict.get("interaction") or {}
    assert inter.get("script_waived") is True


async def test_script_present_clears_gate(skills_env):
    """原料已交（uploadedDocs 非空）→ 不提醒、不短路"""
    skills_env.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.txt", "kind": "file", "char_count": 100}
    ]
    adapter = _CountingAdapter()
    planner = Planner(llm_adapter=adapter)
    result = await planner.handle_message(
        "开始吧", PlannerContext(use_studio_context=False, skill_name="需剧本Skill"))
    assert adapter.calls >= 1
    assert not result.confirmation


async def test_non_script_skill_unaffected(skills_env):
    """免剧本 Skill：空状态也不提醒（影响面隔离）"""
    adapter = _CountingAdapter()
    planner = Planner(llm_adapter=adapter)
    result = await planner.handle_message(
        "开始吧", PlannerContext(use_studio_context=False, skill_name="免剧本Skill"))
    assert adapter.calls >= 1
    assert not result.confirmation


def test_structure_blocked_without_script(skills_env):
    """S5 执行侧：原料缺失拦结构类工具；原料到位放行（双轨同条件）"""
    fs = FlowGateSet.ensure_script_gate(None)
    op = fs.classify_fc("storyboard_key_elements", {})
    ok, missing = fs.check_op(op, {"uploadedDocs": []})
    assert not ok and missing
    ok2, _ = fs.check_op(op, {"uploadedDocs": [{"id": "d1", "name": "x"}]})
    assert ok2
    # 文本轨同条件（classify_action）
    op_txt = fs.classify_action({"action": "storyboard_shots"})
    assert not fs.check_op(op_txt, {"uploadedDocs": []})[0]
