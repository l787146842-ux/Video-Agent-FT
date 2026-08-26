# -*- coding: utf-8 -*-
"""任务 #12 批次2：闸机文案覆盖矩阵钉死（prompts/gates/messages.md 覆盖全部 rule_id）。

宪法 §2.3（Policy-as-Data + 文案外置）与 GOVERNANCE §13.14(f) 门禁冻结条款
的机械守门：
1. 覆盖矩阵键集与 GATE_RULES 注册表一致（每条 rule_id 都必须登记文案口径，
   空元组 = 该闸拒因为运行时客观数据组装，无固定文案分节——也必须显式登记）；
2. 非空登记分节必须真实存在于 prompts/gates/messages.md（防指针漂移）；
3. 每条闸机条目携带 origin 入册溯源（无据者写「历史存量-待裁决」）。
"""
import re
from pathlib import Path

from src.video_agent.core.gate_registry import (
    GATE_MESSAGE_SECTIONS,
    GATE_RULES,
)

ROOT = Path(__file__).resolve().parents[2]
MESSAGES_MD = ROOT / "prompts" / "gates" / "messages.md"

_SECTION_RE = re.compile(r"^## ([A-Z0-9_]+)\s*$", re.M)


def _messages_sections():
    return set(_SECTION_RE.findall(MESSAGES_MD.read_text(encoding="utf-8")))


def test_coverage_matrix_keys_match_registry():
    """每条 rule_id 都在覆盖矩阵登记，且矩阵不得登记注册表外的 rule_id。"""
    assert set(GATE_MESSAGE_SECTIONS) == set(GATE_RULES)


def test_declared_message_sections_exist_in_messages_md():
    """非空登记分节必须存在于 messages.md（文案单一事实源防漂移）。"""
    available = _messages_sections()
    declared = {s for secs in GATE_MESSAGE_SECTIONS.values() for s in secs}
    missing = declared - available
    assert not missing, f"messages.md 缺少登记分节: {sorted(missing)}"


def test_flow_gates_with_user_visible_copy_are_covered():
    """带固定用户可见文案的流程闸/确认闸必须声明至少一个外置分节
    （防固定文案绕过外置单一事实源回流代码）。"""
    must_have_copy = {
        "platform.gen_confirm",
        "skill.flow.spec_gate",
        "skill.flow.element_image",
        "skill.flow.storyboard_pending",
        "skill.gen_asset_binding",
        "skill.script_required",
    }
    for rule_id in must_have_copy:
        assert GATE_MESSAGE_SECTIONS[rule_id], f"{rule_id} 缺外置文案分节登记"


def test_every_rule_has_origin_metadata():
    """门禁溯源（任务 #12 批次2）：每条闸机条目必须携带非空 origin；
    无依据者显式写「历史存量-待裁决」，不得留白。"""
    for rule_id, meta in GATE_RULES.items():
        assert meta.origin.strip(), f"{rule_id} 缺 origin 入册溯源"
