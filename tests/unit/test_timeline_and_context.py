"""回复机制改造回归：过程时间线事件、reasoning 透传、历史截断、文档按需检索"""
import json
from types import SimpleNamespace

import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.state.manager import StateManager
from src.video_agent.state.context_builder import build_agent_context
from src.video_agent.web.chat_service import truncate_history
from src.video_agent.web.action_executor import StateOperationExecutor
from src.video_agent.tools.document_tools import (
    ReadUploadedDocTool, ReadUploadedDocInput,
    ReadSkillTool, ReadSkillInput,
    ReadProjectDocTool, ReadProjectDocInput,
)
from src.video_agent.tools.storyboard_tools import StoryboardReadDraftTool, ReadDraftInput
import src.video_agent.web.skill_docs as skill_docs_mod


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


# ---------- truncate_history：assistant 截断 / user 全文 ----------

class TestTruncateHistory:
    def test_old_assistant_head_tail_kept(self):
        """非最新 assistant 回复：保留头 300 + 尾 300（旧版只留头部，
        会丢掉结尾的下一步建议）"""
        head = "开头结论" * 100          # 400 字
        middle = "中部冗余" * 200        # 800 字
        tail = "结尾下一步建议" * 50     # 350 字
        old_reply = head + middle + tail
        msgs = [
            {"role": "assistant", "content": old_reply},
            {"role": "user", "content": "继续"},
            {"role": "assistant", "content": "最新回复"},
        ]
        out = truncate_history(msgs)
        c = out[0]["content"]
        assert c.startswith(head[:300])
        assert tail[-300:] in c
        assert "中部已省略" in c
        assert middle[:100] not in c
        # 最新回复不受影响
        assert out[2]["content"] == "最新回复"

    def test_recent_assistant_full_up_to_2000(self):
        """最新 assistant 回复保真度优先：2000 字内不截断"""
        text = "复述的提示词全文" * 200  # 1600 字 < 2000
        out = truncate_history([{"role": "assistant", "content": text}])
        assert out[0]["content"] == text

    def test_recent_assistant_truncated_at_2000(self):
        """最新 assistant 回复超 2000 字仍要截断（兼顺 token 治理）"""
        text = "超长最新回复" * 500  # 3000 字 > 2000
        out = truncate_history([{"role": "assistant", "content": text}])
        assert out[0]["content"].startswith(text[:2000])
        assert "已截断" in out[0]["content"]
        assert len(out[0]["content"]) < len(text)

    def test_user_message_kept_full(self):
        long_text = "用户指令" * 300
        out = truncate_history([{"role": "user", "content": long_text}])
        assert out[0]["content"] == long_text

    def test_short_assistant_unchanged(self):
        out = truncate_history([{"role": "assistant", "content": "简短回复"}])
        assert out[0]["content"] == "简短回复"

    def test_non_str_content_passthrough(self):
        parts = [{"type": "text", "text": "多模态"}]
        out = truncate_history([{"role": "user", "content": parts}])
        assert out[0]["content"] is parts


# ---------- agent_loop：文本路径 tool_started/tool_finished 事件 ----------

@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


def make_llm(replies):
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return reply[0], reply[1], 0

    return llm_call


async def test_agent_loop_emits_tool_events(executor):
    """过程时间线事件链（audit-0819b 单轨化后：agent_loop 侧发射源 =
    模型推理条目与前奏明细；动作条目由 fc_tool_runner 发射，见
    test_fc_tool_timeline_events）"""
    events: list = []

    async def on_event(ev):
        events.append(ev)

    result = await run_agent_loop(
        "你好", llm_call=make_llm([("好的，已收到。", "stop")]),
        context_builder=lambda: "ctx", executor=executor, history=[],
        on_event=on_event,
        prelude_notes=[("read_skill", "加载 Skill 流程规范进上下文")],
    )
    types = [e["type"] for e in events]
    assert "tool_started" in types and "tool_finished" in types
    # 前奏条目：先 started 后 finished，且 id 对应
    started = next(e for e in events
                   if e["type"] == "tool_started" and e.get("name") == "read_skill")
    finished = next(e for e in events
                    if e["type"] == "tool_finished" and e.get("id") == started["id"])
    assert types.index("tool_started") < types.index("tool_finished")
    assert finished["ok"] is True
    # 模型推理条目同样成对（耗时回填；finished 事件携 id 不带 name）
    assert any(e.get("id") == "llm-s1" and e["type"] == "tool_finished"
               for e in events)
    # trace 携带 actions 明细（前端刷新后可重建时间线）
    step = result.trace["steps"][0]
    assert step["actions"] and step["actions"][0]["ok"] is True


# ---------- planner：reasoning 透传 + FC 工具时间线事件 ----------

class FakeReasoningAdapter(BaseChatAdapter):
    """流式输出 reasoning_delta + text_delta 的推理模型假 Adapter"""

    @property
    def supports_function_calling(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(content="回复", finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        yield StreamChunk(type="reasoning_delta", text="我需要先分析状态，")
        yield StreamChunk(type="reasoning_delta", text="再规划操作。")
        yield StreamChunk(type="text_delta", text="已完成")
        yield StreamChunk(type="done", finish_reason="stop")


class FakeToolManager:
    invoked: list = []

    @classmethod
    def reset(cls):
        cls.invoked = []

    @classmethod
    def get_all_tool_schemas(cls, exclude=None) -> list:
        return []

    @classmethod
    async def invoke_tool(cls, name: str, args: dict):
        cls.invoked.append((name, args))
        return SimpleNamespace(success=True, error="", data={})


def make_hook(collector: list | None = None):
    async def _hook(text: str) -> None:
        if collector is not None:
            collector.append(text)
    return _hook


async def test_reasoning_passthrough_and_trace(svc):
    planner = Planner(llm_adapter=FakeReasoningAdapter(), tool_manager=FakeToolManager)
    events: list = []

    async def on_event(ev):
        events.append(ev)

    result = await planner.handle_message(
        "你好", PlannerContext(use_studio_context=False),
        stream_hook=make_hook(), on_event=on_event,
    )
    reasoning_events = [e for e in events if e["type"] == "reasoning_delta"]
    assert len(reasoning_events) == 2
    assert result.text == "已完成"
    # reasoning 记入 trace（持久化展示，不进下次上下文）
    step = result.trace["steps"][0]
    assert "先分析状态" in step["reasoning"]


class FakeStreamFCAdapter(BaseChatAdapter):
    def __init__(self, tool_calls: list):
        self._tool_calls = tool_calls

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(content="", finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        yield StreamChunk(type="text_delta", text="执行中")
        for name, args in self._tool_calls:
            yield StreamChunk(type="tool_call", tool_name=name, tool_args=args)
        yield StreamChunk(type="done", finish_reason="stop")


async def test_fc_tool_timeline_events(svc):
    FakeToolManager.reset()
    planner = Planner(llm_adapter=FakeStreamFCAdapter([("fake_tool", {"a": 1})]),
                      tool_manager=FakeToolManager)
    events: list = []

    async def on_event(ev):
        events.append(ev)

    result = await planner.handle_message(
        "执行", PlannerContext(use_studio_context=False),
        stream_hook=make_hook(), on_event=on_event,
    )
    started = [e for e in events if e["type"] == "tool_started"]
    finished = [e for e in events
                if e["type"] == "tool_finished" and e.get("name") != "model_reasoning"
                and e.get("result_summary") != f"Agent 规划完成（第 1 轮）"]
    # 814G2：规划轮也进 live 事件流（运行中视图与持久化视图同条目）
    assert [e["name"] for e in started] == ["model_reasoning", "fake_tool"]
    tool_finished = [e for e in events if e["type"] == "tool_finished"]
    assert len(tool_finished) == 2
    assert started[1]["name"] == "fake_tool"
    # 任务 #2：工具 started 事件携裁剪脱敏后的 args（规划条目不带）
    assert started[1]["args"] == {"a": 1}
    assert "args" not in started[0]
    assert finished[0]["ok"] is True
    step = result.trace["steps"][0]
    # 814G2 顺序：规划条目在前、工具在后，且规划耗时已补填
    assert step["actions"][0]["name"] == "model_reasoning"
    assert step["actions"][0]["elapsed_ms"] >= 0
    assert step["actions"][1]["name"] == "fake_tool"
    # 任务 #2：trace 条目同步落盘 args（刷新重建后详情卡展开区不丢；
    # 规划条目不带 args）
    assert step["actions"][1].get("args") == {"a": 1}
    assert "args" not in step["actions"][0]


# ---------- 知识渐进式披露：规格清单 / 附件清单 / 按需检索 ----------

def test_context_builder_manifests_no_full_text(svc):
    svc.state_dict["documents"] = [{
        "name": "制片规格.md", "updated_at": "",
        "content": "规格内容" * 1000,  # 4000 字，全文不应进上下文
    }]
    svc.state_dict["uploadedDocs"] = [{
        "id": "udoc-1", "name": "剧本.md", "kind": "file",
        "content": "剧本正文不应进入上下文" * 100, "char_count": 1200,
        "uploaded_at": "2026-08-04T00:00:00Z",
    }]
    ctx = build_agent_context(svc.state_dict, "bound")
    parsed = json.loads(ctx)
    # 规格文档仅清单：名称/字数/预览，全文不注入
    doc = next(d for d in parsed["documents"] if d["name"] == "制片规格.md")
    assert doc["char_count"] == 4000
    assert "规格内容" * 1000 not in ctx
    # 附件文档仅清单：有名称与字数，无正文
    udoc = next(d for d in parsed["uploadedDocs"] if d["name"] == "剧本.md")
    assert udoc["char_count"] == 1200
    assert "剧本正文不应进入上下文" not in ctx


async def test_read_uploaded_doc_tool(svc):
    svc.state_dict["uploadedDocs"] = [{
        "id": "udoc-1", "name": "剧本.md", "kind": "file",
        "content": "第一幕：深空中……", "char_count": 9, "uploaded_at": "",
    }]
    tool = ReadUploadedDocTool()
    ok = await tool.aexecute(ReadUploadedDocInput(name="剧本.md"))
    assert ok.success and "第一幕" in ok.data["content"]
    # 模糊匹配（不带后缀）
    ok2 = await tool.aexecute(ReadUploadedDocInput(name="剧本"))
    assert ok2.success
    # 未找到：报错并列出已存档文档
    miss = await tool.aexecute(ReadUploadedDocInput(name="不存在"))
    assert not miss.success and "剧本.md" in miss.error


async def test_read_project_doc_tool(svc):
    svc.state_dict["documents"] = [{
        "name": "制片规格.md", "updated_at": "",
        "content": "规格全文：全片 90 秒……",
    }]
    tool = ReadProjectDocTool()
    ok = await tool.aexecute(ReadProjectDocInput(name="制片规格.md"))
    assert ok.success and "规格全文" in ok.data["content"]
    # 模糊匹配（包含）
    ok2 = await tool.aexecute(ReadProjectDocInput(name="规格"))
    assert ok2.success
    miss = await tool.aexecute(ReadProjectDocInput(name="没有这篇"))
    assert not miss.success and "制片规格.md" in miss.error


async def test_read_skill_tool(tmp_path, monkeypatch, svc):
    """read_skill：文档 Skill 全文按需加载；未命中时报错列出可用 Skill"""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
    skill_docs_mod.save_skill_doc(
        "music-mv", "# 音乐MV制作\n> 调用规则：制作音乐MV时使用\n## 流程\n完整流程正文……",
    )
    tool = ReadSkillTool()
    ok = await tool.aexecute(ReadSkillInput(name="音乐MV制作"))
    assert ok.success and "完整流程正文" in ok.data["content"]
    miss = await tool.aexecute(ReadSkillInput(name="不存在的技能"))
    assert not miss.success and "可用 Skill" in miss.error


def _seed_storyboard(svc):
    """构造可控的最小故事板（覆盖 demo 数据），供目录化/编号检索测试用"""
    svc.state_dict["keyElements"] = [{
        "id": "ke-x", "title": "Element_测试元素", "desc": "视觉本质描述",
        "drafts": [{
            "id": "kd-1", "label": "概念图", "tag": "Agent", "mediaType": "image",
            "prompt": "深空背景中一条发光细线" * 50,  # 长提示词，不应进上下文
            "model": "", "imgUrl": "", "videoUrl": "", "audioUrl": "",
        }],
    }]
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []


def test_context_builder_draft_catalog_no_prompt(svc):
    """草稿卡只注入目录（编号/label/字数），提示词全文不进上下文"""
    _seed_storyboard(svc)
    ctx = build_agent_context(svc.state_dict, "bound")
    parsed = json.loads(ctx)
    draft = parsed["keyElements"][0]["drafts"][0]
    assert draft["prompt_chars"] == 550  # 11 字 x 50
    assert draft["index"] == "1-1" and "Element_测试元素" in ctx
    assert "深空背景中一条发光细线" * 50 not in ctx


async def test_read_draft_tool(svc):
    """read_draft：编号/ID 均可取回全文；draft_type 消歧；未命中报错"""
    _seed_storyboard(svc)
    tool = StoryboardReadDraftTool()
    # 编号命中
    ok = await tool.aexecute(ReadDraftInput(draft_id="1-1"))
    assert ok.success and ok.data["drafts"][0]["prompt"] == "深空背景中一条发光细线" * 50
    assert ok.data["drafts"][0]["group_title"] == "Element_测试元素"
    # 真实 ID 命中
    ok2 = await tool.aexecute(ReadDraftInput(draft_id="kd-1"))
    assert ok2.success
    # draft_type 不匹配 → 未命中
    miss = await tool.aexecute(ReadDraftInput(draft_id="1-1", draft_type="shot"))
    assert not miss.success and "组号-卡序号" in miss.error


def test_system_prompt_contains_catalog_not_full_text(tmp_path, monkeypatch, svc):
    """新契约：未选中 Skill 只进目录；选中的 Skill 全文硬注入（硬保障，
    非 FC 通道调不了 read_skill，模型不自觉调用时也不能丢流程规范）"""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
    skill_docs_mod.save_skill_doc(
        "demo-skill", "# 演示技能\n> 调用规则：演示用\n大段流程正文必须进 system prompt……",
    )
    skill_docs_mod.save_skill_doc(
        "other-skill", "# 未选技能\n> 调用规则：演示用\n未选技能的正文不应进 system prompt……",
    )
    planner = Planner()
    ctx = PlannerContext(use_studio_context=False, skill_name="演示技能")
    prompt = planner._build_system_prompt(ctx)
    assert "Skill 目录" in prompt and "演示技能" in prompt
    assert "read_skill" in prompt
    # 选中项全文硬注入
    assert "当前选中 Skill" in prompt
    assert "大段流程正文必须进 system prompt" in prompt
    # 未选中的 Skill 仍只有目录，全文不注入
    assert "未选技能的正文不应进 system prompt" not in prompt
