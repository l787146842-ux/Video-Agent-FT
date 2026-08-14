"""Skill 声明式流程门禁（硬校验）测试。

888 项目事故：模型读到了 Skill 却把「规格+故事板+元素草案+分镜草案」合并到
一轮做完、跳过全部暂停点。提示词层的纪律无效，故改为代码强制：
Skill 用固定格式声明检查点，系统在执行前校验前置条件，越阶即拦截并强制暂停。
"""
import json

import pytest

import src.video_agent.web.skill_docs as skill_docs_mod
from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.flow_gates import (
    OP_WRITE_SHOT_PROMPT,
    FlowGateSet,
    evaluate_condition,
    parse_flow_gates,
)
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.storyboard_tools import register_storyboard_tools

GATE_SKILL = """# 门禁测试 Skill
> 调用规则：测试用
正文……

== 流程检查点 ==
- 写入分镜提示词 需要: 关键元素提示词已写入, 关键元素已确认
- 触发生成 需要: 关键元素已确认

## 其他段落
不应被解析进来。
"""

NO_GATE_SKILL = "# 无门禁 Skill\n> 调用规则：测试用\n正文……"

# 结构合规的长提示词（814R3 适配：现行结构闸要求 ≥80 字，短夹具会被结构闸误拦）
VALID_SHOT_PROMPT = (
    "镜头总时长：12秒。缓慢推入中景，主角在冰原上奔跑，怀中紧抱文物，"
    "背景崩裂成平面，光影克制，色调深青，<音效轰鸣>，no music，no subtitles。"
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    # 清空 demo 项目预置数据，保证门禁判定基线干净
    for key in ("keyElements", "shots", "audioItems"):
        instance.state_dict[key] = []
    instance.state_dict["documents"] = []
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def gate_skill(tmp_path, monkeypatch):
    """临时文档 Skill 目录 + 声明了流程检查点的 Skill"""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
    skill_docs_mod.save_skill_doc("gate-skill", GATE_SKILL)
    return "门禁测试 Skill"


def _seed_keyelements_ready(svc):
    """关键元素：提示词已写入且已确认（门禁条件满足）"""
    svc.state_dict["keyElements"] = [{
        "id": "g1", "title": "Element_X",
        "drafts": [{"id": "d1", "label": "概念图", "prompt": "x" * 20, "confirmed": True}],
    }]


def _seed_shot_target(svc):
    svc.state_dict["shots"] = [{
        "id": "g2", "title": "Shot_Y",
        "drafts": [{"id": "d2", "label": "分镜卡", "prompt": ""}],
    }]


class TestParseFlowGates:
    def test_parse_declared_gates(self):
        gates = parse_flow_gates(GATE_SKILL)
        assert len(gates) == 2
        shot_gate = next(g for g in gates if OP_WRITE_SHOT_PROMPT in g.ops)
        assert "keyelement_prompts_written" in shot_gate.requires
        assert "keyelements_confirmed" in shot_gate.requires
        gen_gate = next(g for g in gates if "generate" in g.ops)
        assert gen_gate.requires == ["keyelements_confirmed"]

    def test_no_section_returns_empty(self):
        assert parse_flow_gates(NO_GATE_SKILL) == []
        assert FlowGateSet.from_skill(NO_GATE_SKILL) is None

    def test_unknown_condition_ignored(self):
        gates = parse_flow_gates("== 流程检查点 ==\n- 写入分镜提示词 需要: 不存在的条件, 关键元素已确认\n")
        assert gates[0].requires == ["keyelements_confirmed"]


class TestConditionEvaluation:
    def test_keyelement_conditions(self, svc):
        state = svc.state_dict
        assert evaluate_condition("keyelement_prompts_written", state) is False
        state["keyElements"] = [{"id": "g", "title": "t", "drafts": [
            {"id": "a", "prompt": "p", "confirmed": False},
            {"id": "b", "prompt": "", "confirmed": False},
        ]}]
        # 有草稿未写完 → 未满足
        assert evaluate_condition("keyelement_prompts_written", state) is False
        state["keyElements"][0]["drafts"][1]["prompt"] = "q"
        assert evaluate_condition("keyelement_prompts_written", state) is True
        assert evaluate_condition("keyelements_confirmed", state) is False
        for d in state["keyElements"][0]["drafts"]:
            d["confirmed"] = True
        assert evaluate_condition("keyelements_confirmed", state) is True

    def test_spec_doc_exists(self, svc):
        assert evaluate_condition("spec_doc_exists", svc.state_dict) is False
        svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "x"}]
        assert evaluate_condition("spec_doc_exists", svc.state_dict) is True


class FcPatchShotAdapter(BaseChatAdapter):
    """发起一次 storyboard_patch_draft（写分镜提示词）的假 FC 模型"""

    def __init__(self):
        self.calls = 0

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                content="正在写入分镜提示词。",
                finish_reason="tool_calls",
                tool_calls=[{
                    "id": "c1", "type": "function",
                    "function": {
                        "name": "storyboard_patch_draft",
                        "arguments": json.dumps(
                            {"draft_id": "d2", "draft_type": "shot", "patch": {"prompt": VALID_SHOT_PROMPT}},
                            ensure_ascii=False,
                        ),
                    },
                }],
            )
        return ChatResponse(content="完成。", finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        resp = await self.chat(messages, **kwargs)
        from src.video_agent.adapters.base_chat import StreamChunk
        yield StreamChunk(type="text_delta", text=resp.content)


class TestGateEnforcementFcPath:
    """FC 路径：越阶工具被拦截 + 强制暂停"""

    async def test_shot_prompt_blocked_when_keyelements_not_ready(self, svc, gate_skill):
        register_storyboard_tools()
        _seed_shot_target(svc)  # 关键元素为空 → 前置条件不满足
        planner = Planner(llm_adapter=FcPatchShotAdapter(), tool_manager=ToolManager)
        result = await planner.handle_message(
            "写分镜提示词", PlannerContext(use_studio_context=False, skill_name=gate_skill),
        )
        # 拦截：分镜提示词没写进状态
        assert svc.state_dict["shots"][0]["drafts"][0].get("prompt") == ""
        # 强制暂停：confirmation 由系统补发
        assert result.confirmation and "强制暂停" in result.confirmation
        assert result.applied_actions == 0

    async def test_shot_prompt_allowed_when_keyelements_ready(self, svc, gate_skill):
        register_storyboard_tools()
        _seed_keyelements_ready(svc)
        _seed_shot_target(svc)
        planner = Planner(llm_adapter=FcPatchShotAdapter(), tool_manager=ToolManager)
        result = await planner.handle_message(
            "写分镜提示词", PlannerContext(use_studio_context=False, skill_name=gate_skill),
        )
        assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == VALID_SHOT_PROMPT
        assert result.confirmation == ""

    async def test_no_gate_skill_no_blocking(self, svc, tmp_path, monkeypatch):
        register_storyboard_tools()
        skill_dir = tmp_path / "skills"
        if not skill_dir.exists():
            skill_dir.mkdir()
        monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
        skill_docs_mod.save_skill_doc("plain", NO_GATE_SKILL)
        _seed_shot_target(svc)
        planner = Planner(llm_adapter=FcPatchShotAdapter(), tool_manager=ToolManager)
        result = await planner.handle_message(
            "写分镜提示词", PlannerContext(use_studio_context=False, skill_name="无门禁 Skill"),
        )
        # 未声明检查点 → 完全不拦截
        assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == VALID_SHOT_PROMPT
        assert result.confirmation == ""


class TextActionsAdapter(BaseChatAdapter):
    """文本模式：直接输出 studio-actions 写分镜提示词"""

    REPLY = (
        "好的。\n```studio-actions\n"
        '[{"action":"update_draft","draft_type":"shot","draft_id":"d2",'
        f'"patch":{{"prompt":"{VALID_SHOT_PROMPT}"}}}}]\n```'
    )

    @property
    def supports_function_calling(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(content=self.REPLY, finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        from src.video_agent.adapters.base_chat import StreamChunk
        yield StreamChunk(type="text_delta", text=self.REPLY)


class TestGateEnforcementTextPath:
    """文本路径：越阶 action 被剔除 + 强制暂停"""

    async def test_text_action_blocked_and_forced_pause(self, svc, gate_skill):
        _seed_shot_target(svc)
        planner = Planner(llm_adapter=TextActionsAdapter())
        result = await planner.handle_message(
            "写分镜提示词", PlannerContext(use_studio_context=False, skill_name=gate_skill),
        )
        assert svc.state_dict["shots"][0]["drafts"][0].get("prompt") == ""
        assert result.confirmation and "强制暂停" in result.confirmation
        assert any("流程门禁拦截" in w for w in result.warnings)


class TestUserOverrideBypass:
    """用户第一（814R3）：用户明确坚持跳过时，流程门禁不硬拦"""

    async def test_user_insist_bypasses_flow_gate(self, svc, gate_skill):
        _seed_shot_target(svc)
        planner = Planner(llm_adapter=TextActionsAdapter())
        result = await planner.handle_message(
            "按我说的直接写分镜提示词", PlannerContext(use_studio_context=False, skill_name=gate_skill),
        )
        assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == VALID_SHOT_PROMPT
        assert "强制暂停" not in (result.confirmation or "")

    async def test_session_override_consumed_once(self, svc, gate_skill):
        """interaction.gate_overrides 单次生效：消费即清除"""
        _seed_shot_target(svc)
        svc.state_dict.setdefault("interaction", {})["gate_overrides"] = ["all"]
        svc.save()
        planner = Planner(llm_adapter=TextActionsAdapter())
        await planner.handle_message(
            "写分镜提示词", PlannerContext(use_studio_context=False, skill_name=gate_skill),
        )
        assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == VALID_SHOT_PROMPT
        assert (svc.state_dict.get("interaction") or {}).get("gate_overrides") == []
