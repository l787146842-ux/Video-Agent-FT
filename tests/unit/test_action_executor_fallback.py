# -*- coding: utf-8 -*-
"""2222（二轮）复盘修复回归 — S2 事故台账配套用例。

本文件覆盖：
① 铁律删「不得拦截/强制暂停」半句 + 存量文档自动升级（spec_rules）
② 思考档位按调用覆盖（executor_thinking_level，adapter 层）
③ 规格向导平台自动检测（registry.spec_wizard_active）
（执行器机械调用档位/截断保险/拆解边界/规格注入用例已随任务#36 B5
执行器一步退役删除：被测对象（executors._executor_thinking/_rollback_split_groups/
_run_storyboard_split/_split_kinds_for_section/_apply_actions/_spec_override_clauses
与 StoryboardShotsTool）不复存在；分组类型阶段边界与 shotRefs 完整度改由
fc_gates.structure_integrity_gate 承接。）
"""
import json

from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.config import settings
from src.video_agent.core import spec_rules


# ---------- 铁律删句（模板 + 存量自动升级） ----------

_OLD_CLAUSE = "系统不得拦截用户要求的操作，也不得强制暂停等待确认"


def test_iron_rules_template_no_block_clause_removed():
    """拦截/强制暂停半句永不回流（S2 契约）。批 A3（指令收拢批）：
    模板第 1 条整体删除——「照常执行 + 末尾警告」语义唯一表述源 =
    iron_rules_header.md【冲突与缺信息处置】。"""
    body = spec_rules._IRON_RULES_DOC_BODY
    assert _OLD_CLAUSE not in body
    assert "执行优先" not in body
    assert "先照常执行" not in body
    assert "拆解覆盖完整" in body


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
    # 全局置 high + 覨盖 None → 回落全局 high；显式 "" → 模型编辑面板批
    # （2026-09-08）：""（UI「默认（原生）」档）走 meta/兜底注入——meta 未配置
    # 且 env high → 回落 env；meta 无 + env 空 → 兜底 enable_thinking=true
    old = settings.llm_thinking_level
    object.__setattr__(settings, "llm_thinking_level", "high")
    try:
        payload2b: dict = {}
        adapter._apply_thinking_level(payload2b, None)
        assert payload2b.get("reasoning_effort") == "high"
        payload2c: dict = {}
        adapter._apply_thinking_level(payload2c, "")
        assert payload2c.get("reasoning_effort") == "high"
    finally:
        object.__setattr__(settings, "llm_thinking_level", old)
    # 覆盖值非法 → 不下发
    payload3: dict = {}
    adapter._apply_thinking_level(payload3, "xhigh")
    assert "reasoning_effort" not in payload3


def test_thinking_meta_and_fallback_injection(tmp_path, monkeypatch):
    """模型编辑面板批（2026-09-08）："" 档按 chat_models_meta 注入思考参数。

    - meta thinking_enabled=False → 不发任何字段（面板显式关）；
    - meta 开 + thinking_level → reasoning_effort=level；
    - meta 开无 level → enable_thinking=true；
    - meta 未配置 + env 空 → 兜底 enable_thinking=true（hybrid 默认关思考）。"""
    from src.video_agent.utils import provider_config_loader as pcl

    adapter = OpenAICompatChatAdapter(
        base_url="http://x", api_key="k", model="deepseek-v4-flash-0731",
        provider_id="custom-api-4")
    cfg_path = tmp_path / "api_providers.json"
    cfg_path.write_text(json.dumps([{
        "id": "custom-api-4", "name": "t", "protocol": "openai",
        "base_url": "https://tokenrhythm.studio/v1",
        "chat_models": ["deepseek-v4-flash-0731"],
        "chat_models_meta": [
            {"model": "deepseek-v4-flash-0731", "context_window": 1000000},
        ],
    }]), encoding="utf-8")
    monkeypatch.setattr(pcl, "PROVIDERS_FILE", cfg_path)

    # meta 配置存在（未显式关）→ enable_thinking=true 兜底
    payload: dict = {}
    adapter._apply_thinking_level(payload, "")
    assert payload.get("enable_thinking") is True

    # meta 显式关 → 不发任何字段
    adapter2 = OpenAICompatChatAdapter(
        base_url="http://x", api_key="k", model="m2", provider_id="custom-api-4")
    cfg2 = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg2[0]["chat_models_meta"].append(
        {"model": "m2", "thinking_enabled": False})
    cfg_path.write_text(json.dumps(cfg2), encoding="utf-8")
    payload_a: dict = {}
    adapter2._apply_thinking_level(payload_a, "")
    assert "enable_thinking" not in payload_a
    assert "reasoning_effort" not in payload_a

    # meta 开 + 档位 → reasoning_effort=档位
    adapter3 = OpenAICompatChatAdapter(
        base_url="http://x", api_key="k", model="m3", provider_id="custom-api-4")
    cfg3 = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg3[0]["chat_models_meta"].append(
        {"model": "m3", "thinking_enabled": True, "thinking_level": "medium"})
    cfg_path.write_text(json.dumps(cfg3), encoding="utf-8")
    payload_b: dict = {}
    adapter3._apply_thinking_level(payload_b, "")
    assert payload_b.get("reasoning_effort") == "medium"

    # meta 未配置该模型 + env 空 → 兜底 enable_thinking=true
    adapter4 = OpenAICompatChatAdapter(
        base_url="http://x", api_key="k", model="other", provider_id="custom-api-4")
    object.__setattr__(settings, "llm_thinking_level", "")
    payload_c: dict = {}
    adapter4._apply_thinking_level(payload_c, "")
    assert payload_c.get("enable_thinking") is True


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
# 分组类型阶段边界校验改由 fc_gates.structure_integrity_gate 承接钉死。


# ---------- 五项制片规格覆盖注入 ----------
# _SPEC_TEXT_2222 与 test_spec_override_clauses_by_kind / test_spec_override_empty_when_unset /
# test_split_executors_wire_override_injection 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._spec_override_clauses / _run_storyboard_split）不复存在；
# 制片规格改由通用主路径全文注入 Skill 后模型直调平台工具消费。


# ---------- 规格向导平台自动检测 ----------

