"""Skill 创作模式：项目规范提示词、草稿自检、一次自修复（stub 适配器，不触网）。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.web import skill_authoring as sa
from src.video_agent.web.routes import plugins as pr

GOOD = """---
name: 宠物用品广告短片
description: 用户提供宠物用品产品图与卖点时，生成一支产品广告短片
---

# 宠物用品广告短片

> 调用规则：用户上传宠物用品产品图/卖点清单，希望产出一条广告短片时调用

## 流程规划

1. 读取素材：read_uploaded_doc、canvas_list_assets。
2. 卖点确认后调用 workflow_pause 暂停，等用户确认再继续。

## 素材分析

- 产品图记录外观、材质、颜色和可用角度；卖点拆成能落到画面的证据。

## 故事板设计

- 建关键元素、分镜、音频节点；分镜写景别、运镜、画面、卖点指向。

## 媒体生成

- 先出关键元素图，再逐镜静帧，确认后逐镜出视频，最后出音频。

## 提示词写法

- 写清主体、动作、环境、光线、景别、运镜；参数以全局设置为准。

## 组装导出

- 按分镜顺序组装时间线，导出前用 workflow_pause 再确认一次。
"""


class _FakeResult:
    def __init__(self, content: str):
        self.content = content


class _SeqAdapter:
    """按顺序返回预置回复，并记录每次 messages。"""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    async def chat(self, messages, temperature=0.3):  # noqa: ARG002
        self.calls.append(messages)
        return _FakeResult(self.texts.pop(0))


def _reply(content: str, note: str) -> str:
    return f"{note}\n```markdown\n{content}\n```"


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(pr.router, prefix="/api")
    from src.video_agent.exceptions import VideoAgentError
    from src.video_agent.web.app import video_agent_error_handler
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    """同 worker 其它用例会 ToolManager.reset()：显式重注册全套，
    保证创作工具目录覆盖真实注册集（不依赖导入副作用）。"""
    from src.video_agent.tools.analysis_tools import register_analysis_tools
    from src.video_agent.tools.canvas_tools import register_canvas_tools
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.manager import ToolManager
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    from src.video_agent.tools.structured_output import register_structured_output_tools
    from src.video_agent.tools.todo_tools import register_todo_tools
    from src.video_agent.tools.video.generate_video import GenerateVideoTool
    from src.video_agent.tools.web_tools import register_web_tools

    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()
    register_web_tools()
    register_structured_output_tools()
    register_todo_tools()
    register_canvas_tools()
    ToolManager.register(GenerateVideoTool())


# ---------- 创作提示词 / 工具目录 ----------

def test_tool_catalog_covers_every_registered_tool_with_description():
    catalog = sa.build_tool_catalog()
    from src.video_agent.tools import ToolManager
    for name in ToolManager._tools:
        assert f"- {name}：" in catalog, f"工具 {name} 未进创作目录"


def test_create_system_has_six_sections_and_real_tool_catalog():
    text = sa.build_create_system()
    for title in sa.REQUIRED_SECTIONS:
        assert f"## {title}" in text
    assert "description" in text and "200" in text
    assert "全局设置" in text and "workflow_pause" in text
    assert "read_uploaded_doc" in text  # 真实工具目录随提示词下发


# ---------- 草稿自检 ----------

def test_validate_good_draft_passes():
    assert sa.validate_skill_draft(GOOD, create_mode=True) == []


def test_validate_missing_section_and_placeholder():
    missing = GOOD.replace("## 组装导出", "## 其他")
    issues = sa.validate_skill_draft(missing, create_mode=True)
    assert any("缺少章节「组装导出」" in i for i in issues)

    placeholder = GOOD.replace(
        "- 按分镜顺序组装时间线，导出前用 workflow_pause 再确认一次。",
        "- 时间线怎么组装、导出前要确认哪些内容",
    )
    issues = sa.validate_skill_draft(placeholder, create_mode=True)
    assert any("模板占位句" in i for i in issues)


def test_validate_description_too_long_and_hardcoded_param():
    long_desc = GOOD.replace(
        "description: 用户提供宠物用品产品图与卖点时，生成一支产品广告短片",
        "description: " + "用" * 201,
    )
    issues = sa.validate_skill_draft(long_desc, create_mode=True)
    assert any("description 超长" in i for i in issues)

    hard = GOOD.replace("参数以全局设置为准", "输出 1080p、24fps")
    issues = sa.validate_skill_draft(hard, create_mode=True)
    assert any("写死的模型能力参数" in i for i in issues)


def test_validate_optimize_mode_does_not_require_six_headings():
    tag_style = (
        "---\nname: 旧式\ndescription: 测试\n---\n# 旧式\n> 调用规则：测试\n"
        "<planner>\n流程\n</planner>\n"
        "<storyboard_designer>\n故事板\n</storyboard_designer>\n"
        "<media_generator>\n生成参考图与视频\n</media_generator>\n"
        "<write_the_prompt>\n提示词写法规范\n</write_the_prompt>\n"
    )
    assert sa.validate_skill_draft(tag_style, create_mode=False) == []


# ---------- 路由：创作模式自修复 ----------

def test_create_mode_repairs_once_when_check_fails(client, monkeypatch):
    bad = GOOD.replace("## 组装导出", "## 其他")
    adapter = _SeqAdapter([_reply(bad, "初版"), _reply(GOOD, "已修复")])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: adapter)

    resp = client.post("/api/skills/assistant", json={
        "content": "# 新 Skill\n", "messages": [{"role": "user", "content": "做个宠物广告"}],
        "mode": "create",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(adapter.calls) == 2
    assert data["checks"]["passed"] is True
    assert data["checks"]["issues"] == []
    assert "组装导出" in data["content"]
    # 聊天区不重复渲染整篇代码块（正文已进预览）
    assert "```" not in data["reply"]
    assert "已修复" in data["reply"]


def test_create_mode_no_repair_when_first_draft_passes(client, monkeypatch):
    adapter = _SeqAdapter([_reply(GOOD, "初版")])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: adapter)
    resp = client.post("/api/skills/assistant", json={
        "content": "# 新 Skill\n", "messages": [{"role": "user", "content": "做个宠物广告"}],
        "mode": "create",
    })
    assert resp.status_code == 200, resp.text
    assert len(adapter.calls) == 1
    assert resp.json()["checks"] == {"passed": True, "issues": []}


def test_optimize_mode_does_not_auto_repair(client, monkeypatch):
    bad = GOOD.replace("## 组装导出", "## 其他")
    adapter = _SeqAdapter([_reply(bad, "改了一版")])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: adapter)
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "优化"}],
    })
    assert resp.status_code == 200, resp.text
    assert len(adapter.calls) == 1
    assert resp.json()["content"]


def test_reply_strips_skill_block():
    text = "说明\n```markdown\n# 标题\n正文\n```"
    assert pr._display_reply(text, True) == "说明"
    assert pr._display_reply("```markdown\n# 标题\n```", True).startswith("已生成 Skill 草稿")
    assert pr._display_reply("纯文本回复", False) == "纯文本回复"
