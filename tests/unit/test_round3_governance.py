"""第三轮审核 B1 回归测试（N1 渠道规则归一共源 / N3 暂停文案双句号）。

事故溯源约定：编号沿用计划书（docs/修复改进计划书-2026-08-15-第三轮.md）。
"""
from src.video_agent.core.flow_gates import FlowGateSet
from src.video_agent.utils.prompts import load_prompt


def test_n1_channel_rule_single_source_fc_protocol():
    """FC 协议经 include 注入共源段，旧「规格文档指明 API/模型」表述已删除。"""
    text = load_prompt("planner/system_fc.md", use_cache=False)
    assert "生成渠道来源规则" in text
    assert "若规格文档" not in text
    assert "必须把指定的 provider_id 和 model 传入" not in text


def test_n1_channel_rule_single_source_text_protocol():
    """文本协议同样经 include 引用共源段（P1：禁止复述，只允许引用）。"""
    text = load_prompt("planner/text_actions.md", use_cache=False)
    assert "生成渠道来源规则" in text
    assert "必须把指定的 provider_id 和 model 传入本操作" not in text


def test_n1_channel_rule_content_aligns_b7():
    """共源段口径与 B7 裁决一致：草稿自身 > 全局设置；规格文档/Skill 不承载模型参数。"""
    text = load_prompt("shared/gen_channel_rules.md", use_cache=False)
    assert "草稿自身参数" in text
    assert "全局设置" in text
    assert "规格文档与 Skill 不再承载模型能力参数" in text


def test_n3_pause_message_no_double_period():
    """block_reason 自带尾句号，pause_message 拼接归一化后不得出现「。。」。"""
    fs = FlowGateSet([])
    fs.mark_blocked(
        "【流程门禁拦截】写入分镜提示词被阻止：前置条件未满足 —— "
        "关键元素已确认。请先完成并确认当前阶段，不要跳过流程。"
    )
    msg = fs.pause_message()
    assert "。。" not in msg
    assert "不要跳过流程；" not in msg  # 归一化后以「；」连接且单句号收尾
    assert "不要跳过流程。请按" in msg
