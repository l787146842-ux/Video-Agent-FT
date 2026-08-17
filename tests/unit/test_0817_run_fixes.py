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
