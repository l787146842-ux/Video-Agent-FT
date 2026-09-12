"""第三轮审核 B1 回归测试（N1 渠道规则归一共源 / N3 暂停文案双句号）。

事故溯源约定：编号沿用计划书（原 docs/修复改进计划书-2026-08-15-第三轮.md，文书已清退，编号以事故台账为准）。
"""
from src.video_agent.tools.document_tools import ImageGenerateTool
from src.video_agent.tools.video.generate_video import GenerateVideoTool
from src.video_agent.utils.prompts import load_prompt


def test_n1_channel_rule_single_source_fc_protocol():
    """N1 渠道规则唯一家 = 生成工具描述（2026-09-12 治理批：
    protocol「生成渠道来源规则」段迁出至 image_generate/generate_video
    描述；旧「规格文档指明 API/模型」表述保持删除）。
    （原两个同名测试合并为一，覆盖两份 docstring 的断言意图。）"""
    image_desc = ImageGenerateTool().description or ""
    video_desc = GenerateVideoTool().description or ""
    for desc in (image_desc, video_desc):
        assert "生成渠道优先级" in desc, "渠道规则迁入端条款丢失"
        assert "草稿自身参数" in desc or "目标草稿卡自身的视频配置" in desc
        assert "规格文档与 Skill 不承载渠道参数" in desc
    text = load_prompt("planner/protocol.md", use_cache=False)
    assert "生成渠道来源规则" not in text, "protocol 渠道段已迁出，不得回潮"
    assert "若规格文档" not in text
    assert "必须把指定的 provider_id 和 model 传入" not in text
