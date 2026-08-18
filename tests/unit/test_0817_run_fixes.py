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


# ---------- 0817 B18：注入瘦身（铁律4/5删除+全局设置阶段门控+channels死机制清除） ----------

def test_0817_iron_rules_template_drops_clauses_4_5():
    """铁律只留契约条款：提示词质量/产出形态归 Skill 章节唯一表述（用户裁决）。"""
    from src.video_agent.core.spec_rules import _IRON_RULES_DOC_BODY
    assert "提示词质量" not in _IRON_RULES_DOC_BODY
    assert "产出形态" not in _IRON_RULES_DOC_BODY
    for kept in ("执行优先", "拆解覆盖完整", "回复精简"):
        assert kept in _IRON_RULES_DOC_BODY, f"契约条款丢失: {kept}"


def test_0817_iron_rules_migration_strips_old_clauses():
    """存量项目铁律里的默认第4/5条升级迁移时剥离（幂等）。"""
    from src.video_agent.core.spec_rules import (
        IRON_RULES_DOC_NAME, ensure_iron_rules_doc,
    )
    old = (
        "# 执行铁律（系统约定）\n\n"
        "1. 执行优先：用户说什么就做什么。\n"
        "2. 拆解覆盖完整（自检核对）。\n"
        "3. 回复精简：写入草稿的提示词正文只允许一句话汇总。\n"
        "4. 提示词质量：写入草稿的生成提示词须逐条落实所选 Skill 的「提示词写法」规范\n"
        "   （电影级核心规则）；每张卡按画面内容个性化撰写。\n"
        "5. 产出形态：分镜视频提示词用中文叙事式多节拍写法，\n"
        "   节拍内部按 摄像机→主体→空间→音频 顺序展开。\n"
    )
    raw = {"documents": [{"id": "d1", "name": IRON_RULES_DOC_NAME, "content": old}]}
    assert ensure_iron_rules_doc(raw) is True
    content = raw["documents"][0]["content"]
    assert "提示词质量" not in content and "产出形态" not in content
    assert "执行优先" in content and "回复精简" in content
    assert ensure_iron_rules_doc(raw) is False  # 幂等


def test_0817_iron_rules_migration_from_spec_section_strips_clauses():
    """复查补漏：老项目规格文档内嵌铁律章节迁入时，若带默认第4/5条同样剥离。"""
    from src.video_agent.core.spec_rules import ensure_iron_rules_doc
    spec_with_iron = (
        "# 制片规格\n\n## 执行铁律\n"
        "1. 执行优先：用户说什么就做什么。\n"
        "2. 拆解覆盖完整（自检核对）。\n"
        "3. 回复精简。\n"
        "4. 提示词质量：须逐条落实 Skill 规范。\n"
        "5. 产出形态：中文叙事式多节拍写法。\n\n"
        "- 画幅比例：16:9\n"
    )
    raw = {"documents": [{"id": "s1", "name": "Final_Video_Spec.md",
                          "content": spec_with_iron}]}
    assert ensure_iron_rules_doc(raw) is True
    iron = next(d for d in raw["documents"] if "铁律" in d["name"])
    assert "提示词质量" not in iron["content"]
    assert "产出形态" not in iron["content"]
    assert "执行优先" in iron["content"]


def test_0817_global_settings_stage_gated():
    """全局设置注入阶段门控：规格规划阶段不注入，故事板起才注入。"""
    from src.video_agent.core.prompt_builder import PromptBuilder
    pb_empty = PromptBuilder(lambda: None, lambda: "p", get_raw_state=lambda: {
        "keyElements": [], "shots": [], "audioItems": []})
    assert pb_empty.stage_allows_global_settings() is False
    pb_ke = PromptBuilder(lambda: None, lambda: "p", get_raw_state=lambda: {
        "keyElements": [{"id": "g1", "title": "X", "drafts": []}],
        "shots": [], "audioItems": []})
    assert pb_ke.stage_allows_global_settings() is True
    pb_nostate = PromptBuilder(lambda: None, lambda: "p", get_raw_state=None)
    assert pb_nostate.stage_allows_global_settings() is True  # 无法探测时保守注入


def test_0817_channels_dead_mechanism_removed():
    """生成渠道已归全局设置唯一事实源：channels 注入机制整体清除
    （0818 B4：manifest 解析链退役，白名单符号随删）。"""
    from src.video_agent.core.prompt_builder import PromptBuilder
    from src.video_agent.web import skill_docs
    assert not hasattr(PromptBuilder, "build_generation_channels_block")
    assert not hasattr(skill_docs, "_MANIFEST_FLOW_KEYS")


# ---------- 0817 B17：语言闸拒收批内即时纠正（不拖到整工具重做） ----------

@pytest.mark.asyncio
async def test_0817_lang_gate_reject_triggers_inbatch_corrective(tmp_path, monkeypatch):
    """首批部分进展但撞语言闸 → 立即批内带拒因纠正重试一次，
    不得拖到整工具失败由外层从头重做（6 分钟级浪费）。"""
    from src.video_agent.core import prompt_gates
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_media_writer as mw

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "g1", "title": "程心", "drafts": [{"id": "d1", "prompt": ""}]},
        {"id": "g2", "title": "艾AA", "drafts": [{"id": "d2", "prompt": ""}]},
    ]
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    monkeypatch.setattr(mw, "tool_available", lambda skill, tool: True)
    monkeypatch.setattr(mw.exec_common, "_resolve_chat_provider",
                        lambda p="", m="": ("prov", "model"))
    monkeypatch.setattr(mw.exec_common, "_resolve_cascade_fast", lambda p, m: (p, m))

    calls = []

    async def fake_batch(tool_name, skill_name, skill_content, svc_, provider,
                         model, batch, spec, analysis_hint, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            svc_.state_dict["keyElements"][0]["drafts"][0]["prompt"] = "中文提示词一"
            return 1, [prompt_gates.LANG_EN_HARD_PREFIX + "：请改为中文正文后重新写入"], False
        svc_.state_dict["keyElements"][1]["drafts"][0]["prompt"] = "纠正后的中文提示词"
        return 1, [], False

    monkeypatch.setattr(mw, "_write_prompt_batch", fake_batch)
    tool = mw.WriteMediaPromptTool()
    result = await tool.aexecute(tool.get_input_schema()(skill_name="KE"))
    assert result.success, getattr(result, "error", "")
    assert len(calls) == 2, "应在批内即时纠正重试一次"
    assert calls[1].get("corrective") is True
    reasons = calls[1].get("corrective_reasons") or []
    assert any(prompt_gates.LANG_EN_HARD_PREFIX in str(r) for r in reasons)
    assert svc.state_dict["keyElements"][1]["drafts"][0]["prompt"]


# ---------- 0817 B16：执行器警告必须上抛到用户可见层 ----------

def test_0817_executor_warnings_surface_to_user(monkeypatch):
    """执行器成功结果携带的 warnings（如补拆失败缺失清单）必须升级为用户可见警告。"""
    import json
    from src.video_agent.adapters.base_chat import ChatResponse
    from src.video_agent.core.fc_tool_runner import FCToolRunner
    from src.video_agent.tools.base import ToolResult

    class _WarnTM:
        async def invoke_tool(self, name, args):
            return ToolResult(success=True, data={
                "warnings": ["拆解覆盖缺口：角色「罗辑」仍缺失"]})

    runner = FCToolRunner(tool_manager=_WarnTM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "storyboard_key_elements", "arguments": "{}"}},
    ])
    asyncio.run(runner.execute(response, injected_skill="AI-短剧一站式生成",
                               gate_override="all"))
    assert any("仍缺失" in w for w in runner.gate_warnings), runner.gate_warnings


# ---------- 0817 B15：script_analyze 幂等（剧本未变不重跑） ----------

@pytest.mark.asyncio
async def test_0817_script_analyze_idempotent(tmp_path, monkeypatch):
    """同一剧本重复分析 → 第二次直接复用既有结果（零 LLM 调用）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.skill_runtime import exec_tools

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：罗辑：黑暗森林。"}]
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    calls = {"n": 0}

    async def fake_json_call(system, user, **kwargs):
        calls["n"] += 1
        return {"summary": "人类 intercept 白色薄片", "key_points": ["降维打击"]}

    monkeypatch.setattr(exec_tools.exec_spec, "_llm_json_call", fake_json_call)
    monkeypatch.setattr(exec_tools, "tool_available", lambda skill, tool: True)
    monkeypatch.setattr(exec_tools, "_generate_soft_spec_candidates",
                        lambda *a, **k: _async_none())
    tool = exec_tools.ScriptAnalyzeTool()
    params = tool.get_input_schema()(skill_name="AI-短剧一站式生成", doc_name="剧本.md")
    r1 = await tool.aexecute(params)
    assert r1.success and calls["n"] == 1
    r2 = await tool.aexecute(params)
    assert r2.success and calls["n"] == 1, "剧本未变不得重跑 LLM"
    assert r2.data.get("cached") is True
    # 剧本内容变化 → 重新分析
    svc.state_dict["uploadedDocs"][0]["content"] = "剧本正文（改）：程心：好的。"
    r3 = await tool.aexecute(params)
    assert r3.success and calls["n"] == 2


def _async_none():
    async def _coro(*a, **k):
        return None
    return _coro()


# ---------- 0817 B14：规格文档卡不得落在用户选择消息之前 ----------

def test_0817_wizard_doc_card_deferred_until_after_user_msg(tmp_path):
    """向导落盘时卡片只挂起；用户消息先落库，卡片随后补落（顺序正确）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_consume import (
        _consume_spec_wizard, flush_pending_doc_card,
    )
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    svc.state_dict["interaction"] = {"spec_soft_candidates": {}}
    _consume_spec_wizard(svc, "画幅比例：16:9 横屏\n输出语言：中文")
    msgs = svc.get_chat_messages()
    assert not any(m.get("docCard") for m in msgs), "向导消费不得立刻落卡片"
    assert svc.state_dict["interaction"].get("spec_doc_card_pending") == "Final_Video_Spec.md"
    # 模拟真实落库次序：用户消息先落，再补卡片
    svc.add_chat_message("user", "画幅比例：16:9 横屏\n输出语言：中文")
    assert flush_pending_doc_card(svc, "turn-x") == "Final_Video_Spec.md"
    msgs = svc.get_chat_messages()
    assert [m.get("sender") for m in msgs[-2:]] == ["user", "agent"]
    assert msgs[-1].get("docCard") == "Final_Video_Spec.md"
    assert msgs[-1].get("turnId") == "turn-x"
    # 挂起已清：重复 flush 返回空串
    assert flush_pending_doc_card(svc, "turn-x") == ""


@pytest.mark.asyncio
async def test_0817_wizard_doc_card_live_visible_via_sse(tmp_path):
    """0817 B19：向导规格卡补落同时发 doc_written 即显事件（live 不靠刷新）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_consume import emit_pending_doc_card

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict.setdefault("interaction", {})["spec_doc_card_pending"] = "Final_Video_Spec.md"
    events = []

    async def fake_emit(ev):
        events.append(ev)

    name = await emit_pending_doc_card(svc, "t9", fake_emit)
    assert name == "Final_Video_Spec.md"
    assert events and events[0]["type"] == "doc_written"
    assert events[0]["name"] == "Final_Video_Spec.md"
    assert events[0]["turn_id"] == "t9"


# ---------- 0817 B23/B24：思考档不硬编码降档 + 剧本注入上限合一 ----------

def test_0817_script_inject_limit_unified_and_configurable():
    """上限合一移全局设置：可配、截断附可见警告。"""
    from src.video_agent.config import settings
    from src.video_agent.skill_runtime import exec_common

    old = settings.script_inject_limit
    try:
        object.__setattr__(settings, "script_inject_limit", 5000)
        assert exec_common._script_inject_limit() == 5000
        state = {"uploadedDocs": [{"id": "d1", "name": "长.md",
                                   "content": "字" * 6000}]}
        hint = exec_common._build_script_hint(state)
        assert "已截断" in hint and "script_inject_limit" in hint
        object.__setattr__(settings, "script_inject_limit", 20000)
        state2 = {"uploadedDocs": [{"id": "d1", "name": "短.md", "content": "字" * 100}]}
        assert "已截断" not in exec_common._build_script_hint(state2)
    finally:
        object.__setattr__(settings, "script_inject_limit", old)


def test_0817_executor_thinking_not_hardcoded_low():
    """0817 B23：平台不硬编码降档，默认沿用全局。"""
    from src.video_agent.config import settings
    from src.video_agent.skill_runtime import exec_common
    assert settings.executor_thinking_level == ""
    assert exec_common._executor_thinking() is None


def test_0817_script_inject_limit_in_runtime_whitelist():
    """0817 B24 复查：上限键纳入全局设置热更新白名单（独立钳制区间）。"""
    from src.video_agent.web.routes import runtime_settings as rs
    assert "script_inject_limit" in rs._CHAR_LIMIT_KEYS
    assert "script_inject_limit" in rs.RuntimeSettingsUpdate.model_fields


# ---------- 0817 B22：流程意见清除（平台只兜底，不包办排序） ----------

def test_0817_platform_no_next_step_opinions():
    """平台卡片/建议不再点名下一步：V1/V2/V8/V9/V10 清除钉死。"""
    from pathlib import Path
    from src.video_agent.core import gates_cards, round_end_policies as rep

    opts = gates_cards.spec_review_options({})
    assert all("开始拆解" not in o["label"] for o in opts)
    out = rep.suggest_next_actions({"keyElements": [{"id": "k", "drafts": []}]})
    assert out and "拆分镜" not in out[0]["label"]
    sd = Path("prompts/planner/skill_discipline.md").read_text(encoding="utf-8")
    assert "首次拆分故事板只创建 keyElement" not in sd
    assert "继续编写元素生图提示词草案" not in sd


def test_0817_storyboard_progress_note_objective():
    """客观进度描述：只报三类有无 + 暂停点指向 Skill，不含排序意见。"""
    from src.video_agent.core.prompt_builder import PromptBuilder
    pb = PromptBuilder(lambda: None, lambda: "p", get_raw_state=lambda: {
        "keyElements": [{"id": "k"}], "shots": [], "audioItems": []})
    note = pb.build_storyboard_progress_note()
    assert "关键元素：✓" in note and "分镜：✗" in note and "音频：✗" in note
    assert "Skill 流程基线" in note
    pb0 = PromptBuilder(lambda: None, lambda: "p", get_raw_state=lambda: {
        "keyElements": [], "shots": [], "audioItems": []})
    assert pb0.build_storyboard_progress_note() == ""


# ---------- 0817 B21：向导拼装合成记账入 actionLog ----------

def test_0817_wizard_assembly_recorded_in_action_log(tmp_path):
    """向导机械拼装不走工具通道 → 合成记账，drain 后合入轮末 actionLog。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_consume import (
        _consume_spec_wizard, drain_pending_action_log,
    )
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    svc.state_dict["interaction"] = {"spec_soft_candidates": {}}
    _consume_spec_wizard(svc, "画幅比例：16:9 横屏\n输出语言：中文")
    entries = drain_pending_action_log(svc)
    assert entries == ["系统拼装并写入规格文档 Final_Video_Spec.md"]
    assert drain_pending_action_log(svc) == []  # 取走即清


# ---------- 0817 B20：总结展示归 Skill 声明驱动（流程归位清查） ----------

class _LR:
    """AgentLoopResult 轻量替身（assemble_response 只读这些字段）。"""

    def __init__(self, text="", confirmation=""):
        self.text = text
        self.confirmation = confirmation
        self.warnings = []
        self.applied_actions = 0
        self.steps = 1
        self.trace = {}
        self.suggested_actions = []
        self.confirmation_options = []


def test_0817_summary_display_no_platform_injection(tmp_path, monkeypatch):
    """0818 架构板正批：平台不再强注入总结（收集卡中性、轮末只补客观
    完成记账）；总结展示归编排器暂停卡声明。"""
    from src.video_agent.core import gates_spec, planner_output

    st = {"usedSkills": ["no-sum"], "analysis": {"summary": "人类 intercept 薄片"}}
    msg, _ = gates_spec.spec_collect_card(st)
    assert "一句话故事总结" not in msg

    class _Ex:
        chat_inserts = []
        documents_written = []
        action_log = []

    resp = planner_output.assemble_response(
        _LR(text="解析完成。", confirmation="请确认规格"),
        executor=_Ex(), response_factory=lambda **kw: kw,
        analysis_summary="人类 intercept 薄片",
    )
    assert "人类 intercept 薄片" not in resp["confirmation"]
    assert "剧本分析已完成" in resp["text"]


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
    """轮末暂停/引导卡均接入一条龙豁免（G4 同类路径；0818：spec_collect 随门禁链退役）。"""
    import inspect
    from src.video_agent.core import round_end_policies as rep
    for fn in (rep._cond_structure_stage_review, rep._cond_stage_done_fallback):
        assert "flow_auto_continue" in inspect.getsource(fn)


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
    from src.video_agent.web import generation as gen_mod

    calls = []

    async def fake_chat(provider, model, messages, **kw):
        calls.append(list(messages))
        if len(calls) == 1:
            return ('{"summary": "x", "key_points": ["a" "b"]}', "stop")
        return ('{"summary": "x", "key_points": ["a", "b"]}', "stop")

    monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake_chat)
    monkeypatch.setattr(
        exec_spec.exec_common, "_resolve_chat_provider", lambda p, m: ("prov", "model"))
    data = asyncio.run(exec_spec._llm_json_call("sys", "user", max_tokens=512))
    assert data["summary"] == "x"
    assert len(calls) == 2
    # 纠正重试必须携拒因（C2 结构化拒因回喂）
    assert any("无法解析" in str(m.get("content")) for m in calls[1])


def test_0817_llm_json_call_raises_after_retry_still_malformed(monkeypatch, tmp_path):
    """重试仍畸形 → 抛明确错误，不吞。"""
    import asyncio
    import pytest as _pt
    from src.video_agent.skill_runtime import exec_spec, blackbox
    from src.video_agent.web import generation as gen_mod

    async def fake_chat(provider, model, messages, **kw):
        return ('{"summary": "x", "key_points": ["a" "b"]}', "stop")

    monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake_chat)
    monkeypatch.setattr(blackbox, "_BLACKBOX_DIR", tmp_path)
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
