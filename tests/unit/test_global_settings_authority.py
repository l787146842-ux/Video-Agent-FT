"""6666 二轮回归：规格交互只含 Skill 软维度 + 硬参数唯一来源全局设置。"""

from pathlib import Path


def test_skill_doc_step2_no_hard_param_wizard_text():
    """剧本生视频 Skill 步骤 2：不再要求渠道/分辨率/分镜最大时长交互，
    硬参数改为顶部「全局设置」，交互维度锁定 Skill 声明的建议条目。"""
    content = (
        Path(__file__).resolve().parents[2]
        / "data" / "skills" / "剧本生视频需上传剧本" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "候选项覆盖 出图渠道/出视频渠道" not in content
    assert "图片分辨率（1K/2K/4K）" not in content
    assert "一律取顶部导航栏「全局设置」" in content
    assert "建议条目：视频标题/视频类型/目标观众/输出语言/时长/画幅/叙事驱动/视觉风格/声音风格" in content
