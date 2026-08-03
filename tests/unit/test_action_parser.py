"""
action_parser 模块单元测试 — 验证 JSON 容错解析与 action 提取逻辑。
"""
import pytest

from src.video_agent.web.action_parser import (
    strip_action_blocks,
    has_action_block,
    parse_actions_from_reply,
    parse_json_tolerant,
    repair_json,
    normalize_actions,
)


class TestStripActionBlocks:
    def test_removes_markdown_block(self):
        text = '你好\n```studio-actions\n[{"action":"add_group"}]\n```\n再见'
        assert strip_action_blocks(text) == "你好\n\n再见"

    def test_removes_xml_block(self):
        text = '前文<studio-actions>[{"action":"x"}]</studio-actions>后文'
        assert strip_action_blocks(text) == "前文后文"

    def test_no_block_unchanged(self):
        text = "普通回复文本"
        assert strip_action_blocks(text) == text

    def test_case_insensitive(self):
        text = '```StudioActions\n[]\n```done'
        assert strip_action_blocks(text) == "done"


class TestHasActionBlock:
    def test_detects_markdown(self):
        assert has_action_block('```studio-actions\n[]\n```') is True

    def test_detects_xml(self):
        assert has_action_block('<studio-actions>[]</studio-actions>') is True

    def test_no_block(self):
        assert has_action_block('普通文本') is False


class TestParseJsonTolerant:
    def test_valid_json(self):
        assert parse_json_tolerant('[{"action":"add_group"}]') == [{"action": "add_group"}]

    def test_trailing_comma(self):
        result = parse_json_tolerant('[{"action":"x"},]')
        assert result == [{"action": "x"}]

    def test_single_quotes(self):
        result = parse_json_tolerant("[{'action':'x'}]")
        assert result == [{"action": "x"}]

    def test_truncated_json(self):
        # 模拟 LLM 被 max_tokens 截断：数组括号未闭合
        raw = '[{"action":"update_draft","draft_id":"d1"}'
        result = parse_json_tolerant(raw)
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["action"] == "update_draft"

    def test_truncated_beyond_repair(self):
        # 字符串值内部截断——无法修复，返回 None 是可接受的
        raw = '[{"action":"update_draft","patch":{"prompt":"一段很长的文本'
        result = parse_json_tolerant(raw)
        # 不强制要求解析成功，但不能抛异常
        assert result is None or isinstance(result, list)

    def test_completely_invalid(self):
        assert parse_json_tolerant("这不是 JSON") is None


class TestRepairJson:
    def test_trailing_comma_object(self):
        assert repair_json('{"a":1,}') == '{"a":1}'

    def test_trailing_comma_array(self):
        assert repair_json('[1,2,]') == '[1,2]'

    def test_unclosed_braces(self):
        repaired = repair_json('{"action":"x"')
        assert repaired.count("{") == repaired.count("}")

    def test_single_quotes_only(self):
        assert '"' in repair_json("{'key':'val'}")


class TestNormalizeActions:
    def test_list_passthrough(self):
        actions = [{"action": "a"}, {"action": "b"}]
        assert normalize_actions(actions) == actions

    def test_dict_with_actions_key(self):
        parsed = {"actions": [{"action": "x"}]}
        assert normalize_actions(parsed) == [{"action": "x"}]

    def test_single_action_dict(self):
        parsed = {"action": "update_draft", "patch": {}}
        assert normalize_actions(parsed) == [parsed]

    def test_invalid_returns_empty(self):
        assert normalize_actions("string") == []
        assert normalize_actions(42) == []
        assert normalize_actions(None) == []


class TestParseActionsFromReply:
    def test_extracts_from_markdown_block(self):
        reply = '好的\n```studio-actions\n[{"action":"add_group","title":"测试"}]\n```\n完成'
        actions = parse_actions_from_reply(reply)
        assert len(actions) == 1
        assert actions[0]["action"] == "add_group"

    def test_extracts_from_xml_block(self):
        reply = '<studio-actions>[{"action":"delete_draft","draft_id":"d1"}]</studio-actions>'
        actions = parse_actions_from_reply(reply)
        assert len(actions) == 1
        assert actions[0]["draft_id"] == "d1"

    def test_multiple_blocks(self):
        reply = '```studio-actions\n[{"action":"a"}]\n```\n中间\n```studio-actions\n[{"action":"b"}]\n```'
        actions = parse_actions_from_reply(reply)
        assert len(actions) == 2

    def test_tolerant_of_trailing_comma(self):
        reply = '```studio-actions\n[{"action":"x","tag":"标签",}]\n```'
        actions = parse_actions_from_reply(reply)
        assert len(actions) == 1
        assert actions[0]["tag"] == "标签"

    def test_empty_reply(self):
        assert parse_actions_from_reply("") == []
        assert parse_actions_from_reply("没有操作块") == []
