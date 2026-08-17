"""6666 二轮事故 / 业界基准回归：语言单一事实源（C1）、拒因回喂（C2）、
轮内 compaction（C3）、级联快模型（C5）、铁律三条款、卡片面纪律。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core import agent_loop
from src.video_agent.core import spec_rules
from src.video_agent.skill_runtime import executors as ex_mod
from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager
from src.video_agent.skill_runtime import exec_common


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """每个测试独立 Skill 目录 + 清空运行时注册表。"""
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


# ---------- C1：语言单一事实源 ----------

def test_language_rule_default_chinese_and_no_section_exception():
    """默认（语言闸生效）注入句为中文事实陈述，且旧的「章节从其要求」例外消失。"""
    sd.save_skill_doc(
        "demo",
        "# 演示\n> 调用规则：测试\n"
        "<write_the_prompt>\nA character turnaround sheet of X.\n</write_the_prompt>\n",
    )
    rule = ex_mod._prompt_language_rule("demo")
    assert "中文" in rule and "平台语言闸生效" in rule
    assert "从其要求" not in rule
    sysp = ex_mod._skill_system_prompt("write_media_prompt", "demo")
    assert "平台语言闸生效" in sysp
    assert "从其要求" not in sysp


def test_language_rule_english_locked_skill():
    """manifest 声明 cjk_min_ratio=0（英文锁定）→ 注入句为英文事实陈述。"""
    sd.save_skill_doc(
        "en",
        "# 英文锁定\n> 调用规则：测试\n"
        "```json skill_manifest\n{\"gates\": {\"cjk_min_ratio\": 0}}\n```\n"
        "<write_the_prompt>\ntemplate\n</write_the_prompt>\n",
    )
    rule = ex_mod._prompt_language_rule("en")
    assert "英文" in rule and "英文锁定" in rule


# ---------- C2 + 卡片面纪律：纠正重试带结构化拒因 ----------

async def test_corrective_retry_carries_rejection_reasons_and_card_discipline(tmp_path, monkeypatch):
    captured = {}

    async def fake_stream(tool_name, skill_name, system, user, svc, skill_content,
                          provider="", model="", max_tokens=8192, flush_n=2):
        captured["system"] = system
        return 0, [], "[]", "stop"

    monkeypatch.setattr(exec_common, "_stream_actions_progressive", fake_stream)
    svc = StateManager(str(tmp_path / "ws"))
    batch = [("keyElements", {"id": "ke-1", "title": "程心", "drafts": []})]
    await ex_mod._write_prompt_batch(
        "write_media_prompt", "demo", "", svc,
        "p", "m", batch, "", "",
        corrective=True, corrective_reasons=["提示词正文几乎全是英文：请改为中文正文"],
    )
    sysp = captured["system"]
    assert "【拒因回喂】" in sysp
    assert "提示词正文几乎全是英文" in sysp
    # 卡片面纪律：label 限长 + 增量信息（防介绍==提示词）
    assert "≤12 字短语" in sysp
    assert "逐字誊写分组描述不符合要求" in sysp


async def test_normal_batch_has_no_reason_block(tmp_path, monkeypatch):
    captured = {}

    async def fake_stream(tool_name, skill_name, system, user, svc, skill_content,
                          provider="", model="", max_tokens=8192, flush_n=2):
        captured["system"] = system
        return 0, [], "[]", "stop"

    monkeypatch.setattr(exec_common, "_stream_actions_progressive", fake_stream)
    svc = StateManager(str(tmp_path / "ws"))
    batch = [("keyElements", {"id": "ke-1", "title": "程心", "drafts": []})]
    await ex_mod._write_prompt_batch(
        "write_media_prompt", "demo", "", svc, "p", "m", batch, "", "",
    )
    assert "【拒因回喂】" not in captured["system"]
    assert "【卡片面纪律】" in captured["system"]


# ---------- C5：级联快模型 ----------

def test_cascade_fast_resolution_and_fallback(tmp_path, monkeypatch):
    from src.video_agent.config import settings

    monkeypatch.setattr(
        "src.video_agent.web.provider_config.load_merged_providers",
        lambda: [{"id": "fast", "enabled": True, "chat_models": ["flash-lite"]}],
    )
    # 空配置 → 不级联
    assert ex_mod._resolve_cascade_fast("main", "reasoner") == ("main", "reasoner")
    # 配置 provider → 取其默认聊天模型
    object.__setattr__(settings, "executor_fast_model", "fast")
    try:
        assert ex_mod._resolve_cascade_fast("main", "reasoner") == ("fast", "flash-lite")
        # 配置 provider:model 精确指定
        object.__setattr__(settings, "executor_fast_model", "fast:flash-lite")
        assert ex_mod._resolve_cascade_fast("main", "reasoner") == ("fast", "flash-lite")
        # 解析不到 → 回落主模型
        object.__setattr__(settings, "executor_fast_model", "ghost")
        assert ex_mod._resolve_cascade_fast("main", "reasoner") == ("main", "reasoner")
    finally:
        object.__setattr__(settings, "executor_fast_model", "")


# ---------- 铁律三条款 ----------

def test_iron_rules_default_body_three_clauses():
    body = spec_rules._IRON_RULES_DOC_BODY
    assert "1. 执行优先" in body
    assert "2. 拆解覆盖完整（自检核对）" in body
    assert "3. 回复精简" in body
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
    assert "3. 回复精简" in doc["content"]
    assert "流程覆盖" not in doc["content"]


def test_clause_number_references_synced():
    """拆解覆盖现为第 2 条：验收补漏话术引用铁律第 2 条（0817 表述源在 exec_split）。"""
    import inspect
    from src.video_agent.skill_runtime import exec_split
    src = inspect.getsource(exec_split._selfcheck_key_elements)
    assert "第 2 条" in src


# ---------- 暂停语义归位（6666 四轮）：Skill 唯一暂停源 ----------

def test_skill_reminder_has_no_pause_pressure():
    """平台不再两侧施压：反暂停/正暂停 prose 均删，层 9 确定性兜底保留。"""
    import inspect
    from src.video_agent.core import planner as planner_mod

    src = inspect.getsource(planner_mod)
    for phrase in ("仅作参考", "不要为此强制暂停", "反复请求确认", "【阶段确认】当前 Skill 要求"):
        assert phrase not in src
    # 漏暂停的客观兜底（确定性，非 prose 催促）保留
    assert "阶段完成引导兜底" in src


def test_system_md_no_anti_pause_sentence():
    """system.md 反暂停句已删；暂停通道协议（怎么暂停）保留。"""
    from src.video_agent.utils.paths import PROJECT_ROOT

    txt = (PROJECT_ROOT / "prompts" / "planner" / "system.md").read_text(encoding="utf-8")
    assert "不要在每个阶段完成后都暂停" not in txt
    assert "用户已给出明确指令时不要使用" not in txt
    # 新基线（双协议瘦身后）：暂停通道协议表述改为
    # 「只能通过 request_confirmation 动作发起，只在正文写『请确认』无效」
    assert "只能通过 request_confirmation 动作发起" in txt
    assert "无效" in txt


def test_pause_label_protocol_scoped_to_confirmation():
    """workflow_pause label 协议（v3）：必须如实描述用户确认后立即执行的下一步动作。"""
    from src.video_agent.tools.document_tools import WorkflowPauseInput

    desc = WorkflowPauseInput.model_fields["options"].description
    assert "立即执行的下一步动作" in desc
    assert "不得携带下一阶段启动措辞" not in desc


def test_iron_rules_clause2_single_sentence():
    """铁律第 2 条只留标题句，粒度裁量归模型 + Skill。"""
    body = spec_rules._IRON_RULES_DOC_BODY
    assert "2. 拆解覆盖完整（自检核对）。\n" in body
    assert "严禁把多位配角" not in body
    assert "宁缺毋滥" not in body
