"""Skill 上传即注册 + 独立执行器运行时测试。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry
from src.video_agent.web.action_executor import StudioActionExecutor


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """每个测试独立 Skill 目录 + 清空运行时注册表。"""
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


@pytest.fixture(autouse=True)
def _bridge_stream_calls(monkeypatch):
    """流式拆解/提示词批次桥接：把 call_chat_completion_stream 转发到各测试
    已 patch 的 call_chat_completion（整段内容一次性回放给 on_delta），
    测试无需感知 Q5 流式逐条落盘改造。"""
    from src.video_agent.skill_runtime import executors as ex_mod

    async def fake_stream(provider, model, messages, *, max_tokens=8192,
                          temperature=0.7, timeout=180, on_delta=None,
                          reasoning_sink=None, thinking_level=None):
        content, finish = await ex_mod.call_chat_completion(
            provider, model, messages, max_tokens=max_tokens
        )
        if on_delta and content:
            await on_delta(content)
        return content, finish

    monkeypatch.setattr(ex_mod, "call_chat_completion_stream", fake_stream)


def _write(slug: str, content: str):
    sd.save_skill_doc(slug, content)


def test_save_registers_and_delete_unregisters():
    _write(
        "demo",
        "# 演示\n> 调用规则：测试\n"
        "<storyboard_key_elements>\n关键元素规范\n</storyboard_key_elements>\n"
        "<generation>\n生成规范\n</generation>\n",
    )
    entry = registry.get_entry("demo")
    assert entry is not None
    # 只有对应章节存在的执行器才会注册
    assert entry.available_tools == ["storyboard_key_elements", "audio_generate"]
    assert "关键元素规范" in registry.tool_sections("demo", "storyboard_key_elements")
    assert registry.tool_sections("demo", "script_analyze") == ""

    sd.delete_skill_doc("demo")
    assert registry.get_entry("demo") is None
    assert not registry.tool_available("demo", "storyboard_key_elements")


def test_edit_re_registers():
    _write("demo2", "# 演示2\n> 调用规则：测试\n<script_analyze>\n分析\n</script_analyze>\n")
    assert "分析" in registry.tool_sections("demo2", "script_analyze")
    # 编辑后章节变化 → 重新注册
    _write("demo2", "# 演示2\n> 调用规则：测试\n<storyboard_shots>\n分镜\n</storyboard_shots>\n")
    assert registry.tool_sections("demo2", "script_analyze") == ""
    assert "分镜" in registry.tool_sections("demo2", "storyboard_shots")


def test_prompt_draft_section_merges_write_media_prompt_and_write_the_prompt():
    _write(
        "demo3",
        "# 演示3\n> 调用规则：测试\n"
        "<write_media_prompt>\n草案说明\n</write_media_prompt>\n"
        "<write_the_prompt>\n写法规范\n</write_the_prompt>\n",
    )
    sec = registry.tool_sections("demo3", "write_media_prompt")
    assert "草案说明" in sec
    assert "写法规范" in sec


def test_executor_runtime_block_forbids_false_claims():
    """回归（7777 事故）：【执行方式】条款必须明确要求「真实执行后才可声称完成」，
    不再含「无需手动调用执行器」这类会让模型误以为系统自动拆解的歧义表述。"""
    _write(
        "demo-fc",
        "# 演示防虚报\n> 调用规则：测试\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n",
    )
    pb = PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )
    block = pb.build_selected_skill_block("演示防虚报")
    # 新基线（模型可见严禁清零后）：防虚报语义改客观表述——
    # 「真的执行后才可声称完成」+「虚报会被状态对账识破」，行为约束不变
    assert "必须真的执行" in block
    assert "才可声称完成" in block
    assert "虚报结果会被状态对账识破" in block
    assert "无需手动调用" not in block


def test_executor_runtime_block_lists_tools():
    _write(
        "demo4",
        "# 演示4\n> 调用规则：测试\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n"
        "<storyboard_shots>\n分镜\n</storyboard_shots>\n"
        "<storyboard_audio>\n音频\n</storyboard_audio>\n"
        "<write_media_prompt>\n提示词\n</write_media_prompt>\n"
        "<generation>\n生成\n</generation>\n"
        "<video_assembler>\n组装\n</video_assembler>\n",
    )
    pb = PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )
    block = pb.build_selected_skill_block("演示4")
    assert "已注册独立执行器" in block
    for t in ("script_analyze", "storyboard_key_elements", "storyboard_shots",
              "storyboard_audio", "write_media_prompt", "audio_generate", "video_assembler"):
        assert t in block
    # 章节全文不再注入
    assert "关键元素" not in block


def test_is_async_action():
    assert StudioActionExecutor._is_async_action({"action": "storyboard_key_elements"})
    assert StudioActionExecutor._is_async_action({"action": "storyboard_shots"})
    assert StudioActionExecutor._is_async_action({"action": "script_analyze"})
    assert not StudioActionExecutor._is_async_action({"action": "add_group"})
    assert not StudioActionExecutor._is_async_action({"action": "continue"})


@pytest.mark.asyncio
async def test_execute_async_dispatches_executor_action(monkeypatch):
    """文本轨执行器动作走 execute_async：按动作名构造执行器并等待独立 LLM 结果。"""
    import tempfile

    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import (
        ScriptAnalyzeInput,
        SkillToolResult,
    )
    from src.video_agent.state.manager import StateManager

    svc = StateManager(tempfile.mkdtemp())
    called = {}

    class FakeTool:
        name = "script_analyze"

        def get_input_schema(self):
            return ScriptAnalyzeInput

        async def aexecute(self, params):
            called["skill"] = params.skill_name
            return SkillToolResult(success=True, data={"detail": "已分析（必须展示）"})

    monkeypatch.setattr(
        ex_mod, "build_executor_tool",
        lambda name: FakeTool() if name == "script_analyze" else None,
    )
    ex = StudioActionExecutor(svc, gate_enabled=False)
    applied = await ex.execute_async_locked([
        {"action": "script_analyze", "skill_name": "演示", "doc_name": "剧本.md"},
    ])
    assert applied == 1
    assert called["skill"] == "演示"


@pytest.mark.asyncio
async def test_script_analyze_awaits_llm_call(monkeypatch, tmp_path):
    """回归：执行器内 LLM 调用必须 await（曾把协程当结果解包导致解析素材报错）。"""
    import tempfile

    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import ScriptAnalyzeInput, ScriptAnalyzeTool
    from src.video_agent.state.manager import StateManager

    _write(
        "ana-skill",
        "# 分析\n> 调用规则：测试\n<script_analyze>\n分析并总结\n</script_analyze>\n",
    )
    called = {}

    async def fake_chat(provider, model, messages, **kwargs):
        called["provider"] = provider
        return ('{"summary": "一句话总结", "key_points": ["要点"]}', "stop")

    def fake_resolve(provider="", model=""):
        return ("fake-provider", "fake-model")

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文"}
    ]
    monkeypatch.setattr(ex_mod, "call_chat_completion", fake_chat)
    monkeypatch.setattr(ex_mod, "_resolve_chat_provider", fake_resolve)
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    tool = ScriptAnalyzeTool()
    result = await tool.aexecute(
        ScriptAnalyzeInput(skill_name="分析", doc_name="剧本.md")
    )
    assert result.success, result.error
    assert result.data["summary"] == "一句话总结"
    assert called.get("provider") == "fake-provider"
    # 分析结果已写入状态
    assert svc.state_dict["analysis"]["summary"] == "一句话总结"


def test_build_script_hint_injects_full_text_even_with_summary():
    """回归（6666 事故）：已有摘要时拆解阶段仍须注入剧本正文，否则分镜无法忠实台词。"""
    from src.video_agent.skill_runtime.executors import _build_script_hint

    state = {
        "uploadedDocs": [{"id": "d1", "name": "剧本.md", "content": "场一：角色A说：你好。" * 20}],
        "analysis": {"summary": "一句话总结"},
    }
    hint = _build_script_hint(state)
    assert "一句话总结" in hint
    assert "剧本《剧本.md》正文" in hint
    assert "角色A说：你好" in hint


def test_build_script_hint_truncates_long_script():
    from src.video_agent.skill_runtime import executors as ex_mod

    long_text = "字" * (ex_mod._SCRIPT_INJECT_LIMIT + 500)
    state = {"uploadedDocs": [{"id": "d1", "name": "长剧本.md", "content": long_text}]}
    hint = ex_mod._build_script_hint(state)
    assert "已截断" in hint
    assert len(hint) < len(long_text)


def test_add_group_title_field_fallback(tmp_path):
    """回归（6666 事故）：模型用 name/element_id 等非 title 字段时不得静默落默认标题。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.action_executor import StudioActionExecutor

    svc = StateManager(str(tmp_path / "ws"))
    ex = StudioActionExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "name": "罗辑", "desc": "角色描述"},
        {"action": "add_group", "group_type": "keyElement", "element_id": "[Element_ChengXin]"},
        {"action": "add_group", "group_type": "shot", "title": "镜头一",
         "roughDesc": "场景：太空。旁白：二向箔漂浮。"},
    ])
    assert applied == 3
    kes = svc.state_dict["keyElements"]
    assert kes[-2]["title"] == "罗辑"
    assert kes[-1]["title"] == "[Element_ChengXin]"
    # 分镜只写 roughDesc 不写 desc 时自动同步，前端卡片不显示空白
    shot = svc.state_dict["shots"][-1]
    assert shot["desc"] == "场景：太空。旁白：二向箔漂浮。"


@pytest.mark.asyncio
async def test_key_elements_selfcheck_fills_missing(monkeypatch, tmp_path):
    """关键元素拆解后自动跑第二遍自检：对照剧本补建遗漏元素（防漏拆）。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import (
        StoryboardKeyElementsTool, StoryboardSplitInput,
    )
    from src.video_agent.state.manager import StateManager

    _write(
        "ke-skill",
        "# KE\n> 调用规则：测试\n<storyboard_key_elements>\n拆解规范\n</storyboard_key_elements>\n",
    )
    calls = {"n": 0}

    async def fake_chat(provider, model, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # 首拆：只拆出一个元素（模拟概括收敛）
            return ('[{"action":"add_group","group_type":"keyElement",'
                    '"title":"罗辑","desc":"角色"}]', "stop")
        # 自检轮：已补齐后交白卷（真实模型对照已拆清单输出 []）
        titles = [g["title"] for g in svc.state_dict.get("keyElements") or []]
        if "关一帆" in titles:
            return ("[]", "stop")
        return ('[{"action":"add_group","group_type":"keyElement",'
                '"title":"关一帆","desc":"遗漏角色"}]', "stop")

    def fake_resolve(provider="", model=""):
        return ("fake-provider", "fake-model")

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：关一帆与程心在蓝星"}
    ]
    monkeypatch.setattr(ex_mod, "call_chat_completion", fake_chat)
    monkeypatch.setattr(ex_mod, "_resolve_chat_provider", fake_resolve)
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    tool = StoryboardKeyElementsTool()
    result = await tool.aexecute(StoryboardSplitInput(skill_name="KE"))
    assert result.success, result.error
    titles = [g["title"] for g in svc.state_dict["keyElements"]]
    assert "罗辑" in titles
    assert "关一帆" in titles  # 自检轮补建成功
    assert "自检对照剧本补建了 1 个遗漏元素" in result.data["detail"]


def test_apply_actions_no_gate_rules_typeerror(tmp_path):
    """回归：_apply_actions 不再把 gate_rules 传给构造函数（4444 TypeError）。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    applied, warnings = ex_mod._apply_actions(
        svc,
        [{"action": "add_group", "group_type": "keyElement", "title": "Element_A"}],
        "# 剧本生视频（需上传剧本）\n> 调用规则：测试\n",
    )
    assert applied == 1
    assert svc.state_dict["keyElements"][-1]["title"] == "Element_A"


# ---------- 8888 事故回归：无标题分组拒收与标题别名扩展 ----------

def test_apply_actions_rejects_untitled_add_group(tmp_path):
    """8888 事故：首拆 JSON 缺 title 字段时不得静默落默认标题「Agent 新建分组」，
    执行器批次直接拒收（零产出由调用方回退重试）。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    before = len(svc.state_dict.get("keyElements") or [])
    applied, warnings = ex_mod._apply_actions(
        svc,
        [{"action": "add_group", "group_type": "keyElement",
          "desc": "只有描述没有标题", "badgeLabel": "人物"}],
        "# 剧本生视频（需上传剧本）\n> 调用规则：测试\n",
    )
    assert applied == 0
    assert len(svc.state_dict.get("keyElements") or []) == before  # 未建垃圾卡
    assert any("title" in w for w in warnings)


def test_apply_actions_mixed_batch_keeps_titled(tmp_path):
    """混合批次：带标题的照常写入，无标题的被丢弃（部分成功不触发重试）。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    applied, warnings = ex_mod._apply_actions(
        svc,
        [
            {"action": "add_group", "group_type": "keyElement", "title": "程心"},
            {"action": "add_group", "group_type": "keyElement", "desc": "无标题项"},
        ],
        "# 剧本生视频（需上传剧本）\n> 调用规则：测试\n",
    )
    assert applied == 1
    assert svc.state_dict["keyElements"][-1]["title"] == "程心"
    assert any("丢弃" in w for w in warnings)


def test_add_group_title_alias_element_name(tmp_path):
    """8888 事故：标题兜底链扩展 element_name/group_title 等别名。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.action_executor import StudioActionExecutor

    svc = StateManager(str(tmp_path / "ws"))
    ex = StudioActionExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "element_name": "AA"},
        {"action": "add_group", "group_type": "keyElement", "group_title": "预警中心"},
    ])
    assert applied == 2
    titles = [g["title"] for g in svc.state_dict["keyElements"][-2:]]
    assert titles == ["AA", "预警中心"]


def test_apply_actions_rejects_cross_stage_groups(tmp_path):
    """宪法 P2 下沉：阶段边界由代码校验——KE 执行器里建分镜/音频直接拒收。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    applied, warnings = ex_mod._apply_actions(
        svc,
        [
            {"action": "add_group", "group_type": "keyElement", "title": "程心"},
            {"action": "add_group", "group_type": "shot", "title": "越界分镜"},
            {"action": "add_group", "group_type": "audio", "title": "越界音频"},
        ],
        "# 剧本生视频（需上传剧本）\n> 调用规则：测试\n",
        only_group_type="keyElement",
    )
    assert applied == 1  # 只落下 keyElement
    assert svc.state_dict["shots"] == [] or all(
        g["title"] != "越界分镜" for g in svc.state_dict["shots"])
    assert any("越界" in w for w in warnings)


def test_add_draft_label_smart_matching(tmp_path):
    """回归（proj-1786169643 事故）：add_draft 未携带有效 group_id 时，
    按 label 名称匹配对应分组，不再盲捡第一个分组（曾导致 24 条提示词全进程心组）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.action_executor import StudioActionExecutor

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "[Element_Cheng_Xin] 程心", "desc": "", "drafts": []},
        {"id": "ke-2", "title": "[Element_Ai_AA] 艾AA", "desc": "", "drafts": []},
        {"id": "ke-3", "title": "[Element_Dual_Vector_Foil] 二向箔", "desc": "", "drafts": []},
    ]
    ex = StudioActionExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_draft", "group_id": "current",
         "draft": {"label": "艾AA - 角色概念图", "prompt": "艾AA的提示词", "mediaType": "image"}},
        {"action": "add_draft", "group_id": "current",
         "draft": {"label": "二向箔 - 道具概念图", "prompt": "二向箔的提示词", "mediaType": "image"}},
    ])
    assert applied == 2
    kes = {g["title"]: g for g in svc.state_dict["keyElements"]}
    # 各归其位：不再全堆进第一个分组（程心）
    assert len(kes["[Element_Cheng_Xin] 程心"]["drafts"]) == 0
    assert len(kes["[Element_Ai_AA] 艾AA"]["drafts"]) == 1
    assert len(kes["[Element_Dual_Vector_Foil] 二向箔"]["drafts"]) == 1


def test_prompt_coverage_note_detects_misdelivery():
    """防虚报：提示词集中塞进一个分组时，覆盖校验必须报异常。"""
    from src.video_agent.skill_runtime.executors import _prompt_coverage_note

    state = {"keyElements": [
        {"title": "A", "drafts": [{"prompt": "已写"}, {"prompt": "也写在这"}]},
        {"title": "B", "drafts": []},
        {"title": "C", "drafts": []},
    ]}
    note = _prompt_coverage_note(state, "all_keyElements")
    assert "1/3" in note
    # 全覆盖时无警示
    state_ok = {"keyElements": [
        {"title": "A", "drafts": [{"prompt": "x"}]},
        {"title": "B", "drafts": [{"prompt": "y"}]},
    ]}
    assert _prompt_coverage_note(state_ok, "all_keyElements") == ""
    # target 无法判定类别时不校验
    assert _prompt_coverage_note(state, "") == ""


def test_executor_runtime_block_includes_flow_baseline():
    """P0-2：executors 模式注入当前 Skill 的 <planner> 流程基线。"""
    _write(
        "flow-skill",
        "# 流程\n> 调用规则：测试\n"
        "<planner>\n阶段逻辑：先 script_analyze → document_write → storyboard_key_elements\n</planner>\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n",
    )
    pb = PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )
    block = pb.build_selected_skill_block("流程")
    assert "流程基线" in block
    assert "阶段逻辑" in block
    assert "script_analyze" in block


def test_add_group_badge_label_persisted_and_patchable(tmp_path):
    """898 需求：关键元素类别徽标（人物/场景/道具）可随 add_group 写入，
    且双击编辑（update_group patch badgeLabel）能持久化（曾在白名单外被静默丢弃）。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    ex = StudioActionExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement",
         "title": "程心", "desc": "前执剑人", "badgeLabel": "人物"},
        {"action": "add_group", "group_type": "keyElement", "title": "二向箔"},
    ])
    assert applied == 2
    kes = {g["title"]: g for g in svc.state_dict["keyElements"]}
    assert kes["程心"].get("badgeLabel") == "人物"
    assert "badgeLabel" not in kes["二向箔"]
    # 双击徽标编辑（update_group）必须能改写并持久化
    applied = ex.execute([
        {"action": "update_group", "group_id": kes["二向箔"]["id"],
         "group_type": "keyElement", "patch": {"badgeLabel": "道具"}},
    ])
    assert applied == 1
    assert kes["二向箔"]["badgeLabel"] == "道具"


def test_add_draft_accepts_patch_field_fallback(tmp_path):
    """898 事故回归：模型把建卡字段放进 patch/fields 而非 draft 时，
    不得静默落成空默认草稿，提示词必须写入。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "罗辑", "desc": "", "drafts": []},
    ]
    ex = StudioActionExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_draft", "group_id": "ke-1",
         "patch": {"label": "概念图", "prompt": "罗辑的概念图提示词", "mediaType": "image"}},
    ])
    assert applied == 1
    draft = svc.state_dict["keyElements"][0]["drafts"][0]
    assert draft["prompt"] == "罗辑的概念图提示词"
    assert draft["label"] == "概念图"


@pytest.mark.asyncio
async def test_write_media_prompt_batched_fill(monkeypatch, tmp_path):
    """898/2222 事故回归：提示词按缺失分组分批写入，每批落盘后才可返回成功。"""
    import json

    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import WriteMediaPromptInput, WriteMediaPromptTool
    from src.video_agent.state.manager import StateManager

    _write("wmp-skill", "# 写提示词\n> 调用规则：测试\n<write_the_prompt>\n写中文提示词\n</write_the_prompt>\n")
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "程心", "desc": "x", "drafts": []},
        {"id": "ke-2", "title": "罗辑", "desc": "x", "drafts": []},
    ]
    calls = {"n": 0}

    async def fake_chat(provider, model, messages, **kwargs):
        calls["n"] += 1
        # 每批按状态里当前仍缺提示词的分组写入（长度需过关键元素结构闸）
        acts = [
            {"action": "add_draft", "group_id": g["id"],
             "draft": {"label": "概念图", "mediaType": "image",
                       "prompt": f"{g['title']}：年轻人类女性，面容温婉坚毅，身着极简流线型白色深空常服，"
                                 "神态克制悲悯，冷色调光影对比强烈，构图居中半身特写，氛围肃穆。"}}
            for g in svc.state_dict["keyElements"]
            if not any((d.get("prompt") or "").strip() for d in g["drafts"])
        ]
        return ('```studio-actions\n' + json.dumps(acts, ensure_ascii=False) + '\n```', "stop")

    monkeypatch.setattr(ex_mod, "call_chat_completion", fake_chat)
    monkeypatch.setattr(ex_mod, "_resolve_chat_provider", lambda p="", m="": ("fake", "fake-model"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    tool = WriteMediaPromptTool()
    result = await tool.aexecute(
        WriteMediaPromptInput(skill_name="写提示词", target="all_keyElements")
    )
    assert result.success, result.error
    for g in svc.state_dict["keyElements"]:
        assert g["drafts"][0]["prompt"].startswith(f"{g['title']}：")


@pytest.mark.asyncio
async def test_write_media_prompt_batches_split_by_size(monkeypatch, tmp_path):
    """2222 事故回归：待写分组超过单批上限时必须分批多次调用，不得一次输出全部。"""
    import json

    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import WriteMediaPromptInput, WriteMediaPromptTool
    from src.video_agent.state.manager import StateManager

    _write("wmp-skill", "# 写提示词\n> 调用规则：测试\n<write_the_prompt>\n写中文提示词\n</write_the_prompt>\n")
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": f"ke-{i}", "title": f"元素{i}", "desc": "x", "drafts": []}
        for i in range(1, 4)
    ]
    calls = {"n": 0, "batch_sizes": []}

    async def fake_chat(provider, model, messages, **kwargs):
        calls["n"] += 1
        # 模型只为本批列出的分组写入（从提示词里解析本批 group_id）
        import re as _re
        text = messages[-1]["content"]
        batch_ids = set(_re.findall(r"group_id=(ke-\d+)", text))
        missing = [g for g in svc.state_dict["keyElements"]
                   if g["id"] in batch_ids
                   and not any((d.get("prompt") or "").strip() for d in g["drafts"])]
        calls["batch_sizes"].append(len(missing))
        acts = [
            {"action": "add_draft", "group_id": g["id"],
             "draft": {"label": "概念图", "mediaType": "image",
                       "prompt": f"{g['title']}：主体造型清晰，材质细节丰富，冷色调光影对比强烈，"
                                 "构图居中，氛围肃穆克制，背景深空星点散布，整体写实。"}}
            for g in missing
        ]
        return ('```studio-actions\n' + json.dumps(acts, ensure_ascii=False) + '\n```', "stop")

    monkeypatch.setattr(ex_mod, "call_chat_completion", fake_chat)
    monkeypatch.setattr(ex_mod, "_resolve_chat_provider", lambda p="", m="": ("fake", "fake-model"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    monkeypatch.setattr(ex_mod, "_PROMPT_BATCH_SIZE", 2)

    tool = WriteMediaPromptTool()
    result = await tool.aexecute(
        WriteMediaPromptInput(skill_name="写提示词", target="all_keyElements")
    )
    assert result.success, result.error
    # 3 个分组按每批 2 个拆成两次 LLM 调用（第二次只剩 1 个）
    assert calls["n"] == 2
    assert calls["batch_sizes"] == [2, 1]
    assert all(
        (g["drafts"][0]["prompt"] or "").strip()
        for g in svc.state_dict["keyElements"]
    )


@pytest.mark.asyncio
async def test_write_media_prompt_fails_when_no_progress(monkeypatch, tmp_path):
    """898 事故回归：批次零进展（落成空卡）时判失败，不得返回 success 供主模型虚报。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import WriteMediaPromptInput, WriteMediaPromptTool
    from src.video_agent.state.manager import StateManager

    _write("wmp-skill", "# 写提示词\n> 调用规则：测试\n<write_the_prompt>\n写中文提示词\n</write_the_prompt>\n")
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "程心", "desc": "x", "drafts": []},
        {"id": "ke-2", "title": "罗辑", "desc": "x", "drafts": []},
    ]

    async def fake_chat(provider, model, messages, **kwargs):
        # 只建空草稿卡，不写提示词（模拟 898 事故现场）
        return ('```studio-actions\n[{"action":"add_draft","group_id":"ke-1"},'
                '{"action":"add_draft","group_id":"ke-2"}]\n```', "stop")

    monkeypatch.setattr(ex_mod, "call_chat_completion", fake_chat)
    monkeypatch.setattr(ex_mod, "_resolve_chat_provider", lambda p="", m="": ("fake", "fake-model"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    tool = WriteMediaPromptTool()
    result = await tool.aexecute(
        WriteMediaPromptInput(skill_name="写提示词", target="all_keyElements")
    )
    assert not result.success
    assert "覆盖异常" in (result.error or "")
    assert "2/2" in (result.error or "")


@pytest.mark.asyncio
async def test_write_media_prompt_corrective_retry_after_empty_batch(monkeypatch, tmp_path):
    """3333 事故回归：批次零进展（建空卡）时批内纠正重试补齐，不提前判失败。"""
    import json

    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import WriteMediaPromptInput, WriteMediaPromptTool
    from src.video_agent.state.manager import StateManager

    _write("wmp-skill", "# 写提示词\n> 调用规则：测试\n<write_the_prompt>\n写中文提示词\n</write_the_prompt>\n")
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "程心", "desc": "x", "drafts": []},
        {"id": "ke-2", "title": "罗辑", "desc": "x", "drafts": []},
    ]
    calls = {"n": 0}

    async def fake_chat(provider, model, messages, **kwargs):
        calls["n"] += 1
        system = messages[0]["content"]
        missing = [g for g in svc.state_dict["keyElements"]
                   if not any((d.get("prompt") or "").strip() for d in g["drafts"])]
        if "纠正" not in system:
            # 首遍只建空卡（模拟 3333 第 2 批降级输出）
            acts = [{"action": "add_draft", "group_id": g["id"]} for g in missing]
        else:
            # 纠正轮：补齐提示词
            acts = [
                {"action": "add_draft", "group_id": g["id"],
                 "draft": {"label": "概念图", "mediaType": "image",
                           "prompt": f"{g['title']}：主体造型清晰，材质细节丰富，冷色调光影对比强烈，"
                                     "构图居中，氛围肃穆克制，背景深空星点散布，整体写实。"}}
                for g in missing
            ]
        return ('```studio-actions\n' + json.dumps(acts, ensure_ascii=False) + '\n```', "stop")

    monkeypatch.setattr(ex_mod, "call_chat_completion", fake_chat)
    monkeypatch.setattr(ex_mod, "_resolve_chat_provider", lambda p="", m="": ("fake", "fake-model"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    tool = WriteMediaPromptTool()
    result = await tool.aexecute(
        WriteMediaPromptInput(skill_name="写提示词", target="all_keyElements")
    )
    assert result.success, result.error
    assert calls["n"] == 2  # 首遍空卡 + 纠正轮补齐，未升级为整工具失败
    for g in svc.state_dict["keyElements"]:
        assert (g["drafts"][-1]["prompt"] or "").strip()


def test_feedback_carries_tool_detail():
    """3333 事故回归：script_analyze 的一句话总结随回喂传给模型，不再只报「执行成功」。"""
    from src.video_agent.core.fc_tool_runner import format_tool_results

    feedback = format_tool_results([{
        "name": "script_analyze", "ok": True,
        "data": {"summary": "太阳系被二维化的一曲悲歌",
                 "detail": "已分析《剧本.md》。一句话总结：太阳系被二维化的一曲悲歌 （必须展示）"},
    }])
    assert isinstance(feedback, str)
    assert "太阳系被二维化的一曲悲歌" in feedback
    assert "必须展示" in feedback


@pytest.mark.asyncio
async def test_script_analyze_detail_carries_summary(monkeypatch, tmp_path):
    """2222 项目回归：一句话总结必须随工具结果回传并要求展示，防模型吞掉成果。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import ScriptAnalyzeInput, ScriptAnalyzeTool
    from src.video_agent.state.manager import StateManager

    _write(
        "ana-skill2",
        "# 分析2\n> 调用规则：测试\n<script_analyze>\n分析并总结\n</script_analyze>\n",
    )

    async def fake_chat(provider, model, messages, **kwargs):
        return ('{"summary": "太阳系被二维化的一曲悲歌", "key_points": ["要点"]}', "stop")

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [{"id": "d1", "name": "剧本.md", "content": "正文"}]
    monkeypatch.setattr(ex_mod, "call_chat_completion", fake_chat)
    monkeypatch.setattr(ex_mod, "_resolve_chat_provider", lambda p="", m="": ("fake", "fake-model"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    tool = ScriptAnalyzeTool()
    result = await tool.aexecute(
        ScriptAnalyzeInput(skill_name="分析2", doc_name="剧本.md")
    )
    assert result.success, result.error
    assert "太阳系被二维化的一曲悲歌" in result.data["detail"]
    assert "讲给用户" in result.data["detail"]
