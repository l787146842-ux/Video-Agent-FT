# -*- coding: utf-8 -*-
"""能力词单一源对齐测试。

断言 read_skill 工具描述（src/video_agent/tools/document_tools.py
ReadSkillTool）中「Skill 文档章节标签→真实动作」对照段列举的能力词集合
== skill_runtime.registry.PIPELINE_CAPABILITY_TOOLS（双向，抓住漂移）。

registry 为唯一事实源：对照段增删词汇必须同批同步 PIPELINE_CAPABILITY_TOOLS。
（2026-09-12 指令体量治理批：对照段自 protocol.md 迁入 read_skill 工具描述。）
"""
import re

from src.video_agent.skill_runtime.registry import PIPELINE_CAPABILITY_TOOLS
from src.video_agent.tools.document_tools import ReadSkillTool

# 能力词对照段格式：- cap1 / cap2 / cap3（中文描述）：... 或 - cap（中文描述）：...
_CAPABILITY_LINE_RE = re.compile(r"^- ([\w /]+)\uff08", re.M)


def _extract_doc_capabilities() -> set:
    """从 read_skill 工具描述的对照段提取能力词集合。"""
    text = ReadSkillTool().description or ""
    # 定位对照段：以「对应真实动作」行开始，截取其后全部条目
    start = text.find("对应真实动作")
    assert start != -1, "read_skill 描述未找到能力词对照段"
    section = text[start:]
    caps = set()
    for match in _CAPABILITY_LINE_RE.findall(section):
        # 每行可能含多个能力词用 " / " 分隔
        for word in match.split("/"):
            word = word.strip()
            if word:
                caps.add(word)
    return caps


def test_capability_words_bidirectional():
    """read_skill 对照段能力词集 == PIPELINE_CAPABILITY_TOOLS（双向）。"""
    doc_caps = _extract_doc_capabilities()
    registry_caps = set(PIPELINE_CAPABILITY_TOOLS)

    missing_in_doc = registry_caps - doc_caps
    extra_in_doc = doc_caps - registry_caps

    assert not missing_in_doc, (
        f"registry PIPELINE_CAPABILITY_TOOLS 中有但对照段缺失: "
        f"{sorted(missing_in_doc)}"
    )
    assert not extra_in_doc, (
        f"对照段中有但 registry PIPELINE_CAPABILITY_TOOLS 缺失: "
        f"{sorted(extra_in_doc)}"
    )
