# -*- coding: utf-8 -*-
"""规格文档节级合并写入测试（R14：is_spec 命中走 _merge_sections，不再整篇覆盖）。

背景（Harness 对齐 flova P2-I）：document_write 对规格文档整篇覆盖会盖掉
用户手改的节；改为按 `## ` 标题节级合并——同名节 new 替换、new 独有节追加、
old 独有节保留；old 无任何 `## ` 标题回落整篇覆盖。非规格文档行为零变更。
"""
import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.tools.document_tools import (
    DocumentWriteTool,
    WriteDocumentInput,
    _merge_sections,
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


# ---------- _merge_sections 纯函数 ----------

def test_merge_same_name_section_replaced():
    """同名节用 new 替换（含节内正文整体换新）"""
    old = "# 规格\n\n## 画幅\n- 16:9\n\n## 时长\n- 30秒\n"
    new = "# 规格 v2\n\n## 画幅\n- 9:16 竖屏\n"
    merged = _merge_sections(old, new)
    assert "## 画幅\n- 9:16 竖屏" in merged
    assert "- 16:9" not in merged
    assert "## 时长" in merged  # new 未提及的 old 独有节保留


def test_merge_new_section_appended():
    """new 独有节追加到合并结果"""
    old = "# 规格\n\n## 画幅\n- 16:9\n"
    new = "# 规格\n\n## 画幅\n- 16:9\n\n## 声音与语言\n- 中文旁白\n"
    merged = _merge_sections(old, new)
    assert "## 声音与语言\n- 中文旁白" in merged
    assert merged.index("## 画幅") < merged.index("## 声音与语言")


def test_merge_old_only_section_preserved():
    """old 独有节（用户手改/模型未重写的节）保留，不被 new 盖掉"""
    old = (
        "# 规格\n\n前言导语\n\n"
        "## 用户手记\n- 用户自己写的内容\n\n"
        "## 画幅\n- 16:9（旧值）\n"
    )
    new = "# 规格\n\n## 画幅\n- 9:16（新值）\n\n## 时长\n- 60秒\n"
    merged = _merge_sections(old, new)
    assert "## 用户手记\n- 用户自己写的内容" in merged  # old 独有节保留
    assert "前言导语" in merged  # 无标题头块保留
    assert "- 9:16（新值）" in merged and "（旧值）" not in merged  # 同名节替换
    assert "## 时长\n- 60秒" in merged  # new 独有节追加


def test_merge_old_without_sections_falls_back_to_overwrite():
    """old 不含任何 `## ` 标题 → 回落整篇覆盖，直接返回 new"""
    old = "# 规格\n\n只有一段散文，没有任何节标题。\n"
    new = "# 规格 v2\n\n## 画幅\n- 16:9\n"
    assert _merge_sections(old, new) == new
    # old 为空串同样回落
    assert _merge_sections("", new) == new


# ---------- 工具级：document_write 走合并 ----------

@pytest.mark.asyncio
async def test_spec_doc_write_merges_sections(svc):
    """防回归钉：is_spec_doc_name 命中的文档重写走节级合并，
    用户手改的独有节不被模型整篇覆盖盖掉"""
    svc.state_dict["documents"] = [{
        "id": "doc-1", "name": "制片规格.md",
        "content": "# 规格\n\n## 用户手记\n- 用户改过\n\n## 画幅\n- 16:9\n",
        "created_at": "x", "updated_at": "x", "revisions": 3,
    }]
    result = await DocumentWriteTool().aexecute(WriteDocumentInput(
        name="制片规格.md",
        content="# 规格\n\n## 画幅\n- 9:16\n",
    ))
    assert result.success and result.data["action"] == "updated"
    doc = next(d for d in svc.state_dict["documents"] if d["name"] == "制片规格.md")
    assert "用户手记" in doc["content"]  # old 独有节保留
    assert "用户改过" in doc["content"]
    assert "9:16" in doc["content"] and "16:9" not in doc["content"]
    assert doc["revisions"] == 4  # revisions+1 既有逻辑保持


@pytest.mark.asyncio
async def test_non_spec_doc_write_still_overwrites(svc):
    """非规格文档行为零变更：整篇覆盖 + revisions+1"""
    svc.state_dict["documents"] = [{
        "id": "doc-2", "name": "随想笔记.md",
        "content": "# 旧笔记\n\n## 旧节\n- 旧内容\n",
        "created_at": "x", "updated_at": "x", "revisions": 1,
    }]
    result = await DocumentWriteTool().aexecute(WriteDocumentInput(
        name="随想笔记.md",
        content="# 新笔记\n",
    ))
    assert result.success and result.data["action"] == "updated"
    doc = svc.state_dict["documents"][0]
    assert doc["content"] == "# 新笔记\n"  # 不合并，整篇覆盖
    assert doc["revisions"] == 2
