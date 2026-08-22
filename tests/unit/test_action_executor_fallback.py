# -*- coding: utf-8 -*-
"""2222（二轮）复盘修复回归 — S2 事故台账配套用例。

本文件覆盖：
① 铁律删「不得拦截/强制暂停」半句 + 存量文档自动升级（spec_rules）
② 思考档位按调用覆盖（executor_thinking_level，adapter 层）
③ 规格向导平台自动检测（registry.spec_wizard_active）
（执行器机械调用档位/截断保险/拆解边界/规格注入用例已随任务#36 B5
执行器一步退役删除：被测对象（executors._executor_thinking/_rollback_split_groups/
_run_storyboard_split/_split_kinds_for_section/_apply_actions/_spec_override_clauses
与 StoryboardShotsTool）不复存在；分组类型阶段边界与 sceneRefs 完整度改由
fc_tool_runner _structure_integrity_gate 承接。）
"""
from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.config import settings
from src.video_agent.core import spec_rules


# ---------- 铁律删句（模板 + 存量自动升级） ----------

_OLD_CLAUSE = "系统不得拦截用户要求的操作，也不得强制暂停等待确认"


def test_iron_rules_template_no_block_clause_removed():
    """模板第 1 条只保留『照常执行 + 末尾警告』，拦截/强制暂停半句已删。"""
    body = spec_rules._IRON_RULES_DOC_BODY
    assert _OLD_CLAUSE not in body
    assert "1. 执行优先" in body
    assert "先照常执行" in body and "再在回复末尾给出警告。" in body


def test_existing_iron_doc_auto_upgraded_on_ensure():
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


def test_existing_iron_doc_upgrade_idempotent():
    """升级幂等：已升级的文档再次 ensure 不报变化。"""
    state = {"documents": [{"name": "执行铁律.md",
                            "content": spec_rules._IRON_RULES_DOC_BODY.strip() + "\n"}]}
    assert spec_rules.ensure_iron_rules_doc(state) is False


def test_migrated_spec_section_strips_block_clause():
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

def test_thinking_override_wins_over_global():
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


# test_executor_thinking_default_low_and_empty_falls_back /
# test_all_executor_llm_calls_pass_thinking_level 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._executor_thinking 与六个 exec_* 模块源码扫描）不复存在。
# executor 档位策略表保留在 model_policy（test_model_policy 钉死，前端设置页契约）。


# ---------- 截断保险全局化（流式拆解回滚 + 扩额整体重试） ----------
# test_rollback_split_groups_removes_only_new / test_split_truncation_retry_pinned /
# test_split_truncation_retry_success_path 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._rollback_split_groups / _run_storyboard_split /
# StoryboardShotsTool）不复存在。


# ---------- 拆解边界按 Skill 章节结构自适应 ----------
# test_ai_skill_split_sections_scope_kinds / test_separate_sections_keep_single_kind_boundary /
# test_apply_actions_multi_kind_accepts_and_single_rejects 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._split_kinds_for_section / _apply_actions）不复存在；
# 分组类型阶段边界校验改由 fc_tool_runner _structure_integrity_gate 承接钉死。


# ---------- 五项制片规格覆盖注入 ----------
# _SPEC_TEXT_2222 与 test_spec_override_clauses_by_kind / test_spec_override_empty_when_unset /
# test_split_executors_wire_override_injection 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._spec_override_clauses / _run_storyboard_split）不复存在；
# 制片规格改由通用主路径全文注入 Skill 后模型直调平台工具消费。


# ---------- 规格向导平台自动检测 ----------

def test_spec_wizard_frozen_declaration_source():
    """0818 B4：spec_wizard 以 frontmatter 冻结声明为唯一源（文本启发式退役）。"""
    from src.video_agent.skill_runtime import registry

    registry.register_skill("AI-短剧一站式生成")
    entry = registry.resolve_entry("AI-短剧一站式生成")
    assert ((entry.manifest or {}).get("flow") or {}).get("spec_wizard") is True
    assert registry.spec_wizard_active("AI-短剧一站式生成") is True


def test_spec_wizard_declared_true_still_active():
    """显式声明 true 的 Skill 行为不变（0818 B4：声明家 = frontmatter）。"""
    from src.video_agent.skill_runtime import frontmatter, registry
    from src.video_agent.web import skill_docs as sd

    # 自包含桩：frontmatter 显式 spec_wizard:true（不依赖产品 Skill，10.12-G1）
    sd.save_skill_doc(
        "显式向导测试桩",
        "# 显式向导测试桩\n> 调用规则：测试\n",
    )
    frontmatter.write_manifest("显式向导测试桩", {"flow": {"spec_wizard": True}})
    registry.register_skill("显式向导测试桩")
    assert registry.spec_wizard_active("显式向导测试桩") is True
    registry.reset_registry()


def test_spec_wizard_stub_skill_inactive():
    """测试桩（正文无规格文档名）→ 不弹向导。"""
    from src.video_agent.skill_runtime import registry
    from src.video_agent.web import skill_docs as sd

    # 自包含桩（不依赖已退役用例留下的 Skill 文档）：无 frontmatter flow 声明
    sd.save_skill_doc("向导隐性测试桩", "# 向导隐性测试桩\n> 调用规则：测试\n")
    registry.register_skill("向导隐性测试桩")
    assert registry.spec_wizard_active("向导隐性测试桩") is False
    registry.reset_registry()


def test_spec_wizard_manifest_false_escape_hatch():
    """frontmatter 显式 false = 逃生门关闭（0818 B4：声明唯一源 = frontmatter，
    注册条目不再快照，原地改 manifest 失效；改用自包含桩声明）。"""
    from src.video_agent.skill_runtime import frontmatter, registry
    from src.video_agent.web import skill_docs as sd

    sd.save_skill_doc(
        "false向导测试桩",
        "# false向导测试桩\n> 调用规则：测试\n",
    )
    frontmatter.write_manifest("false向导测试桩", {"flow": {"spec_wizard": False}})
    registry.register_skill("false向导测试桩")
    assert registry.spec_wizard_active("false向导测试桩") is False


def test_spec_wizard_consumers_use_objective_detection():
    """G4：消费点统一走 spec_wizard_active，不留直读声明的分身。
    Rule2 v6：FC 轨选项面归一迁 pause_composer 单一实现；
    执行器消费点已随任务#36 B5 执行器一步退役删除。"""
    import inspect

    from src.video_agent.core import fc_tool_runner as fcr
    from src.video_agent.core import pause_composer

    fcr_src = inspect.getsource(fcr)
    assert "normalize_option_surface" in fcr_src
    assert "spec_wizard_active" in inspect.getsource(pause_composer)
    assert 'skill_flow_enabled(injected_skill, "spec_wizard")' not in fcr_src


