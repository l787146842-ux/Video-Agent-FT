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


def test_trace_ok_matches_sse_on_normal_failure(monkeypatch):
    """普通工具失败：SSE 发 ok=False（live 红×），trace 也必须 ok=False，
    刷新重建时间线不得把失败渲染成绿√。"""
    events, actions = _run_with_trace(
        monkeypatch, "read_uploaded_doc", {"name": "三体简短版.md"}, {})
    sse = [e for e in events if e.get("type") == "tool_finished"]
    assert len(sse) == 1 and sse[0]["ok"] is False
    rec = [a for a in actions if a["name"] == "read_uploaded_doc"]
    assert len(rec) == 1
    assert rec[0]["ok"] is False, "trace 与 SSE 口径必须一致：失败记 False"


def test_trace_ok_neutral_on_spec_silent_reject(monkeypatch):
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


def test_spec_english_selection_disables_language_gate():
    """用户选英文 → 语言闸关闭，英文提示词放行。"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：英文"))
    assert ok and not any("全是英文" in h for h in hard)


def test_spec_chinese_selection_blocks_english_prompt():
    """用户选中文 → 英文提示词仍被拦（与平台默认一致）。"""
    _ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：中文"))
    assert any("几乎全是英文" in h for h in hard)


def test_user_selection_overrides_skill_english_lock():
    """优先级：用户选择 > Skill 声明。Skill 声明英文锁定但用户选中文 → 中文生效。"""
    _ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：中文"),
        rules={"cjk_min_ratio": 0})
    assert any("几乎全是英文" in h for h in hard)


def test_bilingual_selection_disables_language_gate():
    """用户选中英双语 → 语言闸不卡，中英皆可。"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：中英双语"))
    assert ok


def test_no_spec_keeps_platform_default():
    """无规格文档 → 维持平台默认（中文环境下英文被拦），不回归。"""
    _ok, hard, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", {"documents": []})
    assert any("几乎全是英文" in h for h in hard)


def test_injection_sentence_matches_spec_selection():
    """C1：语言裁决与闸机读同一事实——注入句随用户选择变化。
    （断言主体从已退役的 exec_common._prompt_language_rule 迁到通用路径
    注入面：prompt_gates 语言闸裁决口径，同输入同结论。）"""
    ok_en, hard_en, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：英文"))
    assert ok_en and not any("全是英文" in h for h in hard_en)
    _ok_cn, hard_cn, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：中文"))
    assert any("几乎全是英文" in h for h in hard_cn)
    ok_bi, hard_bi, _ = prompt_gates.validate_prompt_write(
        _ENG, "keyElement", _spec_state("输出语言：中英双语"))
    assert ok_bi and not any("全是英文" in h for h in hard_bi)


# ---------- 0817 B3：分组标题确定性归一（剥英文标识/编号前缀） ----------

def test_normalize_group_title_strips_prefixes():
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


def test_add_group_title_normalized_on_write(tmp_path):
    """文本轨建组入口：标题落盘前归一。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.action_executor import StateOperationExecutor
    svc = StateManager(str(tmp_path / "ws"))
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement",
        "title": "key_element_audio_瓦西里", "desc": "音色低沉",
    }])
    assert applied == 1
    titles = [g.get("title") for g in svc.state_dict.get("keyElements", [])]
    assert "瓦西里" in titles
    assert "key_element_audio_瓦西里" not in titles


def test_fc_create_group_title_normalized(tmp_path, monkeypatch):
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


def test_patch_group_title_normalized_on_model_path(tmp_path):
    """复查补漏：模型经 patch_group 改名也归一（用户 REST 路径不受影响）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.action_executor import StateOperationExecutor
    svc = StateManager(str(tmp_path / "ws"))
    ex = StateOperationExecutor(svc, gate_enabled=False)
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

def test_iron_rules_template_drops_clauses_4_5():
    """铁律只留契约条款：提示词质量/产出形态归 Skill 章节唯一表述（用户裁决）。"""
    from src.video_agent.core.spec_rules import _IRON_RULES_DOC_BODY
    assert "提示词质量" not in _IRON_RULES_DOC_BODY
    assert "产出形态" not in _IRON_RULES_DOC_BODY
    for kept in ("执行优先", "拆解覆盖完整", "回复精简"):
        assert kept in _IRON_RULES_DOC_BODY, f"契约条款丢失: {kept}"


def test_iron_rules_migration_strips_old_clauses():
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


def test_iron_rules_migration_from_spec_section_strips_clauses():
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


def test_global_settings_stage_gated():
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


def test_channels_dead_mechanism_removed():
    """生成渠道已归全局设置唯一事实源：channels 注入机制整体清除
    （0818 B4：manifest 解析链退役，白名单符号随删）。"""
    from src.video_agent.core.prompt_builder import PromptBuilder
    from src.video_agent.web import skill_docs
    assert not hasattr(PromptBuilder, "build_generation_channels_block")
    assert not hasattr(skill_docs, "_MANIFEST_FLOW_KEYS")


# ---------- 0817 B17：语言闸拒收批内即时纠正（不拖到整工具重做） ----------
# test_lang_gate_reject_triggers_inbatch_corrective 已随任务#36 B5 执行器一步退役删除：
# 被测对象（exec_media_writer.WriteMediaPromptTool 批内纠正）不复存在；
# 语言闸拒因回喂改由 fc_tool_runner 提示词闸承接。


# ---------- 0817 B16：工具警告必须上抛到用户可见层 ----------

def test_executor_warnings_surface_to_user(monkeypatch):
    """工具成功结果携带的 warnings（如拆解覆盖缺口清单）经 FCToolRunner
    必须升级为用户可见警告。"""
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
# test_script_analyze_idempotent 已随任务#36 B5 执行器一步退役删除：
# 被测对象（exec_tools.ScriptAnalyzeTool）不复存在。


# ---------- 0817 B14：规格文档卡不得落在用户选择消息之前 ----------

def test_wizard_doc_card_deferred_until_after_user_msg(tmp_path):
    """v2 批2：向导消费经 write_spec 节点提交（文档进 reducer 单事务），
    消费本身不落卡片；调用方于用户消息后投影文档卡（顺序正确同轮聚合）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_consume import _consume_spec_wizard

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    svc.state_dict["interaction"] = {"spec_soft_candidates": {}}
    note, name = _consume_spec_wizard(svc, "画幅比例：16:9 横屏\n输出语言：中文")
    assert note and name == "Final_Video_Spec.md"
    msgs = svc.get_chat_messages()
    assert not any(m.get("docCard") for m in msgs), "向导消费不得立刻落卡片"
    assert not (svc.state_dict.get("interaction") or {}).get(
        "spec_doc_card" + "_pending"), "挂起补卡旁路退役"
    # 文档由提交写入（reducer 单事务）
    assert any(d.get("name") == "Final_Video_Spec.md"
               for d in svc.state_dict.get("documents") or [])
    # 模拟真实落库次序：用户消息先落，卡片随后投影
    svc.add_chat_message("user", "画幅比例：16:9 横屏\n输出语言：中文")
    svc.add_chat_message("agent", "", doc_card=name, turn_id="turn-x")
    msgs = svc.get_chat_messages()
    assert [m.get("sender") for m in msgs[-2:]] == ["user", "agent"]
    assert msgs[-1].get("docCard") == "Final_Video_Spec.md"
    assert msgs[-1].get("turnId") == "turn-x"


@pytest.mark.asyncio
async def test_wizard_write_spec_node_commit_events(tmp_path):
    """v2 批2：向导落盘 = write_spec 节点提交——ArtifactCommitted +
    StageSucceeded(write_spec) + current_node→review_spec 同事务入账。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core.workflow_events import EventLedger
    from src.video_agent.web.chat_consume import _consume_spec_wizard

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    svc.state_dict["interaction"] = {"spec_soft_candidates": {}}
    note, name = _consume_spec_wizard(svc, "画幅比例：16:9 横屏")
    assert name == "Final_Video_Spec.md"
    run = svc.state_dict.get("workflow_run") or {}
    assert run.get("current_node") == "review_spec"
    assert "write_spec" in (run.get("completed_nodes") or [])
    types = [e.event_type for e in EventLedger(svc.state_dict).by_run(run["run_id"])]
    assert "ArtifactCommitted" in types and "StageSucceeded" in types


# ---------- 0817 B23/B24：思考档不硬编码降档 + 剧本注入上限合一 ----------
# test_script_inject_limit_unified_and_configurable 已随任务#36 B5 执行器一步退役删除：
# 被测对象（exec_common._script_inject_limit / _build_script_hint）不复存在。

# test_executor_thinking_not_hardcoded_low 已随任务#36 B5 执行器一步退役删除：
# 被测对象（exec_common._executor_thinking）不复存在；executor 档位默认改由
# model_policy 通用搭配钉死（test_model_policy.test_0819f_universal_defaults_low_for_executor_summary）。


def test_script_inject_limit_in_runtime_whitelist():
    """0817 B24 复查：上限键纳入全局设置热更新白名单（独立钳制区间）。"""
    from src.video_agent.web.routes import runtime_settings as rs
    assert "script_inject_limit" in rs._CHAR_LIMIT_KEYS
    assert "script_inject_limit" in rs.RuntimeSettingsUpdate.model_fields


# ---------- 0817 B22：流程意见清除（平台只兜底，不包办排序） ----------

def test_platform_no_next_step_opinions():
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


def test_storyboard_progress_note_objective():
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

def test_wizard_assembly_recorded_in_artifact_ledger(tmp_path):
    """向导机械拼装不进工具通道 → 产物账本一等条目（Rule2 v6
    ArtifactCommitted）：workflow_run.artifacts 含规格文档名，
    done 载荷经 documents_written 同轮下发（合成 actionLog 退役）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core import workflow_runtime
    from src.video_agent.web.chat_consume import (
        _consume_spec_wizard,
    )
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    svc.state_dict["interaction"] = {"spec_soft_candidates": {}}
    _consume_spec_wizard(svc, "画幅比例：16:9 横屏\n输出语言：中文")
    run = svc.state_dict.get("workflow_run") or {}
    assert "Final_Video_Spec.md" in (run.get("artifacts") or [])


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


def test_summary_display_no_platform_injection(tmp_path, monkeypatch):
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

def test_wizard_note_no_forced_ke_pause(tmp_path):
    """向导回执不得钉死「拆关键元素并暂停」：流程与暂停点归 Skill 阶段边界。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.chat_consume import _consume_spec_wizard
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    svc.state_dict["interaction"] = {"spec_soft_candidates": {}}
    note, _name = _consume_spec_wizard(svc, "画幅比例：16:9 横屏\n输出语言：中文")
    assert note, "规格选择应被向导消费落盘"
    assert "开始拆分关键元素" not in note, "不得 prose 指定具体子步骤"
    assert "暂停等用户确认拆分方案" not in note, "不得 prose 钉死暂停点"
    assert "暂停点以" in note, "暂停归属必须指向 Skill 阶段边界"


def test_pause_note_objective_spec_state(tmp_path):
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
async def test_flow_directive_tool_sets_flag_and_clears(tmp_path, monkeypatch):
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core import prompt_gates
    from src.video_agent.tools.document_tools import FlowDirectiveTool
    svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    tool = FlowDirectiveTool()
    res = await tool.aexecute(tool.get_input_schema()(auto_continue=True))
    assert res.success and prompt_gates.flow_auto_continue(svc.state_dict)
    # 批5：授权经控制流 trace 留痕（可追溯，Context ≠ Consent）
    from src.video_agent.core.tracer import AgentTracer
    events = AgentTracer.get_instance().control_flow_events()
    assert any(e.get("event") == "autonomy_granted" for e in events), \
        "自主性档位授予必须进控制流 trace"
    # 任务开始清除（按消息生效语义）
    assert prompt_gates.clear_flow_directive(svc.state_dict) is True
    assert not prompt_gates.flow_auto_continue(svc.state_dict)
    assert prompt_gates.clear_flow_directive(svc.state_dict) is False


@pytest.mark.asyncio
async def test_flow_directive_text_track_sets_flag(tmp_path):
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core import prompt_gates
    from src.video_agent.web.action_executor import StateOperationExecutor
    svc = StateManager(str(tmp_path / "ws"))
    ex = StateOperationExecutor(svc, gate_enabled=False)
    assert ex.execute([{"action": "flow_directive", "auto_continue": True}]) == 1
    assert prompt_gates.flow_auto_continue(svc.state_dict)


@pytest.mark.asyncio
async def test_spec_write_allowed_under_auto_continue(tmp_path, monkeypatch):
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


def test_pause_suppressions_wired_to_auto_continue():
    """轮末暂停/引导卡均接入一条龙豁免（G4 同类路径；0818：spec_collect 随门禁链退役）。"""
    import inspect
    from src.video_agent.core import round_end_policies as rep
    for fn in (rep._cond_structure_stage_review, rep._cond_stage_done_fallback):
        assert "flow_auto_continue" in inspect.getsource(fn)


# ---------- 0817 B9：机器覆盖验收（Skill 声明驱动） ----------
# test_script_speakers_extraction / test_skill_declares_audio_from_skill_doc /
# test_coverage_missing_audio_and_speakers / test_coverage_no_audio_check_when_skill_silent
# 已随任务#36 B5 执行器一步退役删除：被测对象（exec_split._script_speakers /
# skill_declares_audio / _coverage_missing_key_elements）不复存在；拆解覆盖完整
# 改由模型按铁律第 2 条自查 + fc_tool_runner _structure_integrity_gate 客观校验承接。


# ---------- 0817 B4：执行器 JSON 畸形 → 带拒因纠正重试（C2） ----------
# test_llm_json_call_corrective_retry_on_malformed /
# test_llm_json_call_raises_after_retry_still_malformed 已随任务#36 B5
# 执行器一步退役删除：被测对象（exec_spec._llm_json_call 与 blackbox 档案）
# 不复存在；畸形 JSON 纠正重试随执行器内层 LLM 调用一并退役。


# ---------- 0817 B6：后台任务生命周期状态可观测（静默死亡留痕） ----------

def test_task_lifecycle_done_and_cancel_statuses(tmp_path):
    """worker 正常结束=done、被取消=cancelled，状态均落账（可观测性前提）。"""
    from src.video_agent.web.agent_task_manager import AgentTaskManager
    from src.video_agent.web.task_store import TaskStore

    mgr = AgentTaskManager.__new__(AgentTaskManager)
    mgr._tasks = {}
    # 任务 #24：持久化已迁 sqlite kv 表，测试注入临时库（替代旧 _persist_path）
    mgr._store = TaskStore(tmp_path / "tasks.sqlite3")

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
