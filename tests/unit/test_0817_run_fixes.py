"""0817 运行事故回归：trace 与 SSE 成败口径一致（失败不得刷新后变绿√）。

事故现场：6666 项目 2026-08-17 运行，live 时间线红×的工具失败，
刷新后 trace 重建却显示绿√——失败分支 trace ok 与 SSE ok 口径反转。
"""

import asyncio
import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.tools.base import ToolResult


class _FailTM:
    """所有工具一律失败（模拟 read_uploaded_doc / script_analyze 失败轮）。"""

    async def invoke_tool(self, name, args):
        return ToolResult(success=False, error="模拟失败：文档未就绪")


def _run_with_trace(monkeypatch, tool_name, args, raw_state):
    """跑一次 execute，返回 (SSE 事件列表, trace 挂起动作列表)。"""
    AgentTracer.reset()
    tracer = AgentTracer.get_instance()
    tracer.start_trace("0817-regression")
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: raw_state))
    events = []

    async def on_event(ev):
        events.append(ev)

    runner = FCToolRunner(tool_manager=_FailTM())
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": tool_name, "arguments": json.dumps(args)}},
    ])
    asyncio.run(runner.execute(response, on_event=on_event))
    return events, list(tracer._pending_actions)


def test_0817_trace_ok_matches_sse_on_normal_failure(monkeypatch):
    """普通工具失败：SSE 发 ok=False（live 红×），trace 也必须 ok=False，
    刷新重建时间线不得把失败渲染成绿√。"""
    events, actions = _run_with_trace(
        monkeypatch, "read_uploaded_doc", {"name": "三体简短版.md"}, {})
    sse = [e for e in events if e.get("type") == "tool_finished"]
    assert len(sse) == 1 and sse[0]["ok"] is False
    rec = [a for a in actions if a["name"] == "read_uploaded_doc"]
    assert len(rec) == 1
    assert rec[0]["ok"] is False, "trace 与 SSE 口径必须一致：失败记 False"


def test_0817_trace_ok_neutral_on_spec_silent_reject(monkeypatch):
    """规格手写被向导拒收（814G3 静默）：用户侧中性（无红×），
    trace 与 SSE 同口径记 ok=True。"""
    events, actions = _run_with_trace(
        monkeypatch, "document_write",
        {"name": "Final_Video_Spec.md", "content": "x"},
        {"documents": []})
    sse = [e for e in events if e.get("type") == "tool_finished"]
    assert len(sse) == 1 and sse[0]["ok"] is True
    rec = [a for a in actions if a["name"] == "document_write"]
    assert len(rec) == 1
    assert rec[0]["ok"] is True, "规格静默拒收对用户中性，trace 不得红×"


# ---------- 0817 B2：语言单一事实源接入用户「输出语言」选择 ----------

from src.video_agent.core import prompt_gates

_ENG = (
    "A character turnaround sheet of an elderly male commander with metallic voice. "
    "Front view, side view, back view. Identical clothing across all views. "
    "Plain neutral gray background, soft even studio lighting, photorealistic cinematic film still."
)


def _spec_state(lang_line: str):
    return {"documents": [{"name": "Final_Video_Spec.md",
                           "content": f"# 最终成片规格\n- 画幅比例：16:9\n- {lang_line}\n"}]}


def test_0817_spec_english_selection_disables_language_gate():
    """用户选英文 → 语言闸关闭，英文提示词放行。"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：英文"))
    assert ok and not any("全是英文" in h for h in hard)


def test_0817_spec_chinese_selection_blocks_english_prompt():
    """用户选中文 → 英文提示词仍被拦（与平台默认一致）。"""
    _ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：中文"))
    assert any("几乎全是英文" in h for h in hard)


def test_0817_user_selection_overrides_skill_english_lock():
    """优先级：用户选择 > Skill 声明。Skill 声明英文锁定但用户选中文 → 中文生效。"""
    _ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：中文"),
        rules={"cjk_min_ratio": 0})
    assert any("几乎全是英文" in h for h in hard)


def test_0817_bilingual_selection_disables_language_gate():
    """用户选中英双语 → 语言闸不卡，中英皆可。"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：中英双语"))
    assert ok


def test_0817_no_spec_keeps_platform_default():
    """无规格文档 → 维持平台默认（中文环境下英文被拦），不回归。"""
    _ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", {"documents": []})
    assert any("几乎全是英文" in h for h in hard)


def test_0817_injection_sentence_matches_spec_selection():
    """C1：执行器注入句与闸机读同一裁决——注入句随用户选择变化。"""
    from src.video_agent.skill_runtime import exec_common
    s_en = exec_common._prompt_language_rule(
        "AI-短剧一站式生成", _spec_state("输出语言：英文"))
    assert "英文" in s_en
    s_cn = exec_common._prompt_language_rule(
        "AI-短剧一站式生成", _spec_state("输出语言：中文"))
    assert "中文" in s_cn and "中英双语" not in s_cn
    s_bi = exec_common._prompt_language_rule(
        "AI-短剧一站式生成", _spec_state("输出语言：中英双语"))
    assert "中英双语" in s_bi


# ---------- 0817 B3：分组标题确定性归一（剥英文标识/编号前缀） ----------

def test_0817_normalize_group_title_strips_prefixes():
    """模型模仿 Skill 英文标识当标题 → 确定性剥前缀，保留中文主体。"""
    from src.video_agent.state import storyboard_ops as ops
    assert ops.normalize_group_title("key_element_audio_瓦西里") == "瓦西里"
    assert ops.normalize_group_title("key_element_audio_领航员") == "领航员"
    assert ops.normalize_group_title("元素场景_01 木星轨道星环号球形舱") == "木星轨道星环号球形舱"
    assert ops.normalize_group_title("元素道具_01 白色薄膜") == "白色薄膜"
    assert ops.normalize_group_title("程心") == "程心"
    # 剥完无中文主体 → 原样保留（机器不造名）
    assert ops.normalize_group_title("element_scene_01") == "element_scene_01"
    assert ops.normalize_group_title("元素场景_01") == "元素场景_01"


def test_0817_add_group_title_normalized_on_write(tmp_path):
    """文本轨/执行器轨建组入口：标题落盘前归一。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.action_executor import StudioActionExecutor
    svc = StateManager(str(tmp_path / "ws"))
    ex = StudioActionExecutor(svc, gate_enabled=False)
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement",
        "title": "key_element_audio_瓦西里", "desc": "音色低沉",
    }])
    assert applied == 1
    titles = [g.get("title") for g in svc.state_dict.get("keyElements", [])]
    assert "瓦西里" in titles
    assert "key_element_audio_瓦西里" not in titles


def test_0817_fc_create_group_title_normalized(tmp_path, monkeypatch):
    """FC 轨 storyboard_create_group 同覆盖（G4）。"""
    import asyncio
    from src.video_agent.state.manager import StateManager
    from src.video_agent.tools.storyboard_tools import StoryboardCreateGroupTool

    svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    tool = StoryboardCreateGroupTool()
    asyncio.run(tool.aexecute(tool.get_input_schema()(
        group_type="keyElement", title="元素场景_02 太阳系外缘启示号控制舱", desc="x")))
    titles = [g.get("title") for g in svc.state_dict.get("keyElements", [])]
    assert "太阳系外缘启示号控制舱" in titles


def test_0817_patch_group_title_normalized_on_model_path(tmp_path):
    """复查补漏：模型经 patch_group 改名也归一（用户 REST 路径不受影响）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.action_executor import StudioActionExecutor
    svc = StateManager(str(tmp_path / "ws"))
    ex = StudioActionExecutor(svc, gate_enabled=False)
    ex.execute([{
        "action": "add_group", "group_type": "keyElement",
        "title": "瓦西里", "desc": "x",
    }])
    gid = svc.state_dict["keyElements"][0]["id"]
    ex.execute([{
        "action": "patch_group", "group_id": gid, "group_type": "keyElement",
        "patch": {"title": "key_element_audio_瓦西里"},
    }])
    assert svc.state_dict["keyElements"][0]["title"] == "瓦西里"


# ---------- 0817 B13：轮间提示去 prose 越权（客观状态机械生成） ----------

def test_0817_wizard_note_no_forced_ke_pause(tmp_path):
    """向导回执不得钉死「拆关键元素并暂停」：流程与暂停点归 Skill 阶段边界。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_consume import _consume_spec_wizard
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    svc.state_dict["interaction"] = {"spec_soft_candidates": {}}
    note = _consume_spec_wizard(svc, "画幅比例：16:9 横屏\n输出语言：中文")
    assert note, "规格选择应被向导消费落盘"
    assert "开始拆分关键元素" not in note, "不得 prose 指定具体子步骤"
    assert "暂停等用户确认拆分方案" not in note, "不得 prose 钉死暂停点"
    assert "暂停点以" in note, "暂停归属必须指向 Skill 阶段边界"


def test_0817_pause_note_objective_spec_state(tmp_path):
    """暂停消费提示按客观状态生成：规格已存在说已写入，绝不再出现「先写入规格文档」。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_consume import _consume_pending_confirmation
    svc = StateManager(str(tmp_path / "ws"))
    inter = svc.state_dict.setdefault("interaction", {})
    inter["awaiting_confirmation"] = True
    inter["confirmation_message"] = "请审阅"
    svc.state_dict["documents"] = [
        {"name": "Final_Video_Spec.md", "content": "# 规格\n- 画幅比例：16:9\n"}]
    note = _consume_pending_confirmation(svc, "继续")
    assert "先写入规格文档" not in note, "固定 prose 指令已废除"
    assert "规格文档已写入" in note, "客观状态：规格存在必须如实告知"
    # 无规格项目：不得谎称已写入
    inter["awaiting_confirmation"] = True
    inter["confirmation_message"] = "请审阅"
    svc.state_dict["documents"] = []
    note2 = _consume_pending_confirmation(svc, "继续")
    assert "规格文档已写入" not in note2
    assert "先写入规格文档" not in note2


# ---------- 0817 B11：flow_directive 一条龙（模型解读+平台机械执行+按消息生效） ----------

@pytest.mark.asyncio
async def test_0817_flow_directive_tool_sets_flag_and_clears(tmp_path, monkeypatch):
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core import prompt_gates
    from src.video_agent.tools.document_tools import FlowDirectiveTool
    svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    tool = FlowDirectiveTool()
    res = await tool.aexecute(tool.get_input_schema()(auto_continue=True))
    assert res.success and prompt_gates.flow_auto_continue(svc.state_dict)
    # 任务开始清除（按消息生效语义）
    assert prompt_gates.clear_flow_directive(svc.state_dict) is True
    assert not prompt_gates.flow_auto_continue(svc.state_dict)
    assert prompt_gates.clear_flow_directive(svc.state_dict) is False


@pytest.mark.asyncio
async def test_0817_flow_directive_text_track_sets_flag(tmp_path):
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core import prompt_gates
    from src.video_agent.web.action_executor import StudioActionExecutor
    svc = StateManager(str(tmp_path / "ws"))
    ex = StudioActionExecutor(svc, gate_enabled=False)
    assert ex.execute([{"action": "flow_directive", "auto_continue": True}]) == 1
    assert prompt_gates.flow_auto_continue(svc.state_dict)


@pytest.mark.asyncio
async def test_0817_spec_write_allowed_under_auto_continue(tmp_path, monkeypatch):
    """一条龙下模型可按 Skill 填写规格（用户指令=规格同意，留痕）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.tools.document_tools import DocumentWriteTool
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    svc.state_dict.setdefault("interaction", {})["auto_continue"] = True
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    tool = DocumentWriteTool()
    res = await tool.aexecute(tool.get_input_schema()(
        name="Final_Video_Spec.md", content="- 输出语言：中文\n"))
    assert res.success, res.error


def test_0817_pause_suppressions_wired_to_auto_continue():
    """轮末三处暂停/引导卡均接入一条龙豁免（G4 同类路径）。"""
    import inspect
    from src.video_agent.core import round_end_policies as rep
    for fn in (rep._cond_structure_stage_review, rep._cond_stage_done_fallback):
        assert "flow_auto_continue" in inspect.getsource(fn)
    assert "flow_auto_continue" in inspect.getsource(rep._apply_spec_collect)


# ---------- 0817 B9：机器覆盖验收（Skill 声明驱动） ----------

def test_0817_script_speakers_extraction():
    from src.video_agent.skill_runtime import exec_split
    text = "### 场一\n罗辑：黑暗森林。\n程心：好的。\n旁白：远处。\n罗辑：再来。"
    assert exec_split._script_speakers(text) == ["罗辑", "程心"]


def test_0817_skill_declares_audio_from_skill_doc():
    from src.video_agent.skill_runtime import exec_split
    # 真实 Skill 声明 key_element_audio → 验收才查音色
    assert exec_split.skill_declares_audio("AI-短剧一站式生成") is True
    assert exec_split.skill_declares_audio("不存在的Skill") is False


def test_0817_coverage_missing_audio_and_speakers(tmp_path):
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_split
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "1", "title": "瓦西里", "badgeLabel": "人物", "desc": "x"},
    ]
    svc.state_dict["uploadedDocs"] = [
        {"id": "d", "name": "剧本.md", "content": "瓦西里：收到。\n领航员：明白。"}
    ]
    missing = exec_split._coverage_missing_key_elements(svc, "AI-短剧一站式生成")
    # 台词人领航员未拆 + 瓦西里缺音色组
    assert any("领航员" in m for m in missing)
    assert any("瓦西里" in m and "音色" in m for m in missing)
    # 补齐后 → 无缺失
    svc.state_dict["keyElements"].append(
        {"id": "2", "title": "领航员", "badgeLabel": "人物", "desc": "x"})
    svc.state_dict["keyElements"].append(
        {"id": "3", "title": "瓦西里", "badgeLabel": "音频-角色", "desc": "音色"})
    svc.state_dict["keyElements"].append(
        {"id": "4", "title": "领航员", "badgeLabel": "音频-角色", "desc": "音色"})
    assert exec_split._coverage_missing_key_elements(svc, "AI-短剧一站式生成") == []


def test_0817_coverage_no_audio_check_when_skill_silent(tmp_path):
    """Skill 未声明音色 → 不查音色（不会硬拆出音色组）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_split
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "1", "title": "瓦西里", "badgeLabel": "人物", "desc": "x"},
    ]
    svc.state_dict["uploadedDocs"] = [
        {"id": "d", "name": "剧本.md", "content": "瓦西里：收到。"}
    ]
    assert exec_split._coverage_missing_key_elements(svc, "不存在的Skill") == []


# ---------- 0817 B4：执行器 JSON 畸形 → 带拒因纠正重试（C2） ----------

def test_0817_llm_json_call_corrective_retry_on_malformed(monkeypatch):
    """首次返回畸形 JSON → 携拒因重试一次 → 二次正确则解析成功。"""
    import asyncio
    from src.video_agent.skill_runtime import exec_spec

    calls = []

    async def fake_chat(provider, model, messages, **kw):
        calls.append(list(messages))
        if len(calls) == 1:
            return ('{"summary": "x", "key_points": ["a" "b"]}', "stop")
        return ('{"summary": "x", "key_points": ["a", "b"]}', "stop")

    monkeypatch.setattr(exec_spec._gen, "call_chat_completion", fake_chat)
    monkeypatch.setattr(
        exec_spec.exec_common, "_resolve_chat_provider", lambda p, m: ("prov", "model"))
    data = asyncio.run(exec_spec._llm_json_call("sys", "user", max_tokens=512))
    assert data["summary"] == "x"
    assert len(calls) == 2
    # 纠正重试必须携拒因（C2 结构化拒因回喂）
    assert any("无法解析" in str(m.get("content")) for m in calls[1])


def test_0817_llm_json_call_raises_after_retry_still_malformed(monkeypatch):
    """重试仍畸形 → 抛明确错误，不吞。"""
    import asyncio
    import pytest as _pt
    from src.video_agent.skill_runtime import exec_spec

    async def fake_chat(provider, model, messages, **kw):
        return ('{"summary": "x", "key_points": ["a" "b"]}', "stop")

    monkeypatch.setattr(exec_spec._gen, "call_chat_completion", fake_chat)
    monkeypatch.setattr(
        exec_spec.exec_common, "_resolve_chat_provider", lambda p, m: ("prov", "model"))
    with _pt.raises(Exception, match="无法解析"):
        asyncio.run(exec_spec._llm_json_call("sys", "user", max_tokens=512))


# ---------- 0817 B6：后台任务生命周期状态可观测（静默死亡留痕） ----------

def test_0817_task_lifecycle_done_and_cancel_statuses(tmp_path):
    """worker 正常结束=done、被取消=cancelled，状态均落账（可观测性前提）。"""
    from src.video_agent.web.agent_task_manager import AgentTaskManager

    mgr = AgentTaskManager.__new__(AgentTaskManager)
    mgr._tasks = {}
    mgr._persist_path = tmp_path / "tasks.json"

    async def worker_ok():
        await asyncio.sleep(0.02)

    async def worker_long():
        await asyncio.sleep(5)

    async def main():
        rec = mgr.create("proj-x", worker_ok)
        await asyncio.sleep(0.1)
        done_status = mgr.get(rec["task_id"])["status"]
        rec2 = mgr.create("proj-x", worker_long)
        await asyncio.sleep(0.02)
        mgr.stop(rec2["task_id"])
        await asyncio.sleep(0.05)
        return done_status, mgr.get(rec2["task_id"])["status"]

    done_status, cancel_status = asyncio.run(main())
    assert done_status == "done"
    assert cancel_status == "cancelled"
