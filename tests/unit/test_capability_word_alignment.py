# -*- coding: utf-8 -*-
"""能力词单一源对齐测试。

断言 prompts/planner/system_fc.md「Skill 文档能力词对照」段落中列举的能力词集合
== skill_runtime.registry.PIPELINE_CAPABILITY_TOOLS（双向，抓住漂移）。

registry 为唯一事实源：system_fc.md 对照段增删词汇必须同批同步 PIPELINE_CAPABILITY_TOOLS。
"""
import re
from pathlib import Path

from src.video_agent.skill_runtime.registry import PIPELINE_CAPABILITY_TOOLS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_FC_PATH = PROJECT_ROOT / "prompts" / "planner" / "system_fc.md"

# 能力词对照段格式：- cap1 / cap2 / cap3（中文描述）：... 或 - cap（中文描述）：...
_CAPABILITY_LINE_RE = re.compile(r"^- ([\w /]+)\uff08", re.M)


def _extract_doc_capabilities() -> set:
    """从 system_fc.md 的「Skill 文档能力词对照」段落提取能力词集合。"""
    text = SYSTEM_FC_PATH.read_text(encoding="utf-8")
    # 定位段落：以 == Skill 文档能力词对照 开头，到下一个 == 或 {{include 截止
    start = text.find("== Skill \u6587\u6863\u80fd\u529b\u8bcd\u5bf9\u7167")
    assert start != -1, "system_fc.md 未找到「Skill 文档能力词对照」段落"
    # 从段头开始截取到下一个 {{include 或 == 段头
    rest = text[start:]
    end_markers = [rest.find("\n{{include:", 1), rest.find("\n== ", 3)]
    end = min((e for e in end_markers if e > 0), default=len(rest))
    section = rest[:end]
    caps = set()
    for match in _CAPABILITY_LINE_RE.findall(section):
        # 每行可能含多个能力词用 " / " 分隔
        for word in match.split("/"):
            word = word.strip()
            if word:
                caps.add(word)
    return caps


def test_capability_words_bidirectional():
    """system_fc.md 能力词对照集 == PIPELINE_CAPABILITY_TOOLS（双向）。"""
    doc_caps = _extract_doc_capabilities()
    registry_caps = set(PIPELINE_CAPABILITY_TOOLS)

    missing_in_doc = registry_caps - doc_caps
    extra_in_doc = doc_caps - registry_caps

    assert not missing_in_doc, (
        f"registry PIPELINE_CAPABILITY_TOOLS 中有但 system_fc.md 对照段缺失: "
        f"{sorted(missing_in_doc)}"
    )
    assert not extra_in_doc, (
        f"system_fc.md 对照段中有但 registry PIPELINE_CAPABILITY_TOOLS 缺失: "
        f"{sorted(extra_in_doc)}"
    )
