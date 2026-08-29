"""FC 工具结果回喂测试 — 渐进式披露的「借阅归还」回路。

read_* 工具读回的全文（Skill 流程/规格文档/剧本/草稿提示词）必须回喂进
对话上下文，模型在后续轮次才真正看得到；否则按需加载形同虚设，
Skill 执行质量与提示词质量会显著下降。

注：代码内置 Skill（编剧/分镜师/制片）已按用户要求彻底移除，
本测试全部使用文档 Skill（data/skills/*.md，测试中为临时目录）。
"""
import json

import pytest

import src.video_agent.web.skill_docs as skill_docs_mod
from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.fc_tool_runner import format_tool_results
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.document_tools import (
    ReadProjectDocInput,
    ReadProjectDocTool,
    _fuzzy_pick,
    register_document_tools,
)
from src.video_agent.tools.manager import ToolManager

SKILL_MARKER = "SKILL_FLOW_MARKER"


@pytest.fixture
def svc(tmp_path, monkeypatch):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    # 文档 Skill：临时目录 + 一个测试 Skill（代替已删除的代码内置 Skill）；
    # M2 门户：read_skill 放行须可加载（已注册）→ 带 frontmatter 必填键
    # 可注册 + 隔离注册表，用例后重置防污染。
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
    registry.reset_registry()
    skill_docs_mod.save_skill_doc(
        "demo-flow",
        "---\nname: 测试流程 Skill\ndescription: 测试桩\n---\n"
        f"# 测试流程 Skill\n> 调用规则：测试用\n{SKILL_MARKER} 完整流程正文",
    )
    yield instance
    registry.reset_registry()
    StateManager.reset_instance()


class FcReadSkillAdapter(BaseChatAdapter):
    """第一轮发起 read_skill 工具调用，第二轮检查上下文后收尾的假 FC 模型"""

    def __init__(self, skill_name: str = "测试流程 Skill"):
        self._skill_name = skill_name
        self.calls = []

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        if len(self.calls) == 1:
            return ChatResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[{
                    "id": "call_test_1",
                    "type": "function",
                    "function": {
                        "name": "read_skill",
                        "arguments": json.dumps({"name": self._skill_name}, ensure_ascii=False),
                    },
                }],
            )
        return ChatResponse(content="已按 Skill 流程完成任务。", finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        response = await self.chat(messages, **kwargs)
        from src.video_agent.adapters.base_chat import StreamChunk
        yield StreamChunk(type="text_delta", text=response.content)


class TestFcToolResultFeedback:
    """工具执行结果必须回喂进下一轮 LLM 上下文"""

    async def test_read_skill_content_enters_next_round_context(self, svc):
        """read_skill 读回的 Skill 全文必须出现在第二轮调用的 messages 里"""
        register_document_tools()
        adapter = FcReadSkillAdapter()
        planner = Planner(llm_adapter=adapter, tool_manager=ToolManager)
        result = await planner.handle_message("按制作流程拆解这个剧本", PlannerContext(use_studio_context=False))

        assert result.steps >= 2, "read_skill 后应有第二轮 LLM 调用"
        second_round = "\n".join(m.get("content", "") for m in adapter.calls[1] if isinstance(m.get("content"), str))
        assert "read_skill" in second_round
        assert SKILL_MARKER in second_round, "Skill 全文未回喂进上下文，渐进式披露回路断裂"

    async def test_fuzzy_skill_name_still_readable(self, svc):
        """名称略有出入（带后缀/空格差异）也应能读到 Skill"""
        register_document_tools()
        adapter = FcReadSkillAdapter(skill_name="测试流程Skill.md")  # 故意不规范的名称
        planner = Planner(llm_adapter=adapter, tool_manager=ToolManager)
        await planner.handle_message("开工", PlannerContext(use_studio_context=False))

        second_round = "\n".join(m.get("content", "") for m in adapter.calls[1] if isinstance(m.get("content"), str))
        assert SKILL_MARKER in second_round, "模糊匹配失败导致 Skill 读不到"


class TestFormatToolResults:
    """回喂消息格式：read_* 携带全文，写入类只报成功，失败携带原因"""

    def test_read_tool_full_text_and_write_tool_brief(self):
        msg = format_tool_results([
            {"name": "read_skill", "ok": True, "data": {"name": "测试流程 Skill", "content": "SKILL_FULL_TEXT"}},
            {"name": "storyboard_patch_draft", "ok": True, "data": {"draft_id": "x"}},
            {"name": "read_project_doc", "ok": False, "error": "未找到文档"},
        ])
        assert "SKILL_FULL_TEXT" in msg, "read_skill 全文必须完整回喂"
        assert "storyboard_patch_draft：执行成功" in msg, "写入类工具只报成功，不携带大 JSON"
        assert "read_project_doc：执行失败" in msg

    def test_read_draft_renders_each_card(self):
        msg = format_tool_results([{
            "name": "read_draft", "ok": True,
            "data": {"drafts": [
                {"index": "1-2", "label": "概念图", "group_title": "元素组",
                 "draft_id": "d1", "prompt": "PROMPT_FULL_TEXT"},
            ]},
        }])
        assert "1-2" in msg and "PROMPT_FULL_TEXT" in msg

    def test_empty_results_no_feedback(self):
        assert format_tool_results([]) == ""


class TestFuzzyPick:
    """清单模糊定位：模型名称略有出入也能命中"""

    def test_extension_variants(self):
        items = [{"name": "剧本.md"}, {"name": "故事.txt"}]
        assert _fuzzy_pick(items, "剧本", ["name"])["name"] == "剧本.md"
        assert _fuzzy_pick(items, "剧本.md", ["name"])["name"] == "剧本.md"
        assert _fuzzy_pick(items, "故事", ["name"])["name"] == "故事.txt"

    def test_containment_and_case(self):
        items = [{"name": "Final_Video_Spec.md"}]
        assert _fuzzy_pick(items, "final_video_spec", ["name"]) is not None
        assert _fuzzy_pick(items, "Final_Video_Spec.md 制作规格", ["name"]) is not None

    def test_single_char_no_false_positive(self):
        items = [{"name": "剧本.md"}]
        assert _fuzzy_pick(items, "X", ["name"]) is None

    async def test_read_project_doc_fuzzy(self, svc):
        svc.state_dict["documents"] = [{
            "name": "Final_Video_Spec.md", "content": "SPEC_CONTENT", "updated_at": "",
        }]
        tool = ReadProjectDocTool()
        result = await tool.aexecute(ReadProjectDocInput(name="final_video_spec"))
        assert result.success and "SPEC_CONTENT" in (result.data or {}).get("content", "")
