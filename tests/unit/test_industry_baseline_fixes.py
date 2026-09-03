"""6666 二轮事故 / 业界基准回归：铁律三条款、卡片面纪律、暂停语义归位。
（C1 语言单一事实源、C2 拒因回喂、C5 级联快模型、条款编号同步用例
已随任务#36 B5 执行器一步退役删除：被测对象 executors._prompt_language_rule /
_write_prompt_batch / _resolve_cascade_fast 与 exec_split._selfcheck_key_elements
不复存在。语言闸/拒因回喂改由 fc_tool_runner 提示词闸消费（prompt_gates 既有单测钉死）。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core import spec_rules
from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """每个测试独立 Skill 目录 + 清空运行时注册表。"""
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


# ---------- C1：语言单一事实源 ----------
# test_language_rule_default_chinese_and_no_section_exception / test_language_rule_english_locked_skill
# 已随任务#36 B5 执行器一步退役删除：被测对象（executors._prompt_language_rule /
# _skill_system_prompt）不复存在。语言闸由 prompt_gates 消费，其既有单测承接钉死。


# ---------- C2 + 卡片面纪律：纠正重试带结构化拒因 ----------
# test_corrective_retry_carries_rejection_reasons_and_card_discipline /
# test_normal_batch_has_no_reason_block 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._write_prompt_batch）不复存在；拒因回喂改由 fc_tool_runner
# 提示词闸拒因文案承接。


# ---------- C5：级联快模型 ----------
# test_cascade_fast_resolution_and_fallback 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._resolve_cascade_fast）不复存在。


# ---------- 铁律三条款 ----------

def test_iron_rules_default_body_three_clauses():
    body = spec_rules._IRON_RULES_DOC_BODY
    assert "1. 执行优先" in body
    assert "2. 拆解覆盖完整（系统机器验收）" in body
    assert "3. 回复纪律见平台协议" in body
    # 旧条款已删（功能由闸门/系统行为兜底）
    assert "流程覆盖" not in body
    assert "分镜提示词必须包含" not in body
    assert "本文档可在左侧" not in body


def test_ensure_iron_rules_doc_creates_three_clause_doc(tmp_path):
    svc = StateManager(str(tmp_path / "ws"))
    changed = spec_rules.ensure_iron_rules_doc(svc.state_dict)
    assert changed
    doc = spec_rules.find_iron_rules_doc(svc.state_dict)
    assert doc is not None
    assert "3. 回复纪律见平台协议" in doc["content"]
    assert "流程覆盖" not in doc["content"]


# test_clause_number_references_synced 已随任务#36 B5 执行器一步退役删除：
# 断言主体（exec_split._selfcheck_key_elements 源码引用铁律第 2 条）不复存在；
# 铁律第 2 条正文由上方 test_iron_rules_default_body_three_clauses 钉死。


# ---------- 暂停语义归位（6666 四轮）：Skill 唯一暂停源 ----------

def test_skill_reminder_has_no_pause_pressure():
    """平台不再两侧施压：反暂停/正暂停 prose 均删。
    （S10 stage_done_fallback 已随用户裁决 2026-09-02 退役删除，
    兜底注释断言不再适用）"""
    import inspect
    from src.video_agent.core import planner as planner_mod

    src = inspect.getsource(planner_mod)
    for phrase in ("仅作参考", "不要为此强制暂停", "反复请求确认", "【阶段确认】当前 Skill 要求"):
        assert phrase not in src


def test_protocol_no_anti_pause_sentence():
    """协议模板反暂停句已删；暂停通道协议（怎么暂停）保留。
    P2e 单轨收敛：断言对象从已退役的 system.md 迁到唯一协议 protocol.md。"""
    from src.video_agent.utils.paths import PROJECT_ROOT

    txt = (PROJECT_ROOT / "prompts" / "planner" / "protocol.md").read_text(encoding="utf-8")
    assert "不要在每个阶段完成后都暂停" not in txt
    assert "用户已给出明确指令时不要使用" not in txt
    # 新基线（P2e 后）：暂停通道协议在 FC 协议中表述为
    # 「暂停请求用户确认：调用 workflow_pause Tool」
    assert "调用 workflow_pause Tool" in txt


def test_pause_label_protocol_scoped_to_confirmation():
    """workflow_pause label 协议（v3）：必须如实描述用户确认后立即执行的下一步动作。"""
    from src.video_agent.tools.document_tools import WorkflowPauseInput

    desc = WorkflowPauseInput.model_fields["options"].description
    assert "立即执行的下一步动作" in desc
    assert "不得携带下一阶段启动措辞" not in desc


def test_iron_rules_clause2_single_sentence():
    """铁律第 2 条只留标题句，粒度裁量归模型 + Skill。"""
    body = spec_rules._IRON_RULES_DOC_BODY
    assert "2. 拆解覆盖完整（系统机器验收）。\n" in body
    assert "严禁把多位配角" not in body
    assert "宁缺毋滥" not in body
