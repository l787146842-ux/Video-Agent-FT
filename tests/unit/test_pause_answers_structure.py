# -*- coding: utf-8 -*-
"""暂停回应问题级结构化回携契约单测（2026-09-21 批J，用户要求）。

**背景**：用户「F-②c dsh 式 answers[] 成型回携，要做。」

批F 给暂停卡补了 `questions[]`（一次可问 N 个问题），但**回答侧仍是扁平的**：
前端把各问所选**逐行拼接**成一个 `value` 字符串送出，后端只能靠"第几行 = 第几问"
的位置约定反推 —— 问题问句里含换行、或某问用自定义文本作答时，这个约定就会错位。

dsh 参照（`dsh-user-questions` types.d.ts:46-53 的 `AskUserQuestionAnswerItem`）：
每个回答自带 `id`（与问题 id 对应）、`selected`（选中标签数组）、
`custom`（自由文本，不用时省略）。

本批契约：`pause_response.answers = [{id, selected[], custom?}]`。
- **`value` 扁平字段保持原样**（旧消费链零改动：对勾匹配 `turn-groups`
  按值相等、`is_flow_continue_value` 行格式判定都读它）；
- `answers` 是**新增的结构化面**，后端归一后落盘 `pauseAnsweredAnswers`。

钉死：① 归一清洗（丢非法项不留脏数据）；② 非空才透传/落盘（旧消息零变化）；
③ 向后兼容（无 answers 时标记形态逐字不变）；④ 纯函数不抛异常。
"""
import pytest

from src.video_agent.web.chat_consume import normalize_pause_answers


# ---------- ① 归一清洗 ----------

def test_normalizes_well_formed_answers():
    """正常形态原样归一：id + selected 数组（+ 可选 custom）。"""
    out = normalize_pause_answers([
        {"id": "ratio", "selected": ["16:9"]},
        {"id": "naming", "selected": ["不显名"], "custom": ""},
    ])
    assert out == [
        {"id": "ratio", "selected": ["16:9"]},
        {"id": "naming", "selected": ["不显名"]},
    ]


def test_custom_only_answer_is_kept():
    """纯自定义作答（selected 空 + custom 非空）必须保留（对齐 dsh 的 custom 槽）。"""
    out = normalize_pause_answers([
        {"id": "q1", "selected": [], "custom": "我自己写一个"},
    ])
    assert out == [{"id": "q1", "selected": [], "custom": "我自己写一个"}]


def test_empty_custom_field_is_omitted():
    """custom 为空串 → 字段省略（对齐 dsh：不用 custom 时该字段不出现）。"""
    out = normalize_pause_answers([{"id": "q1", "selected": ["A"], "custom": "   "}])
    assert out == [{"id": "q1", "selected": ["A"]}]
    assert "custom" not in out[0]


def test_drops_items_without_id():
    """无 id 的项丢弃——留着无法与问题对应，只会污染账本。"""
    out = normalize_pause_answers([
        {"id": "", "selected": ["A"]},
        {"selected": ["B"]},
        {"id": "q2", "selected": ["C"]},
    ])
    assert out == [{"id": "q2", "selected": ["C"]}]


def test_drops_items_with_no_content():
    """既无 selected 又无 custom 的空回答丢弃（无信息量）。"""
    out = normalize_pause_answers([
        {"id": "q1", "selected": []},
        {"id": "q2", "selected": [], "custom": ""},
        {"id": "q3", "selected": ["有用"]},
    ])
    assert out == [{"id": "q3", "selected": ["有用"]}]


def test_drops_non_dict_items_and_blank_selected_entries():
    """非 dict 项丢弃；selected 内的空串/None 条目滤掉。"""
    out = normalize_pause_answers([
        "not-a-dict",
        None,
        {"id": "q1", "selected": ["A", "", None, "  ", "B"]},
    ])
    assert out == [{"id": "q1", "selected": ["A", "B"]}]


def test_selected_not_a_list_treated_as_empty():
    """selected 非列表（畸形输入）→ 视为空；若同时无 custom 则整项丢弃。"""
    assert normalize_pause_answers([{"id": "q1", "selected": "A"}]) == []
    assert normalize_pause_answers(
        [{"id": "q1", "selected": "A", "custom": "文本"}]) == [
        {"id": "q1", "selected": [], "custom": "文本"}]


# ---------- ② 纯函数健壮性（绝不抛异常击穿回携链） ----------

@pytest.mark.parametrize("bad", [None, "", "str", 123, {}, [1, 2], [None]])
def test_never_raises_on_malformed_input(bad):
    """任何畸形输入一律回落空列表，绝不抛异常（回携链不能被炸断）。"""
    assert normalize_pause_answers(bad) == []


# ---------- ③ 端到端：消费函数透传 answers，且旧形态逐字不变 ----------

class _Svc:
    """最小 StateManager 桩：只提供 consume_pause_response 需要读写的面。"""

    def __init__(self, pause_id: str = "p1"):
        self.state_dict = {
            "interaction": {"active_pause": {"pause_id": pause_id}},
            "turn_seq": 7,
            "usedSkills": [],
            "workflow_run": {},
        }

    def save_debounced(self):
        pass

    def save(self):
        pass


def _consume(pause_response):
    from src.video_agent.web.chat_consume import consume_pause_response

    return consume_pause_response(_Svc(), pause_response)


def test_consume_passes_answers_through():
    """与 active_pause 匹配时，归一后的 answers 随标记返回（批J）。"""
    res = _consume({
        "pause_id": "p1", "value": "16:9\n不显名",
        "answers": [
            {"id": "ratio", "selected": ["16:9"]},
            {"id": "naming", "selected": ["不显名"]},
        ],
    })
    assert res is not None
    assert res["answers"] == [
        {"id": "ratio", "selected": ["16:9"]},
        {"id": "naming", "selected": ["不显名"]},
    ]
    # 扁平 value 保持原样（旧消费链零改动）
    assert res["value"] == "16:9\n不显名"


def test_consume_omits_answers_key_when_absent():
    """无 answers 的旧形态 → 标记里**不出现** answers 键（旧消息零变化）。"""
    res = _consume({"pause_id": "p1", "value": "确认"})
    assert res is not None
    assert "answers" not in res, "旧形态混入了 answers 键（会改变落盘形态）"
    assert res["value"] == "确认"


def test_consume_omits_answers_when_all_items_invalid():
    """answers 全为非法项 → 归一为空 → 同样不落键（不留空数组脏数据）。"""
    res = _consume({"pause_id": "p1", "value": "确认", "answers": [{"selected": ["x"]}]})
    assert res is not None
    assert "answers" not in res


# ---------- ④ 落盘：非空才写 pauseAnsweredAnswers ----------

def test_persist_writes_answers_only_when_present():
    """落盘层：answers 非空才写 `pauseAnsweredAnswers`（防类型退化）。"""
    from src.video_agent.state.conversation_ops import build_chat_entry

    base = dict(sender="user", text="16:9", pause_answered={
        "pause_id": "p1", "value": "16:9", "label": "", "decision": "accept"})
    old = build_chat_entry(**base)
    assert "pauseAnsweredAnswers" not in old, "旧形态不应产生新键"

    new = build_chat_entry(**{**base, "pause_answered": {
        "pause_id": "p1", "value": "16:9", "decision": "accept",
        "answers": [{"id": "ratio", "selected": ["16:9"]}],
    }})
    assert new["pauseAnsweredAnswers"] == [{"id": "ratio", "selected": ["16:9"]}]
    # 扁平字段照旧
    assert new["pauseAnsweredId"] == "p1"
    assert new["pauseAnsweredValue"] == "16:9"
