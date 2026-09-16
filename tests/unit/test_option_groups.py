# -*- coding: utf-8 -*-
"""确认选项兜底归组测试（防笨模型：无 group 选项按维度启发式补分组）。

回归样本来自 6666 项目事故：gemini 502 降级到 Qwen3-235B 后，
模型输出 10 个规格选项但全部未带 group，前端分页向导退化成普通单选卡。
"""
from src.video_agent.core.option_groups import classify_option, fill_option_groups


# ---------- 单选项分类 ----------

def test_classify_aspect_and_duration():
    assert classify_option("横版16:9") == "画幅"
    assert classify_option("9:16 竖屏") == "画幅"
    assert classify_option("10分钟") == "时长"
    assert classify_option("3-5 min") == "时长"


def test_classify_style_and_audio():
    assert classify_option("写实科幻") == "视觉风格"
    assert classify_option("赛博朋克") == "视觉风格"
    assert classify_option("中文旁白") == "声音与语言"


def test_classify_channel_by_hint_words():
    # description 含「渠道」→ 出视频/出图渠道（不依赖真实配置）
    assert classify_option("火山引擎Seedance2.0", "视频生成渠道") == "出视频API与模型"
    assert classify_option("APIMART midjourney", "图像生成渠道") == "出图API与模型"


def test_classify_not_confused_by_generation_verbs():
    """回归（proj-1786160896 事故）：「图像生成提示词」这类动词短语不得被误判为渠道维度，
    否则阶段确认卡片会被误造成标题为「出图API与模型」的分页向导。"""
    dim = classify_option("确认关键元素，编写提示词", "关键元素符合要求，开始为每个关键元素编写图像生成提示词")
    assert dim not in ("出图API与模型", "出视频API与模型")


def test_classify_unknown():
    assert classify_option("完全无关的选项") == "其它"


# ---------- 兜底归组 ----------

def test_fill_groups_qwen_6666_case():
    """6666 事故真实样本：10 个无 group 选项 → 归出多维度，前端可渲染分页向导"""
    options = [
        {"label": "横版16:9", "description": "标准影视画幅比例"},
        {"label": "竖版9:16", "description": "移动端适配比例"},
        {"label": "写实科幻", "description": "视觉风格选择"},
        {"label": "赛博朋克", "description": "视觉风格选择"},
        {"label": "10分钟", "description": "总时长选择"},
        {"label": "15分钟", "description": "总时长选择"},
        {"label": "中文旁白", "description": "语言版本选择"},
        {"label": "英文旁白", "description": "语言版本选择"},
        {"label": "火山引擎Seedance2.0", "description": "视频生成渠道"},
        {"label": "APIMART Doubao", "description": "视频生成渠道"},
    ]
    result = fill_option_groups(options)
    groups = {o["group"] for o in result}
    assert len(groups) >= 4  # 画幅/视觉风格/时长/声音与语言/系统注入
    assert all(o.get("group") for o in result)
    by_group = {}
    for o in result:
        by_group.setdefault(o["group"], []).append(o["label"])
    assert set(by_group["画幅"]) == {"横版16:9", "竖版9:16"}
    assert set(by_group["时长"]) == {"10分钟", "15分钟"}
    # R12：系统注入维度（渠道/分辨率）不再以原维度名成组，并入单一组标签
    assert "出视频API与模型" not in groups
    assert set(by_group["系统注入（不入规格文档）"]) == {"火山引擎Seedance2.0", "APIMART Doubao"}


def test_system_injected_dimensions_merge_into_single_group():
    """R12：出图/出视频渠道 + 图片/视频分辨率四个系统注入维度并成同一组标签；
    与规格维度（画幅）共存时仍归组（≥2 个组标签）"""
    options = [
        {"label": "横版16:9"},
        {"label": "竖版9:16"},
        {"label": "APIMART midjourney", "description": "图像生成渠道"},
        {"label": "火山引擎Seedance2.0", "description": "视频生成渠道"},
        {"label": "2K", "description": "图片分辨率档位"},
        {"label": "1080p", "description": "视频分辨率档位"},
    ]
    result = fill_option_groups(options)
    groups = {o["group"] for o in result}
    assert groups == {"画幅", "系统注入（不入规格文档）"}


def test_only_system_injected_single_label_stays_plain():
    """R12 撤回判定按写入后的组标签计数：多个系统注入维度并入同一标签后
    只剩单一组标签 → 仍撤回归组（不造单页向导）"""
    options = [
        {"label": "APIMART midjourney", "description": "图像生成渠道"},
        {"label": "火山引擎Seedance2.0", "description": "视频生成渠道"},
        {"label": "2K", "description": "图片分辨率档位"},
        {"label": "720p", "description": "视频分辨率档位"},
        {"label": "1080p", "description": "视频分辨率档位"},
    ]
    result = fill_option_groups(options)
    assert all("group" not in o for o in result)


def test_existing_groups_not_touched():
    """模型已标注 group 时绝不改动（尊重模型输出）"""
    options = [
        {"label": "A", "group": "自定义维度1"},
        {"label": "B"},  # 部分缺失也不触发兜底（不是「全部无 group」）
    ]
    result = fill_option_groups(options)
    assert result[0]["group"] == "自定义维度1"
    assert "group" not in result[1]


def test_phase_confirm_options_not_grouped():
    """回归（proj-1786160896 事故真实样本）：关键元素拆解后的阶段确认只有 2 个选项，
    曾被兜底归组误造成「出图API与模型」分页向导；选项 <5 时一律不归组。"""
    options = [
        {"label": "确认关键元素，编写提示词",
         "description": "关键元素符合要求，开始为每个关键元素编写图像生成提示词"},
        {"label": "需要补充/修改关键元素",
         "description": "对部分角色、道具或场景进行增删或调整"},
    ]
    result = fill_option_groups(options)
    assert all("group" not in o for o in result)


def test_few_options_not_grouped_even_if_multi_dimension():
    """即使 4 个选项分属不同维度，低于最小选项数也不归组（阶段确认防误伤保险）"""
    options = [
        {"label": "16:9"},
        {"label": "3分钟"},
        {"label": "写实风格"},
        {"label": "中文旁白"},
    ]
    result = fill_option_groups(options)
    assert all("group" not in o for o in result)


def test_single_dimension_stays_plain():
    """普通二选一确认（同属「其它」单维度）不得被强行变成单页向导"""
    options = [
        {"label": "确认提示词草案，开始生成概念图", "description": "将目标草稿标记为已确认并重新触发生成"},
        {"label": "先调整提示词", "description": "告诉我需要修改的草稿与修改意见"},
    ]
    result = fill_option_groups(options)
    assert all("group" not in o for o in result)


def test_empty_options():
    assert fill_option_groups([]) == []
