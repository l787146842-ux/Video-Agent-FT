# -*- coding: utf-8 -*-
"""执行器能力注册表（Policy-as-Data，审核整改批 2：欠账显性化）。

执行器按能力分两级：
- ``execution``（执行级）：真实执行，产出真实产物/副作用；
- ``planning``（规划级）：只产出规划文本/方案文档，不产生真实媒体——
  欠账显性化：能力级别是数据，前端与回喂可见，杜绝"假装做完了"。

新增执行器必须在此登记（deny-by-default：``scripts/check_executor_skill_drift.py``
棘轮断言未登记即红）。能力级别变化（planning 清偿为 execution）同批更新本表。
"""
from typing import Dict

CAPABILITY_EXECUTION = "execution"
CAPABILITY_PLANNING = "planning"

# 执行器工具名 → 能力级别（唯一事实源）
EXECUTOR_CAPABILITY: Dict[str, str] = {
    "script_analyze": CAPABILITY_EXECUTION,
    "storyboard_key_elements": CAPABILITY_EXECUTION,
    "storyboard_shots": CAPABILITY_EXECUTION,
    "storyboard_audio": CAPABILITY_EXECUTION,
    "write_media_prompt": CAPABILITY_EXECUTION,
    # 欠账显性化：真实 TTS/BGM 与成片合成暂缓（2026-08-21 用户裁定），
    # 当前只产出规划文本/组装方案文档
    "audio_generate": CAPABILITY_PLANNING,
    "video_assembler": CAPABILITY_PLANNING,
}

# 规划级标注文案（description 追加与前端徽标同源；唯一表述点）
PLANNING_NOTE = "【规划级执行器：产出规划/方案文本，不产生真实媒体文件】"


def capability_of(tool_name: str) -> str:
    """能力级别查询；未登记视为执行级（登记强制归棘轮门禁管）。"""
    return EXECUTOR_CAPABILITY.get(str(tool_name or "").strip(), CAPABILITY_EXECUTION)


def is_planning(tool_name: str) -> bool:
    """是否规划级执行器。"""
    return capability_of(tool_name) == CAPABILITY_PLANNING


def planning_note(tool_name: str) -> str:
    """description 尾部能力标注（规划级返回标注文案，执行级返回空串）。"""
    return PLANNING_NOTE if is_planning(tool_name) else ""


__all__ = [
    "CAPABILITY_EXECUTION", "CAPABILITY_PLANNING", "EXECUTOR_CAPABILITY",
    "PLANNING_NOTE", "capability_of", "is_planning", "planning_note",
]
