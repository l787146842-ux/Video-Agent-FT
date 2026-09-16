# -*- coding: utf-8 -*-
"""K8 批（2026-09-16 对齐 flova）规格脚手架契约单测。

钉死：① 新建空规格 → 内容=骨架（含「全局制作参数」占位）；
② 新建带 `## ` 节规格 → 同名节合并（骨架独有节保留、模型同名节替换）；
③ 非规格文档新建 → 不注骨架（行为零变更）；
④ 存量空规格更新 → 先注骨架再合并；
⑤ 骨架不含系统注入四维度（wizard 标签口径）。
"""
import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.tools.document_tools import register_document_tools
from src.video_agent.tools.manager import ToolManager

SPEC = "制片规格.md"


@pytest.fixture(autouse=True)
def _reset_tools():
    ToolManager.reset()
    register_document_tools()
    yield
    ToolManager.reset()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _doc(svc, name):
    return next(d for d in svc.state_dict["documents"] if d["name"] == name)


async def test_new_empty_spec_gets_scaffold(svc):
    res = await ToolManager.invoke_tool(
        "document_write", {"name": SPEC, "content": ""})
    assert res.success is True, res.error
    content = _doc(svc, SPEC)["content"]
    assert "全局制作参数" in content
    assert "待用户补充" in content


async def test_new_spec_merges_same_name_sections(svc):
    res = await ToolManager.invoke_tool(
        "document_write",
        {"name": SPEC,
         "content": "## 一、全局制作参数（待用户补充）\n- 时长与结构：3 分钟 / 5 段\n"})
    assert res.success is True, res.error
    content = _doc(svc, SPEC)["content"]
    assert "3 分钟 / 5 段" in content        # 模型同名节替换骨架占位
    assert "## 二、关键元素要点" in content   # 骨架独有节保留
    assert "## 四、备注" in content


async def test_non_spec_doc_unchanged(svc):
    res = await ToolManager.invoke_tool(
        "document_write", {"name": "随笔.md", "content": "自由散文"})
    assert res.success is True, res.error
    assert _doc(svc, "随笔.md")["content"] == "自由散文"


async def test_existing_empty_spec_update_injects_scaffold(svc):
    svc.state_dict["documents"] = [{
        "id": "doc-1", "name": SPEC, "content": "",
        "created_at": "", "updated_at": "", "revisions": 0}]
    res = await ToolManager.invoke_tool(
        "document_write",
        {"name": SPEC, "content": "## 三、分镜要点（待用户补充）\n- 每镜 3-6 秒\n"})
    assert res.success is True, res.error
    content = _doc(svc, SPEC)["content"]
    assert "每镜 3-6 秒" in content
    assert "## 一、全局制作参数" in content


def test_scaffold_excludes_system_injected_dimensions():
    from src.video_agent.tools.document_tools import _load_spec_scaffold
    scaffold = _load_spec_scaffold()
    assert scaffold
    assert "## 一、全局制作参数" in scaffold
    for label in ("出图API与模型", "出视频API与模型"):
        assert label not in scaffold
