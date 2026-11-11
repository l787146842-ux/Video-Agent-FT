"""Flova 六节骨架的阶段探针回归（2026-11-11 裁决）。

背景：主文档改用 Flova 六节骨架（目标与交付 / 项目结构规划 / 制片规格 /
创作流程规划 / 专业创作方法 / Reference 路由）后，旧的阶段标题词
（故事板设计 / 媒体生成 / 提示词写法 / 组装导出）在主文档里全部消失。
实测探针整体落空——只剩 `planning`，`available_tools` 只剩 script_analyze。

这会连锁打断三处平台行为：
1. `available_tools` 决定子代理可用工具面与委派能力；
2. `prompt_gates` 的音频闸只在 Skill 声明 storyboard_audio 时要求音频；
3. `stage_probes` 的阶段推进判定。

本文件钉死：六节骨架的标题必须被识别成对应阶段能力。
"""
from src.video_agent.skill_runtime.registry import (
    CAPABILITY_TOOL_STAGES,
    PIPELINE_CAPABILITY_TOOLS,
)
from src.video_agent.web import skill_docs as sd

FLOVA_DOC = """---
name: 骨架探针
description: Flova 六节骨架的阶段探针用例
---

# 骨架探针

## 一、目标、输入与交付

把剧本做成短剧。

## 二、项目结构规划

- 登记关键元素、分镜、音频。

## 三、制片规格

- 全局参数写入制片规格。

## 四、创作流程规划

1. 分析剧本。

**依赖关系：** 2→1。

**何时暂停：** 每阶段结束暂停。

## 五、专业创作方法

- 分类与拆解规则。

## 六、Reference 路由

- 读 `references/媒体生成.md`、`references/提示词写作.md`、`references/剪辑交付.md`。
"""


def _stages() -> dict:
    return sd.split_skill_sections(FLOVA_DOC)


def test_flova_skeleton_maps_all_core_stages():
    """六节骨架必须映射出全部核心阶段键。"""
    stages = _stages()
    for key in ("planning", "storyboard_ke", "storyboard_shot",
                "storyboard_audio", "generation", "prompt_draft", "assembly"):
        assert key in stages, f"阶段键 {key} 未被识别；实际={sorted(stages)}"


def test_flova_skeleton_wires_every_pipeline_capability():
    """全部管线能力探针都要命中（否则子代理工具面/音频闸整体失效）。"""
    stages = set(_stages())
    missing = []
    for tool in PIPELINE_CAPABILITY_TOOLS:
        wanted = CAPABILITY_TOOL_STAGES.get(tool) or ()
        if not any((stages and s in stages) for s in wanted):
            missing.append(tool)
    assert not missing, f"能力探针落空: {missing}"


def test_reference_routing_section_declares_assembly():
    """组装/导出下沉到剪辑交付分册：主文档路由段仍须声明 assembly 能力。"""
    assert "assembly" in _stages()


def test_heading_stage_hint_is_case_insensitive():
    """标题含英文「Reference」时也能命中（关键字表用小写）。"""
    assert sd._stage_from_heading("六、Reference 路由")
    assert sd._stage_from_heading("六、REFERENCE 路由")


def test_old_skeleton_still_maps():
    """旧骨架（故事板设计/媒体生成/提示词写法/组装导出）保持兼容。"""
    old_doc = (
        "## 三、剧本分析\n内容\n\n"
        "## 四、故事板设计\n内容\n\n"
        "## 五、媒体生成\n内容\n\n"
        "## 六、提示词写法\n内容\n\n"
        "## 七、组装导出\n内容\n"
    )
    stages = sd.split_skill_sections(old_doc)
    for key in ("planning", "storyboard_ke", "storyboard_shot",
                "storyboard_audio", "generation", "prompt_draft", "assembly"):
        assert key in stages, f"旧骨架阶段键 {key} 回归丢失；实际={sorted(stages)}"
