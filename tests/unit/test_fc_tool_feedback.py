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
from src.video_agent.core.fc_feedback import FEEDBACK_MARKER, format_tool_results
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
        f"# 测试流程 Skill\n> 调用规则：测试用\n{SKILL_MARKER} 完整流程正文\n"
        "## 章节一\nSECTION_BODY_TEXT",
    )
    yield instance
    registry.reset_registry()
    StateManager.reset_instance()


class FcReadSkillAdapter(BaseChatAdapter):
    """第一轮发起 read_skill 工具调用，第二轮检查上下文后收尾的假 FC 模型"""

    def __init__(self, skill_name: str = "测试流程 Skill", section: str = ""):
        self._skill_name = skill_name
        self._section = section
        self.calls = []

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        if len(self.calls) == 1:
            args = {"name": self._skill_name}
            if self._section:
                args["section"] = self._section
            return ChatResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[{
                    "id": "call_test_1",
                    "type": "function",
                    "function": {
                        "name": "read_skill",
                        "arguments": json.dumps(args, ensure_ascii=False),
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
        """read_skill 章节读回的全文必须出现在第二轮调用的 messages 里（B1：
        无 section = 指针（内容在 system），有 section = 全文回喂）"""
        register_document_tools()
        adapter = FcReadSkillAdapter(section="章节一")
        planner = Planner(llm_adapter=adapter, tool_manager=ToolManager)
        result = await planner.handle_message("按制作流程拆解这个剧本", PlannerContext(use_studio_context=False))

        assert result.steps >= 2, "read_skill 后应有第二轮 LLM 调用"
        second_round = "\n".join(m.get("content", "") for m in adapter.calls[1] if isinstance(m.get("content"), str))
        assert "read_skill" in second_round
        assert "SECTION_BODY_TEXT" in second_round, "章节全文未回喂进上下文，渐进式披露回路断裂"

    async def test_fuzzy_skill_name_still_readable(self, svc):
        """名称略有出入（带后缀/空格差异）也应能读到 Skill"""
        register_document_tools()
        adapter = FcReadSkillAdapter(skill_name="测试流程Skill.md", section="章节一")  # 故意不规范的名称
        planner = Planner(llm_adapter=adapter, tool_manager=ToolManager)
        await planner.handle_message("开工", PlannerContext(use_studio_context=False))

        second_round = "\n".join(m.get("content", "") for m in adapter.calls[1] if isinstance(m.get("content"), str))
        assert "SECTION_BODY_TEXT" in second_round, "模糊匹配失败导致 Skill 读不到"


class TestFormatToolResults:
    """回喂消息格式：read_* 携带全文，写入类只报成功，失败携带原因"""

    def test_read_skill_index_pointer(self):
        """B1：无 section（流程段+目录）与 system 的 Skill 轻量块重复 → 指针"""
        msg = format_tool_results([
            {"name": "read_skill", "ok": True, "data": {"name": "测试流程 Skill", "content": "SKILL_FULL_TEXT"}},
        ])
        assert "SKILL_FULL_TEXT" not in msg, "流程段+目录与 system 重复，不再全文回喂"
        assert "read_skill：执行成功" in msg

    def test_read_skill_section_first_full_then_dup_pointer(self):
        """B1：有 section 首次全文（带结构化行头）；同章节重复取读 → 指针"""
        tr = {"name": "read_skill", "ok": True, "data": {
            "name": "测试流程 Skill", "section": "script_analyze", "content": "SECTION_FULL_TEXT"}}
        first = format_tool_results([dict(tr)])
        assert "SECTION_FULL_TEXT" in first, "章节首次取读必须全文回喂"
        assert "skill=测试流程 Skill，section=script_analyze" in first, "结构化行头供历史扫描"
        history = [{"role": "user", "content": FEEDBACK_MARKER + "\n" + first}]
        dup = format_tool_results([dict(tr)], messages=history)
        assert "SECTION_FULL_TEXT" not in dup, "同章节重复取读走指针"
        assert "script_analyze" in dup
        # 不同章节仍全文
        other = format_tool_results([{"name": "read_skill", "ok": True, "data": {
            "name": "测试流程 Skill", "section": "storyboard", "content": "OTHER_SECTION_TEXT"}}],
            messages=history)
        assert "OTHER_SECTION_TEXT" in other, "不同章节首次取读照旧全文"

    def test_read_tool_full_text_and_write_tool_brief(self):
        msg = format_tool_results([
            {"name": "read_project_doc", "ok": True, "data": {"name": "doc.md", "content": "DOC_FULL_TEXT"}},
            {"name": "storyboard_patch_draft", "ok": True, "data": {"draft_id": "x"}},
            {"name": "read_project_doc", "ok": False, "error": "未找到文档"},
        ])
        assert "DOC_FULL_TEXT" in msg, "read_project_doc 全文必须完整回喂"
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


# ---------- C2：标准 tool role 回喂组装 ----------

class TestFormatToolResultMessages:
    """C2：工具结果切标准 tool role（id 配对），图片走 user 多模态"""

    def test_tool_role_messages_with_call_id(self):
        from src.video_agent.core.fc_feedback import format_tool_result_messages

        trs = [
            {"name": "read_uploaded_doc", "ok": True, "call_id": "call_a",
             "data": {"name": "doc.md", "content": "DOC_TEXT"}},
            {"name": "script_analysis_report", "ok": False, "call_id": "call_b",
             "error": "校验失败"},
        ]
        msgs, image_msg = format_tool_result_messages(trs)
        assert image_msg is None
        assert [m["role"] for m in msgs] == ["tool", "tool"]
        assert msgs[0]["tool_call_id"] == "call_a"
        assert "DOC_TEXT" in msgs[0]["content"]
        assert msgs[1]["tool_call_id"] == "call_b"
        assert "校验失败" in msgs[1]["content"]

    def test_image_tool_image_parts_go_to_user_msg(self):
        from src.video_agent.core.fc_feedback import format_tool_result_messages

        trs = [{"name": "view_storyboard_media", "ok": True, "call_id": "call_c",
                "data": {"images": [{"label": "镜头1", "draft_id": "d1",
                                     "data_uri": "data:image/png;base64,XXX"}]}}]
        msgs, image_msg = format_tool_result_messages(trs)
        assert image_msg is not None and image_msg["role"] == "user"
        imgs = [p for p in image_msg["content"] if p.get("type") == "image_url"]
        assert imgs and imgs[0]["image_url"]["url"].startswith("data:image/png")
        assert msgs, "文本说明仍以 tool 消息回喂"
        assert all(isinstance(m["content"], str) for m in msgs)


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


class TestParseFailReject8888:
    """8888 事故批：工具参数 JSON 解析失败不再静默伪造 {} 继续调用——
    抢救失败即结构化拒收，真实拒因（出错位置+原文片段）回喂模型。
    8888 实证：伪造 {} 后工具按「未携带非空 title」假拒收，模型原样重发 15 轮。"""

    def _runner(self):
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        return FCToolRunner(tool_manager=object())

    @staticmethod
    def _call(args_str: str, name: str = "storyboard_create_group") -> dict:
        return {"id": "call_8888", "type": "function",
                "function": {"name": name, "arguments": args_str}}

    async def test_broken_args_rejected_with_real_reason(self):
        runner = self._runner()
        ctx = runner._gate_ctx("")
        events = []

        async def on_event(ev):
            events.append(ev)

        c = await runner._prepare_call(
            self._call('{"title": "S02·曹彬来电", "desc": "【空间锚'), 0,
            ctx=ctx, image_provider="", image_aspect_ratio="",
            paused_this_batch=False, on_event=on_event)
        assert c.result is not None and c.result.success is False
        assert "参数 JSON 解析失败" in (c.gate_error or "")
        assert "S02·曹彬来电" in c.gate_error        # 原文片段随拒因可见（数据不丢）
        assert "未携带" not in c.gate_error           # 假拒因禁绝
        assert "未执行、未写入任何字段" in c.gate_error
        # 任何中断都有痕迹：started 事件已发（时间线可见）
        assert any(e.get("type") == "tool_started" for e in events)

    async def test_control_char_args_rescued_not_rejected(self, monkeypatch):
        """裸控制字符 → 抢救成功：args 为解析后 dict，走正常闸机链（不拒收）"""
        from src.video_agent.core import fc_tool_runner as ftr_mod

        runner = self._runner()
        ctx = runner._gate_ctx("")
        # 聚焦解析层：桩掉未注册判定/注入/闸机链（各自有独立测试覆盖）
        monkeypatch.setattr(ftr_mod.fc_gates, "unknown_tool_error",
                            lambda name, has_tool: None)
        monkeypatch.setattr(ftr_mod.fc_gates, "run_gate_chain",
                            lambda ctx, name, args, paused_this_batch:
                            type("R", (), {"error": None})())
        monkeypatch.setattr(ftr_mod.provider_injection, "inject",
                            lambda *a, **k: None)
        raw = '{"title": "S01", "desc": "第一行\n第二行"}'
        c = await runner._prepare_call(
            self._call(raw, name="read_skill"), 0,
            ctx=ctx, image_provider="", image_aspect_ratio="",
            paused_this_batch=False)
        assert c.args == {"title": "S01", "desc": "第一行\n第二行"}
        assert c.gate_error is None
        assert c.result is None   # 未被拒收，交由后续派发执行
