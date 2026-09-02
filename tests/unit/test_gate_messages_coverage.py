# -*- coding: utf-8 -*-
"""任务 #12 批次2：闸机文案覆盖矩阵钉死（prompts/gates/messages.md 覆盖全部 rule_id）。

宪法 §2.3（Policy-as-Data + 文案外置）的机械守门：
1. 覆盖矩阵键集与 GATE_RULES 注册表一致（每条 rule_id 都必须登记文案口径，
   空元组 = 该闸拒因为运行时客观数据组装，无固定文案分节——也必须显式登记）；
2. 非空登记分节必须真实存在于 prompts/gates/messages.md（防指针漂移）；
3. 每条闸机条目携带 origin 入册溯源（无据者写「历史存量-待裁决」）。

任务 #13（孤儿分节消除）追加口径：
4. messages.md 每个 ## KEY 分节都必须被 GATE_MESSAGE_SECTIONS 或
   PAUSE_MESSAGE_SECTIONS 登记，且登记分节都存在于 messages.md（双向：
   无孤儿、无悬空指针）；
5. PAUSE_MESSAGE_SECTIONS 每个逻辑键都被消费方 gates_cards.py 引用
   （登记即有代码消费者，杠杀「外置但无人管」孤儿存活空间）。
"""
import re
from pathlib import Path

from src.video_agent.core.gate_registry import (
    GATE_MESSAGE_SECTIONS,
    GATE_RULES,
    PAUSE_MESSAGE_SECTIONS,
)

ROOT = Path(__file__).resolve().parents[2]
MESSAGES_MD = ROOT / "prompts" / "gates" / "messages.md"
GATES_CARDS_PY = ROOT / "src" / "video_agent" / "core" / "gates_cards.py"

_SECTION_RE = re.compile(r"^## ([A-Z0-9_]+)\s*$", re.M)
_PAUSE_REF_RE = re.compile(r"PAUSE_MESSAGE_SECTIONS\[\s*[\"']([^\"']+)[\"']\s*\]")


def _messages_sections():
    return set(_SECTION_RE.findall(MESSAGES_MD.read_text(encoding="utf-8")))


def _all_registered_sections():
    """两张覆盖矩阵登记的全部分节键（闸机文案 + 暂停/告警文案）。"""
    gate_secs = {s for secs in GATE_MESSAGE_SECTIONS.values() for s in secs}
    return gate_secs | set(PAUSE_MESSAGE_SECTIONS.values())


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
    }
    for rule_id in must_have_copy:
        assert GATE_MESSAGE_SECTIONS[rule_id], f"{rule_id} 缺外置文案分节登记"


def test_every_rule_has_origin_metadata():
    """门禁溯源（任务 #12 批次2）：每条闸机条目必须携带非空 origin；
    无依据者显式写「历史存量-待裁决」，不得留白。"""
    for rule_id, meta in GATE_RULES.items():
        assert meta.origin.strip(), f"{rule_id} 缺 origin 入册溯源"


def test_no_orphan_sections_in_messages_md():
    """任务 #13：messages.md 每个 ## KEY 分节都被覆盖矩阵登记（无孤儿），
    且登记分节都存在于 messages.md（无悬空指针）。任一方向漂移即红。"""
    available = _messages_sections()
    registered = _all_registered_sections()
    orphans = available - registered
    dangling = registered - available
    assert not orphans, (
        f"messages.md 存在未登记孤儿分节（改名/删除无门禁发现）: {sorted(orphans)}")
    assert not dangling, (
        f"覆盖矩阵登记了 messages.md 不存在的分节: {sorted(dangling)}")


def test_pause_sections_have_code_consumer():
    """任务 #13：PAUSE_MESSAGE_SECTIONS 每个逻辑键都被消费方 gates_cards.py
    引用（登记即有代码消费者，杠杀孤儿存活空间）。"""
    src = GATES_CARDS_PY.read_text(encoding="utf-8")
    referenced = set(_PAUSE_REF_RE.findall(src))
    unconsumed = set(PAUSE_MESSAGE_SECTIONS) - referenced
    assert not unconsumed, (
        f"PAUSE_MESSAGE_SECTIONS 逻辑键无 gates_cards.py 消费引用: {sorted(unconsumed)}")
    unknown = referenced - set(PAUSE_MESSAGE_SECTIONS)
    assert not unknown, (
        f"gates_cards.py 引用了未登记的 PAUSE_MESSAGE_SECTIONS 逻辑键: {sorted(unknown)}")
