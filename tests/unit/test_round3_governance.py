"""第三轮审核 B1 回归测试（N1 渠道规则归一共源 / N3 暂停文案双句号）。

事故溯源约定：编号沿用计划书（原 docs/修复改进计划书-2026-08-15-第三轮.md，文书已清退，编号以事故台账为准）。
"""
from src.video_agent.utils.prompts import load_prompt


def test_n1_channel_rule_single_source_fc_protocol():
    """FC 协议内联共源段，旧「规格文档指明 API/模型」表述已删除。"""
    text = load_prompt("planner/protocol.md", use_cache=False)
    assert "生成渠道来源规则" in text
    assert "若规格文档" not in text
    assert "必须把指定的 provider_id 和 model 传入" not in text


def test_n1_channel_rule_single_source_fc_protocol():
    """FC 协议内联共源段（P1：禁止复述，只允许引用）；
    4-4 后 text_actions.md 已删，文本协议同源性断言退役（协议单轨）。"""
    text = load_prompt("planner/protocol.md", use_cache=False)
    assert "生成渠道来源规则" in text
    assert "必须把指定的 provider_id 和 model 传入本操作" not in text


def test_n1_channel_rule_content_aligns_b7():
    """共源段口径与 B7 裁决一致：草稿自身 > 全局设置；规格文档/Skill 不承载模型参数。"""
    text = load_prompt("planner/protocol.md", use_cache=False)
    assert "草稿自身参数" in text
    assert "全局设置" in text
    assert "规格文档与 Skill 不再承载模型能力参数" in text
