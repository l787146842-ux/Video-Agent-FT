# -*- coding: utf-8 -*-
"""规格文档写入契约单测（K8 骨架退役后，2026-09-20 对齐 flova 精简散文）。

钉死：① 新建规格 = 模型正文原样落盘（平台不注入骨架/占位节）；
② 8888 回归——带 `## ` 节的规格写入不再堆积「待用户补充」占位、不再出现
   「。## 」同行拼接、不含骨架的关键元素/分镜要点节（这些实体细节归故事板）；
③ R14 节级合并仍保护用户手改的节（模型重写同名节替换、用户独有节保留）；
④ 非规格文档整篇覆盖（行为零变更）；
⑤ 规格写入同批补《执行铁律.md》。
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


async def test_new_spec_is_model_content_verbatim(svc):
    """新建规格 = 模型正文原样，不注入任何骨架占位。"""
    content = "# 制片规格\n\n## 全局参数\n- 画幅比例：16:9 横屏\n- 输出语言：中文\n"
    res = await ToolManager.invoke_tool(
        "document_write", {"name": SPEC, "content": content})
    assert res.success is True, res.error
    assert _doc(svc, SPEC)["content"] == content


async def test_spec_write_has_no_scaffold_placeholders(svc):
    """8888 回归：带 `## ` 节的规格写入不堆占位、不同行拼接、不含骨架招灰节。"""
    res = await ToolManager.invoke_tool(
        "document_write",
        {"name": SPEC,
         "content": "## 全局参数\n\n- 画幅比例：16:9 横屏\n- 目标时长：60~90 秒\n"})
    assert res.success is True, res.error
    content = _doc(svc, SPEC)["content"]
    assert "待用户补充" not in content       # 无骨架占位
    assert "关键元素要点" not in content      # 骨架招灰节已退役（实体细节归故事板）
    assert "分镜要点" not in content
    assert "。## " not in content            # 无缺换行同行拼接 bug
    assert content.startswith("## 全局参数")


async def test_spec_section_merge_protects_user_edit(svc):
    """R14：用户手改的节在模型重写时不被盖掉（同名节替换、独有节保留）。"""
    await ToolManager.invoke_tool(
        "document_write",
        {"name": SPEC,
         "content": "## 全局参数\n- 画幅：16:9\n\n## 声音\n- 用户手改：中文旁白\n"})
    res = await ToolManager.invoke_tool(
        "document_write",
        {"name": SPEC, "content": "## 全局参数\n- 画幅：2.39:1\n"})
    assert res.success is True, res.error
    content = _doc(svc, SPEC)["content"]
    assert "画幅：2.39:1" in content        # 模型同名节替换
    assert "用户手改：中文旁白" in content     # 用户独有节保留


async def test_non_spec_doc_overwrites(svc):
    """非规格文档整篇覆盖（行为零变更）。"""
    await ToolManager.invoke_tool(
        "document_write", {"name": "随笔.md", "content": "第一版"})
    res = await ToolManager.invoke_tool(
        "document_write", {"name": "随笔.md", "content": "第二版"})
    assert res.success is True, res.error
    assert _doc(svc, "随笔.md")["content"] == "第二版"


async def test_spec_write_ensures_iron_rules_doc(svc):
    """规格写入同批补《执行铁律.md》。"""
    res = await ToolManager.invoke_tool(
        "document_write", {"name": SPEC, "content": "## 全局参数\n- 画幅：16:9\n"})
    assert res.success is True, res.error
    names = [d["name"] for d in svc.state_dict["documents"]]
    assert any("执行铁律" in n for n in names)
