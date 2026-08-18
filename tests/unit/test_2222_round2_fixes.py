# -*- coding: utf-8 -*-
"""2222（二轮）复盘修复回归 — S2 事故台账配套用例。

本文件覆盖：
① 铁律删「不得拦截/强制暂停」半句 + 存量文档自动升级（spec_rules）
② 执行器机械调用思考档位按调用覆盖（executor_thinking_level）
后续批次（截断保险/边界自适应/规格注入/向导自动检测）陆续追加。
"""
import inspect

import pytest

from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.config import settings
from src.video_agent.core import spec_rules
from src.video_agent.skill_runtime import executors as ex_mod
from src.video_agent.skill_runtime import exec_common
from src.video_agent.web import generation as gen_mod


# ---------- 铁律删句（模板 + 存量自动升级） ----------

_OLD_CLAUSE = "系统不得拦截用户要求的操作，也不得强制暂停等待确认"


def test_2222_iron_rules_template_no_block_clause_removed():
    """模板第 1 条只保留『照常执行 + 末尾警告』，拦截/强制暂停半句已删。"""
    body = spec_rules._IRON_RULES_DOC_BODY
    assert _OLD_CLAUSE not in body
    assert "1. 执行优先" in body
    assert "先照常执行" in body and "再在回复末尾给出警告。" in body


def test_2222_existing_iron_doc_auto_upgraded_on_ensure():
    """存量项目铁律文档带旧半句：ensure 时精确删除，其余内容不动。"""
    old = (
        "# 执行铁律（系统约定，按优先级执行：用户指令 > 本文档 + 制片规格 > Skill/系统默认）\n\n"
        "1. 执行优先：用户说什么就做什么。用户指令与本文档/制片规格/Skill 流程冲突时，先照常执行，\n"
        "   再在回复末尾给出警告；系统不得拦截用户要求的操作，也不得强制暂停等待确认。\n"
        "2. 拆解覆盖完整（自检核对）。\n"
        "- 用户自定义条款：保持原样。\n"
    )
    state = {"documents": [{"name": "执行铁律.md", "content": old}]}
    changed = spec_rules.ensure_iron_rules_doc(state)
    assert changed
    doc = spec_rules.find_iron_rules_doc(state)
    assert _OLD_CLAUSE not in doc["content"]
    assert "再在回复末尾给出警告。" in doc["content"]
    assert "- 用户自定义条款：保持原样。" in doc["content"]  # 用户其它编辑不动


def test_2222_existing_iron_doc_upgrade_idempotent():
    """升级幂等：已升级的文档再次 ensure 不报变化。"""
    state = {"documents": [{"name": "执行铁律.md",
                            "content": spec_rules._IRON_RULES_DOC_BODY.strip() + "\n"}]}
    assert spec_rules.ensure_iron_rules_doc(state) is False


def test_2222_migrated_spec_section_strips_block_clause():
    """老项目规格文档内嵌铁律章节迁移时，旧半句一并清除。"""
    spec = (
        "# 最终成片规格\n\n## 执行铁律（系统约定）\n\n"
        "1. 执行优先：……先照常执行，再在回复末尾给出警告；"
        "系统不得拦截用户要求的操作，也不得强制暂停等待确认。\n"
        "2. 拆解覆盖完整（自检核对）。\n"
    )
    state = {"documents": [{"name": "Final_Video_Spec.md", "content": spec}]}
    changed = spec_rules.ensure_iron_rules_doc(state)
    assert changed
    iron = spec_rules.find_iron_rules_doc(state)
    assert iron is not None
    assert _OLD_CLAUSE not in iron["content"]
    assert "执行铁律" not in state["documents"][-1]["content"]


# ---------- 思考档位按调用覆盖（executor_thinking_level） ----------

def test_2222_thinking_override_wins_over_global():
    """本次调用档位覆盖全局配置；覆盖值非法时不下发；显式空串=原生（814H7）。"""
    adapter = OpenAICompatChatAdapter(base_url="http://x", api_key="k", model="m")
    payload: dict = {}
    adapter._apply_thinking_level(payload, "low")
    assert payload.get("reasoning_effort") == "low"
    # 814H7：全局默认空（原生）→ 覆盖 None 时不下发字段
    payload2: dict = {}
    adapter._apply_thinking_level(payload2, None)
    assert "reasoning_effort" not in payload2
    # 全局置 high + 覆盖 None → 回落全局 high；显式 "" → 原生不下发（UI「默认」档）
    old = settings.llm_thinking_level
    object.__setattr__(settings, "llm_thinking_level", "high")
    try:
        payload2b: dict = {}
        adapter._apply_thinking_level(payload2b, None)
        assert payload2b.get("reasoning_effort") == "high"
        payload2c: dict = {}
        adapter._apply_thinking_level(payload2c, "")
        assert "reasoning_effort" not in payload2c
    finally:
        object.__setattr__(settings, "llm_thinking_level", old)
    # 覆盖值非法 → 不下发
    payload3: dict = {}
    adapter._apply_thinking_level(payload3, "xhigh")
    assert "reasoning_effort" not in payload3


def test_2222_executor_thinking_default_low_and_empty_falls_back():
    """0817 B23：默认不硬编码降档（空 = 沿用全局）；全局设置配置值生效。"""
    assert ex_mod._executor_thinking() is None
    object.__setattr__(settings, "executor_thinking_level", "low")
    try:
        assert ex_mod._executor_thinking() == "low"
    finally:
        object.__setattr__(settings, "executor_thinking_level", "")


def test_2222_all_executor_llm_calls_pass_thinking_level():
    """G4 全局化：执行器全部 5 个 LLM 调用点都传思考档位，不许漏路径。
    R4a 拆分后扫描实现模块；五轮 S5 新增 exec_split（拆解域切出，含自检调用点）；
    0817 B4 新增 _llm_json_call 畸形 JSON 纠正重试调用点；
    调用统一经 _gen.（web.generation）模块属性。"""
    from src.video_agent.skill_runtime import (
        exec_common, exec_spec, exec_split, exec_tools,
        exec_media_writer, exec_media_gen,
    )

    src = (inspect.getsource(exec_common) + inspect.getsource(exec_spec)
           + inspect.getsource(exec_tools) + inspect.getsource(exec_split)
           + inspect.getsource(exec_media_writer) + inspect.getsource(exec_media_gen))
    # 0818-1111 B2：执行器 LLM 出口收敛为 exec_common.executor_stream_text
    # （帮手内部是唯一 _gen 流式出口）。业务调用点 5 = 改道 4 + 流式拆解直调 1；
    # 源码特征 6 = 5 业务点 + 帮手内部 1。调用点变化时必须同步本断言。
    n_redirects = src.count("await exec_common.executor_stream_text(")
    n_stream = src.count("await _gen.call_chat_completion_stream(")
    n_legacy = src.count("await _gen.call_chat_completion(")
    assert n_legacy == 0, "执行器层不得残留非流式调用"
    assert n_redirects == 4 and n_stream == 2
    # 5 调用点传思考档 + _executor_thinking 定义本身 1 处
    assert src.count("_executor_thinking()") == 6


# ---------- 截断保险全局化（流式拆解回滚 + 扩额整体重试） ----------

def test_2222_rollback_split_groups_removes_only_new(tmp_path):
    """回滚只删本次拆解新建的分组，拆解前既有分组不动，幂等。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    shots = svc.state_dict.setdefault("shots", [])
    ids_before = {g.get("id") for g in shots}  # demo 项目可能自带分组，全量快照
    n_before = len(shots)
    shots.append({"id": "shot-new-1", "title": "残品1"})
    shots.append({"id": "shot-new-2", "title": "残品2"})

    n = ex_mod._rollback_split_groups(svc, "shot", ids_before)
    assert n == 2
    assert len(svc.state_dict["shots"]) == n_before
    assert all(g["id"] in ids_before for g in svc.state_dict["shots"])
    assert ex_mod._rollback_split_groups(svc, "shot", ids_before) == 0  # 幂等


def test_2222_split_truncation_retry_pinned():
    """钉死：流式拆解截断 → 回滚 → 扩额整体重试，不再收部分成功。"""
    src = inspect.getsource(ex_mod._run_storyboard_split)
    assert "正在回退重试补全" not in src  # 只承诺不执行的空头文案已删
    assert src.count("_stream_actions_progressive(") == 2  # 首拆 + 截断后整体重试
    assert "_rollback_split_groups(svc, _split_kind, _ids_before)" in src
    # 顺序钉死：回滚重试必须先于零产出兜底（重试仍零产出才进兜底）
    assert src.index("_rollback_split_groups(") < src.index("if not applied:")


# ---------- 拆解边界按 Skill 章节结构自适应 ----------

def test_2222_merged_section_allows_all_three_kinds():
    """「AI-短剧」storyboard_designer 同含三类职责 → 三个拆解执行器均放行三类。"""
    from src.video_agent.skill_runtime import registry

    registry.register_skill("AI-短剧一站式生成")
    for tool in ("storyboard_key_elements", "storyboard_shots", "storyboard_audio"):
        kinds = set(ex_mod._split_kinds_for_section(tool, "AI-短剧一站式生成"))
        assert kinds == {"keyElement", "shot", "audio"}, f"{tool} 应放行三类，实际 {kinds}"


def test_2222_separate_sections_keep_single_kind_boundary():
    """三个独立章节（各带「本节职责：只创建 X 分组」声明）→ 各执行器只放行自己类别。"""
    from src.video_agent.skill_runtime import registry
    from src.video_agent.web import skill_docs as sd

    # 自包含桩（不依赖任何产品 Skill 文件，10.12-G1）：三章各自单一职责
    sd.save_skill_doc(
        "分章边界测试桩",
        "# 分章边界测试桩\n> 调用规则：测试\n"
        "<storyboard_key_elements>\n**本节职责（最高优先级）**：只创建关键元素"
        "（keyElement）分组，严禁创建分镜（shot）或音频（audio）分组。\n"
        "</storyboard_key_elements>\n"
        "<storyboard_shots>\n**本节职责（最高优先级）**：只创建分镜（shot）分组，"
        "不得创建关键元素（keyElement）与音频（audio）分组。\n</storyboard_shots>\n"
        "<storyboard_audio>\n**本节职责（最高优先级）**：只创建音频（audio）分组，"
        "不得创建关键元素（keyElement）与分镜（shot）分组。\n</storyboard_audio>\n",
    )
    registry.register_skill("分章边界测试桩")
    assert ex_mod._split_kinds_for_section("storyboard_shots", "分章边界测试桩") == ["shot"]
    assert ex_mod._split_kinds_for_section("storyboard_audio", "分章边界测试桩") == ["audio"]
    assert ex_mod._split_kinds_for_section(
        "storyboard_key_elements", "分章边界测试桩") == ["keyElement"]
    registry.reset_registry()


def test_2222_apply_actions_multi_kind_accepts_and_single_rejects(tmp_path):
    """多类别边界放行混类 add_group；单类别边界仍拒收越界。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    mixed = [
        {"action": "add_group", "group_type": "keyElement", "title": "程心"},
        {"action": "add_group", "group_type": "shot", "title": "冬眠苏醒",
         "sceneRefs": ["s1"]},
        {"action": "add_group", "group_type": "audio", "title": "BGM"},
    ]
    n, warns = ex_mod._apply_actions(svc, list(mixed), "", only_group_type="keyElement,shot,audio")
    assert n == 3 and not warns

    n2, warns2 = ex_mod._apply_actions(svc, list(mixed), "", only_group_type="keyElement")
    assert n2 == 1 and any("越界分组被拒收" in w for w in warns2)


@pytest.mark.asyncio
async def test_2222_split_truncation_retry_success_path(monkeypatch, tmp_path):
    """正向路径钉死：首拆截断 → 回滚 + 扩额重试；重试完整则无拼接、不进对账流程。"""
    from src.video_agent.skill_runtime import registry
    from src.video_agent.skill_runtime.executors import StoryboardShotsTool, StoryboardSplitInput
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web import skill_docs as sd

    # 复用既有测试桩「截断技能」（不新增 Skill 文件，10.12-G1）
    sd.save_skill_doc(
        "截断技能", "# T\n> 调用规则：测试\n<storyboard_shots>\n拆解规范\n</storyboard_shots>\n",
    )
    registry.register_skill("截断技能")

    calls = {"n": 0}

    async def fake_stream(provider, model, messages, *, max_tokens=8192,
                          temperature=0.7, timeout=180, on_delta=None,
                          reasoning_sink=None, thinking_level=None):
        calls["n"] += 1
        if calls["n"] == 1:
            content = ('[{"action":"add_group","group_type":"shot","title":"镜1",'
                       '"duration":"10s","sceneRefs":["s1"]}]')
            finish = "length"  # 首拆撞上限
        else:
            content = ('[{"action":"add_group","group_type":"shot","title":"镜1",'
                       '"duration":"10s","sceneRefs":["s1"]},'
                       '{"action":"add_group","group_type":"shot","title":"镜2",'
                       '"duration":"12s","sceneRefs":["s1"]}]')
            finish = "stop"  # 扩额重试完整产出
        if on_delta:
            await on_delta(content)
        return content, finish

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["shots"] = []
    monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake_stream)
    monkeypatch.setattr(exec_common, "_resolve_chat_provider", lambda p="", m="": ("f", "f"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    result = await StoryboardShotsTool().aexecute(
        StoryboardSplitInput(skill_name="截断技能")
    )
    assert result.success
    assert calls["n"] == 2, "截断必须重试"
    assert [g["title"] for g in svc.state_dict["shots"]] == ["镜1", "镜2"], \
        "重试结果整体替换，不得出现 1+2 拼接"
    assert not any("仍撞上限" in w for w in result.data["warnings"])
    registry.reset_registry()


# ---------- 五项制片规格覆盖注入 ----------

_SPEC_TEXT_2222 = (
    "# 最终成片规格\n"
    "- 图片分辨率：2K\n"
    "- 视频分辨率：720p\n"
    "- 分镜最大时长：12 秒\n"
)


def test_2222_spec_override_clauses_by_kind(set_global_setting):
    """6666 二轮：覆盖句来自顶部全局设置，按 kinds 精确注入；kinds 之外不串味。"""
    set_global_setting("default_image_resolution", "2K")
    set_global_setting("default_video_resolution", "720p")
    set_global_setting("max_shot_duration", 12)
    set_global_setting("default_image_provider_id", "")
    set_global_setting("default_video_provider_id", "")
    state = {"documents": []}
    shots = ex_mod._spec_override_clauses(
        state, ("duration", "video_resolution", "video_channel"))
    assert "12 秒" in shots and "720p" in shots
    assert "冲突时以本条为准" in shots
    assert "图片分辨率" not in shots  # 分镜阶段不带元素图参数
    ke = ex_mod._spec_override_clauses(state, ("image_resolution", "image_channel"))
    assert "2K" in ke
    assert "分镜最大时长" not in ke and "视频分辨率" not in ke


def test_2222_spec_override_empty_when_unset(set_global_setting):
    """全局设置未配置 → 不注入，Skill 章节默认值照常兜底。"""
    set_global_setting("default_image_resolution", "")
    set_global_setting("default_video_resolution", "")
    set_global_setting("max_shot_duration", 0)
    set_global_setting("default_image_provider_id", "")
    set_global_setting("default_video_provider_id", "")
    assert ex_mod._spec_override_clauses({"documents": []},
                                         ("duration", "image_resolution")) == ""


def test_2222_split_executors_wire_override_injection():
    """钉死：拆解执行器经统一 helper 注入规格覆盖，旧的内联时长块不复存在。"""
    src = inspect.getsource(ex_mod._run_storyboard_split)
    assert "_spec_override_clauses(svc.state_dict, _override_kinds)" in src
    assert "【时长硬约束】" not in src  # 已并入统一 helper，不得留分身


# ---------- 规格向导平台自动检测 ----------

def test_2222_spec_wizard_frozen_declaration_source():
    """0818 B4：spec_wizard 以 sidecar 冻结声明为唯一源（文本启发式退役）。"""
    from src.video_agent.skill_runtime import registry

    registry.register_skill("AI-短剧一站式生成")
    entry = registry.resolve_entry("AI-短剧一站式生成")
    assert ((entry.manifest or {}).get("flow") or {}).get("spec_wizard") is True
    assert registry.spec_wizard_active("AI-短剧一站式生成") is True


def test_2222_spec_wizard_declared_true_still_active():
    """显式声明 true 的 Skill 行为不变（0818 B4：声明家 = sidecar）。"""
    from src.video_agent.skill_runtime import registry, sidecar
    from src.video_agent.web import skill_docs as sd

    # 自包含桩：sidecar 显式 spec_wizard:true（不依赖产品 Skill，10.12-G1）
    sd.save_skill_doc(
        "显式向导测试桩",
        "# 显式向导测试桩\n> 调用规则：测试\n",
    )
    sidecar.write_sidecar("显式向导测试桩", {"flow": {"spec_wizard": True}})
    registry.register_skill("显式向导测试桩")
    assert registry.spec_wizard_active("显式向导测试桩") is True
    registry.reset_registry()


def test_2222_spec_wizard_stub_skill_inactive():
    """测试桩（正文无规格文档名）→ 不弹向导。"""
    from src.video_agent.skill_runtime import registry

    registry.register_skill("截断技能")
    assert registry.spec_wizard_active("截断技能") is False


def test_2222_spec_wizard_manifest_false_escape_hatch():
    """sidecar 显式 false = 逃生门关闭（0818 B4：声明唯一源 = sidecar，
    注册条目不再快照，原地改 manifest 失效；改用自包含桩声明）。"""
    from src.video_agent.skill_runtime import registry, sidecar
    from src.video_agent.web import skill_docs as sd

    sd.save_skill_doc(
        "false向导测试桩",
        "# false向导测试桩\n> 调用规则：测试\n",
    )
    sidecar.write_sidecar("false向导测试桩", {"flow": {"spec_wizard": False}})
    registry.register_skill("false向导测试桩")
    assert registry.spec_wizard_active("false向导测试桩") is False


def test_2222_spec_wizard_consumers_use_objective_detection():
    """G4：三个消费点统一走 spec_wizard_active，不留直读声明的分身。
    R4a 拆分后 ex_mod 为 re-export 壳，实现扫描三个子模块。"""
    from src.video_agent.core import agent_loop as al
    from src.video_agent.core import fc_tool_runner as fcr
    from src.video_agent.skill_runtime import exec_common, exec_spec, exec_tools

    al_src = inspect.getsource(al)
    fcr_src = inspect.getsource(fcr)
    ex_src = (inspect.getsource(exec_common) + inspect.getsource(exec_spec)
              + inspect.getsource(exec_tools))
    assert "spec_wizard_active(skill)" in al_src
    assert "spec_wizard_active(injected_skill)" in fcr_src
    assert "spec_wizard_active(skill_name)" in ex_src
    assert 'skill_flow_enabled(skill, "spec_wizard")' not in al_src
    assert 'skill_flow_enabled(injected_skill, "spec_wizard")' not in fcr_src


