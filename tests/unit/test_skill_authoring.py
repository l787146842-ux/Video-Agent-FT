"""Skill 创作模式：通用文档契约、草稿自检、一次自修复（stub 适配器，不触网）。

2026-11-11 通用 skill 口径：frontmatter + Markdown 标题式正文；不再有
`<planner>` 等标签章节，自检只查通用骨架（frontmatter / 至少两个二级标题 /
含制作流程 / 实质内容 / 字段表与代码块）。
"""
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

## 一、这个 Skill 做什么

把宠物用品的产品图与卖点做成一支广告短片。

## 二、制作流程

1. 读取并整理用户上传的产品素材。
2. 卖点确认后暂停，等用户确认再继续。

**依赖关系：** 2→1。

**何时暂停：** 每个关键阶段结束后停下来与用户确认。

## 三、剧本分析

- 产品图记录外观、材质、颜色和可用角度；卖点拆成能落到画面的证据。

## 四、故事板设计

- 建关键元素、分镜、音频节点；分镜写景别、运镜、画面、卖点指向。

## 五、媒体生成

- 先出关键元素图，再逐镜静帧，确认后逐镜出视频，最后出音频。

## 六、提示词写法

- 写清主体、动作、环境、光线、景别、运镜；参数以全局设置为准。

## 七、组装导出

- 按分镜顺序组装时间线，导出前再向用户确认一次。
"""


class _FakeResult:
    def __init__(self, content: str):
        self.content = content


class _SeqAdapter:
    """按顺序返回预置回复，并记录每次 messages。"""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    async def chat(self, messages, temperature=0.3, **kwargs):  # noqa: ARG002
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


# ---------- 创作提示词（通用契约） ----------

def test_create_system_is_generic_contract():
    text = sa.build_create_system()
    assert "frontmatter" in text and "description" in text and "200" in text
    assert "二级标题" in text or "##" in text
    assert "references/" in text
    assert "全局设置" in text
    # 文档只保留标题/章节与自然语言说明，不注入/罗列工具名
    assert "read_uploaded_doc" not in text
    assert "workflow_pause" not in text
    assert "工具名" in text
    # 散文写法，禁平台字段表/提示词代码块
    assert "散文" in text and "字段表" in text and "代码块" in text


# ---------- 草稿自检 ----------

def test_validate_good_draft_passes():
    assert sa.validate_skill_draft(GOOD, create_mode=True) == []


def test_validate_stock_skills_pass_the_structural_contract():
    """存量 16 份按通用结构自检：frontmatter/标题/流程/占位句零问题。"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "data" / "skills"
    structural = ("缺少 frontmatter", "缺少 name", "缺少 description",
                  "二级标题", "缺少「制作流程」", "模板占位句")
    for doc in sorted(root.glob("*/SKILL.md")):
        text = doc.read_text(encoding="utf-8-sig")
        issues = sa.validate_skill_draft(text, create_mode=True)
        bad = [i for i in issues if any(k in i for k in structural)]
        assert not bad, f"[{doc.parent.name}] 结构项自检不通过: {bad}"


def test_validate_rejects_internal_fields_and_code_blocks():
    table_doc = GOOD.replace(
        "- 建关键元素、分镜、音频节点；分镜写景别、运镜、画面、卖点指向。",
        "| shot_id | 说明 |\n| --- | --- |\n| 001 | 镜头 |",
    )
    issues = sa.validate_skill_draft(table_doc, create_mode=True)
    assert any("平台内部字段表" in i for i in issues)

    id_doc = GOOD.replace(
        "- 建关键元素、分镜、音频节点；分镜写景别、运镜、画面、卖点指向。",
        "- 用 character_id 绑定角色卡，再写分镜。",
    )
    issues = sa.validate_skill_draft(id_doc, create_mode=True)
    assert any("平台内部字段名" in i for i in issues)

    code_doc = GOOD.replace(
        "- 写清主体、动作、环境、光线、景别、运镜；参数以全局设置为准。",
        "```text\n主体：宠物\n```",
    )
    issues = sa.validate_skill_draft(code_doc, create_mode=True)
    assert any("代码块" in i for i in issues)


def test_validate_style_issues_are_not_create_only():
    """优化模式也要提示字段名/字段表（不判代码块，避免误伤存量写法）。"""
    table_doc = GOOD.replace(
        "- 建关键元素、分镜、音频节点；分镜写景别、运镜、画面、卖点指向。",
        "| shot_id | 说明 |\n| --- | --- |\n| 001 | 镜头 |",
    )
    issues = sa.validate_skill_draft(table_doc, create_mode=False)
    assert any("平台内部字段表" in i for i in issues)


def test_validate_missing_flow_and_placeholder():
    no_flow = GOOD.replace("## 二、制作流程", "## 二、杂项说明")
    issues = sa.validate_skill_draft(no_flow, create_mode=True)
    assert any("缺少「制作流程」类章节" in i for i in issues)

    placeholder = GOOD.replace(
        "- 按分镜顺序组装时间线，导出前再向用户确认一次。",
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


def test_validate_optimize_mode_does_not_require_headings():
    """优化模式只查通用项：标题写法差异不误判（结构项零问题）。"""
    def structural(issues):
        return [i for i in issues
                if any(k in i for k in ("二级标题", "缺少「制作流程」", "模板占位句"))]

    heading_style = (
        "---\nname: 标题式\ndescription: 测试\n---\n"
        "# 标题式\n\n## 制作流程\n流程正文\n"
    )
    assert structural(sa.validate_skill_draft(heading_style, create_mode=False)) == []


# ---------- 路由：创作模式自修复 ----------

def test_create_mode_repairs_once_when_check_fails(client, monkeypatch):
    bad = GOOD.replace("## 二、制作流程", "## 二、杂项说明")
    adapter = _SeqAdapter([_reply(bad, "初版"), _reply(GOOD, "已修复")])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: adapter)

    resp = client.post("/api/skills/assistant", json={
        "content": "---\nname: 新 Skill\ndescription: x\n---\n",
        "messages": [{"role": "user", "content": "做个宠物广告"}],
        "mode": "create",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(adapter.calls) == 2
    assert data["checks"]["passed"] is True
    assert data["checks"]["issues"] == []
    assert "## 二、制作流程" in data["content"]
    assert "```" not in data["reply"]
    assert "已修复" in data["reply"]


def test_create_mode_no_repair_when_first_draft_passes(client, monkeypatch):
    adapter = _SeqAdapter([_reply(GOOD, "初版")])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: adapter)
    resp = client.post("/api/skills/assistant", json={
        "content": "---\nname: 新 Skill\ndescription: x\n---\n",
        "messages": [{"role": "user", "content": "做个宠物广告"}],
        "mode": "create",
    })
    assert resp.status_code == 200, resp.text
    assert len(adapter.calls) == 1
    assert resp.json()["checks"] == {"passed": True, "issues": []}


def test_optimize_mode_does_not_auto_repair(client, monkeypatch):
    bad = GOOD.replace("## 二、制作流程", "## 二、杂项说明")
    adapter = _SeqAdapter([_reply(bad, "改了一版")])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: adapter)
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "优化"}],
    })
    assert resp.status_code == 200, resp.text
    assert len(adapter.calls) == 1
    assert resp.json()["content"]


def test_optimize_mode_repairs_internal_field_style(client, monkeypatch):
    """优化模式也清理平台字段表：只对文风类问题自修复一次。"""
    bad = GOOD.replace(
        "- 建关键元素、分镜、音频节点；分镜写景别、运镜、画面、卖点指向。",
        "| shot_id | 说明 |\n| --- | --- |\n| 001 | 镜头 |",
    )
    adapter = _SeqAdapter([_reply(bad, "初稿"), _reply(GOOD, "已清理")])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: adapter)
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "清理字段表"}],
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(adapter.calls) == 2
    assert data["checks"]["passed"] is True
    assert "shot_id" not in data["content"]
    assert "已清理" in data["reply"]


def test_reply_strips_skill_block():
    text = "说明\n```markdown\n# 标题\n正文\n```"
    assert pr._display_reply(text, True).startswith("说明")
    assert "预览已更新" in pr._display_reply(text, True)
    assert pr._display_reply(
        "```markdown\n# 标题\n```", True, mode="create",
    ).startswith("已生成")
    assert pr._display_reply("纯文本回复", False) == "纯文本回复"


def test_extract_block_accepts_heading_doc_without_h1():
    """通用文档：frontmatter + 二级标题即可被接受；纯散文块仍被拒。"""
    doc = "---\nname: 甲\ndescription: 乙\n---\n\n## 制作流程\n流程\n"
    assert pr._extract_skill_block(f"说明\n```markdown\n{doc}\n```") == doc.strip()
    assert pr._extract_skill_block("```markdown\n纯散文没有结构\n```") is None
