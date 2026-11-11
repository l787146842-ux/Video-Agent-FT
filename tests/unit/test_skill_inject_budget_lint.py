"""Skill 文档 lint 的注入预算校验（2026-11-11 裁决）。

钉死两件事：
1. 主文档超 `skill_selected_inject_max_chars` 时告警（选中会被截断）；
2. 分册指针落在注入头部窗口之外时告警（截断后指针失联 = 分册不可发现）。

旧口径是 `max_doc_chars * 0.8`，那是 30000 的 80%，与注入预算 12000 不是同一个
数量级，导致 12000–24000 字的文档一条告警都不出。
"""
import pytest

import src.video_agent.web.skill_docs as sd


def _doc(body_chars: int, refs_before: int = 0, tail_ref: bool = False) -> str:
    """构造文档：可选把分册指针放在前部 / 尾部。"""
    parts = [
        "---\nname: 预算用例\ndescription: lint 注入预算校验\n---\n",
        "# 预算用例\n\n## 一、目标\n\n",
    ]
    if refs_before:
        parts.append("分册见 `references/媒体生成.md`。\n\n")
    parts.append("填充正文。" * (body_chars // 5))
    parts.append("\n\n## 二、参考资料\n\n")
    if tail_ref:
        parts.append("- `references/提示词写作.md`\n")
    return "".join(parts)


def _warnings(content: str) -> list:
    return sd.lint_skill_content(content, "预算用例")["warnings"]


def test_within_budget_no_warning(set_global_setting):
    """预算内文档不产生注入预算告警。"""
    set_global_setting("skill_selected_inject_max_chars", 12000)
    set_global_setting("skill_selected_inject_head_chars", 6000)
    ws = _warnings(_doc(6000))
    assert not any("超过选中注入预算" in w for w in ws)


def test_over_budget_warns(set_global_setting):
    """主文档超注入预算必须告警（旧的 max_doc_chars*0.8 口径查不出来）。"""
    set_global_setting("skill_selected_inject_max_chars", 12000)
    set_global_setting("skill_selected_inject_head_chars", 6000)
    ws = _warnings(_doc(18000, refs_before=1))
    assert any("超过选中注入预算 12000" in w for w in ws), ws


def test_buried_reference_pointer_warns(set_global_setting):
    """分册指针落在注入头部窗口之外 → 告警（截断后模型看不到它）。"""
    set_global_setting("skill_selected_inject_max_chars", 12000)
    set_global_setting("skill_selected_inject_head_chars", 6000)
    # 指针只出现在末尾（第 6000 字之后），且正文超预算
    ws = _warnings(_doc(18000, refs_before=0, tail_ref=True))
    assert any("落在注入头部" in w for w in ws), ws


def test_front_reference_pointer_no_buried_warning(set_global_setting):
    """指针前置到头部窗口内 → 不产生「指针越界」告警。"""
    set_global_setting("skill_selected_inject_max_chars", 12000)
    set_global_setting("skill_selected_inject_head_chars", 6000)
    ws = _warnings(_doc(18000, refs_before=1))
    assert not any("落在注入头部" in w for w in ws), ws
