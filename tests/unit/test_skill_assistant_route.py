"""POST /api/skills/assistant（非流式）+ /assistant/stream（SSE）契约测试。

验证：代码块提取 / 无代码块回落 null / LLM 失败回落 null；
流式端点：思考与正文帧顺序、done 终态收口、创作模式自修复、失败错误帧。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.adapters.base_chat import StreamChunk
from src.video_agent.web.routes import plugins as pr


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(pr.router, prefix="/api")
    # P9：standalone 应用需注册统一转译 handler（与生产 app.py 同源）
    from src.video_agent.exceptions import VideoAgentError
    from src.video_agent.web.app import video_agent_error_handler
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


class _FakeResult:
    def __init__(self, text: str):
        self.content = text


class _FakeAdapter:
    def __init__(self, text: str):
        self._text = text
        self.calls = []
        self.kwargs = []

    async def chat(self, messages, temperature=0.3, **kwargs):  # noqa: ARG002
        self.calls.append(messages)
        self.kwargs.append(kwargs)
        return _FakeResult(self._text)


class _BoomAdapter:
    async def chat(self, messages, temperature=0.3, **kwargs):  # noqa: ARG002
        raise RuntimeError("boom")


def test_extract_skill_block_last_block_wins():
    text = "说明\n```markdown\n# 旧\n```\n再改一版\n```markdown\n# 新 Skill\n\n> 调用规则：x\n```\n"
    out = pr._extract_skill_block(text)
    assert out is not None and "# 新 Skill" in out


def test_extract_skill_block_nested_fence_keeps_full_doc():
    """文档内部有 ``` 示例围栏：必须取完整章节，不能截成“前言+组装导出”。"""
    doc = (
        "说明。\n```markdown\n---\nname: 甲\ndescription: 乙\n---\n"
        "## 制作流程\n流程\n\n"
        "## 提示词写法\n模板：\n```text\n主体：{人物}\n```\n\n"
        "## 组装导出\n导出\n```"
    )
    out = pr._extract_skill_block(doc)
    assert out is not None
    assert out.startswith("---")
    assert "## 制作流程" in out and "## 组装导出" in out
    assert "主体：{人物}" in out


def test_extract_skill_block_nested_fence_in_last_section():
    """最后一个章节内部再开示例围栏：也要扩到全文。"""
    doc = (
        "```markdown\n---\nname: 甲\ndescription: 乙\n---\n"
        "## 制作流程\n流程\n\n"
        "## 组装导出\n导出前模板：\n```text\n先对齐音画\n```\n```"
    )
    out = pr._extract_skill_block(doc)
    assert out is not None
    assert "## 组装导出" in out
    assert "先对齐音画" in out


def test_extract_skill_block_sentinel():
    """哨兵定界：文档内部围栏再多也不影响边界。"""
    text = (
        "已补暂停点。\n<<<SKILL_DOC>>>\n"
        "---\nname: 甲\ndescription: 乙\n---\n## 制作流程\n流程\n"
        "<<<END_SKILL_DOC>>>\n"
    )
    assert pr._extract_skill_block(text) == (
        "---\nname: 甲\ndescription: 乙\n---\n## 制作流程\n流程"
    )


def test_extract_skill_block_sentinel_wrapped_in_fence():
    """模型仍给整篇包围栏：哨兵内容照取，聊天说明不残留围栏行。"""
    from src.video_agent.web.skill_doc_stream import extract_skill_doc

    text = (
        "说明\n```markdown\n<<<SKILL_DOC>>>\n"
        "---\nname: 甲\ndescription: 乙\n---\n## 制作流程\n流程\n<<<END_SKILL_DOC>>>\n```"
    )
    chat, doc, source = extract_skill_doc(text)
    assert source == "sentinel"
    assert doc == "---\nname: 甲\ndescription: 乙\n---\n## 制作流程\n流程"
    assert chat == "说明"


def test_extract_skill_block_no_block():
    assert pr._extract_skill_block("普通回复，没有代码块") is None


def test_extract_skill_block_block_without_title():
    assert pr._extract_skill_block("```markdown\n纯散文\n```") is None


def test_extract_skill_block_bare_heading_doc():
    """模型没套代码块、直接输出标题式全文：从 `# ` 标题起提取。"""
    text = (
        "这版补了暂停点。\n\n"
        "# 标题式 Skill\n\n"
        "## 制作流程\n第一步分析素材。\n\n"
        "## 组装导出\n导出成片。"
    )
    out = pr._extract_skill_block(text)
    assert out is not None
    assert out.startswith("# 标题式 Skill")
    assert "## 制作流程" in out


def test_extract_skill_block_unclosed_fence():
    """输出被截断/漏写结尾围栏：仍取到文末，不白丢整轮产出。"""
    text = "已优化。\n```markdown\n# 新 Skill\n\n> 调用规则：x\n"
    out = pr._extract_skill_block(text)
    assert out is not None and "# 新 Skill" in out


def test_extract_skill_block_bare_with_frontmatter():
    text = (
        "说明。\n---\nname: 甲\ndescription: 乙\n---\n"
        "# 甲\n\n## 制作流程\n步骤。\n"
    )
    out = pr._extract_skill_block(text)
    assert out is not None
    assert out.startswith("---")
    assert "## 制作流程" in out


def test_extract_skill_block_plain_reply_none():
    assert pr._extract_skill_block("这版没有改动，因为你的要求不明确。") is None


def test_display_reply_strips_bare_doc():
    """裸文档进预览后，聊天区只留说明 + 完成摘要（不重复贴整篇）。"""
    doc = "# 标题\n\n## 制作流程\n步骤"
    text = "补了暂停点。\n\n" + doc
    reply = pr._display_reply(text, True, doc)
    assert reply.startswith("补了暂停点。")
    assert "预览已更新" in reply
    assert "## 制作流程" not in reply


def test_route_returns_content(client, monkeypatch):
    fake = _FakeAdapter("已优化。\n```markdown\n# 探针 Skill\n\n> 调用规则：x\n```")
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: fake)
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "改标题"}],
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["content"] and "# 探针 Skill" in data["content"]
    assert "已优化" in data["reply"]
    assert "预览已更新" in data["reply"]
    # 走 BaseChatAdapter.chat（generate 是媒体适配器接口，chat 适配器没有）：
    # 首两条 = system + 当前全文；其后为用户历史
    assert fake.calls and fake.calls[0][0]["role"] == "system"
    assert "当前 Skill 文档全文" in fake.calls[0][1]["content"]
    assert fake.calls[0][-1] == {"role": "user", "content": "改标题"}
    # 思考开关/推理档位交给模型 meta 链（chat_models_meta）
    assert fake.kwargs[0].get("thinking_level") == ""


def test_format_prompt_is_generic_heading_format():
    """整理接口的 system prompt 不得再教模型输出旧标签块。"""
    assert "<planner>" not in pr._FORMAT_SYSTEM
    assert "## 三、制作流程" in pr._FORMAT_SYSTEM
    assert "references/" in pr._FORMAT_SYSTEM


def test_format_route_uses_chat_adapter(client, monkeypatch):
    """整理接口同走 chat：此前误调媒体接口 generate，模型调用永远失败。"""
    fake = _FakeAdapter("# 整理后\n\n> 调用规则：测试")
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: fake)
    resp = client.post("/api/skills/format", json={"content": "随手记的流程"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"].startswith("# 整理后")
    assert fake.calls[0][1] == {"role": "user", "content": "随手记的流程"}


def test_format_route_no_provider_returns_original(client, monkeypatch):
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: None)
    resp = client.post("/api/skills/format", json={"content": "原文"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "原文"


def test_route_no_block_content_null(client, monkeypatch):
    monkeypatch.setattr(
        pr, "_resolve_chat_adapter",
        lambda provider, model: _FakeAdapter("你的请求不明确，保持原文。"),
    )
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "嗯"}],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"] is None


def test_route_llm_failure_content_null(client, monkeypatch):
    monkeypatch.setattr(
        pr, "_resolve_chat_adapter",
        lambda provider, model: _BoomAdapter(),
    )
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "改"}],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"] is None


def test_route_empty_body_400(client):
    resp = client.post("/api/skills/assistant", json={"content": "", "messages": []})
    assert resp.status_code == 400


# ---------- 2026-10-26 用户裁决：文档不写具体工具名 ----------

def test_assistant_system_has_no_tool_names():
    """助手提示词只要求自然语言流程，不再注入工具清单/工具名白名单。"""
    text = pr._assistant_system()
    for name in (
        "todo_write", "run_subagent", "read_analysis", "script_analysis_report",
        "storyboard_create_group", "storyboard_add_draft", "document_write",
        "canvas_list", "canvas_read_nodes", "read_project_doc",
        "canvas_list_assets", "web_search", "workflow_pause",
    ):
        assert name not in text, f"工具名 {name} 不应进助手提示词"
    assert "工具名" in text and "自然语言" in text
    assert "字段表" in text and "代码块" in text and "散文" in text


# ---------- SSE 流式端点（思考/正文实时下发） ----------

def _frames(body: str):
    """拆 data: 帧为 dict（忽略空行/非 data 行）。"""
    return [json.loads(line[len("data: "):]) for line in body.splitlines()
            if line.startswith("data: ")]


class _FakeStreamAdapter:
    """流式桩：按脚本产出增量；chat 供创作模式自修复分支。"""

    def __init__(self, chunks, repair_text: str = ""):
        self._chunks = chunks
        self._repair_text = repair_text
        self.chat_calls = 0
        self.stream_calls = 0
        self.stream_kwargs = []

    async def chat_stream(self, messages, temperature=0.3, **kwargs):  # noqa: ARG002
        self.stream_calls += 1
        self.stream_kwargs.append(kwargs)
        for chunk in self._chunks:
            yield chunk

    async def chat(self, messages, temperature=0.3, **kwargs):  # noqa: ARG002
        self.chat_calls += 1
        return _FakeResult(self._repair_text)


class _BoomStreamAdapter:
    async def chat_stream(self, messages, temperature=0.3, **kwargs):  # noqa: ARG002
        yield StreamChunk(type="text_delta", text="部分输出")
        raise RuntimeError("boom")


def test_stream_route_reasoning_then_done(client, monkeypatch):
    """思考增量先于正文；文档正文走 doc_delta，done 帧携带解析后的全文与自检结果。"""
    fake = _FakeStreamAdapter([
        StreamChunk(type="reasoning_delta", text="先看结构"),
        StreamChunk(type="text_delta", text="已优化。\n"),
        StreamChunk(
            type="text_delta",
            text="```markdown\n# 探针 Skill\n\n> 调用规则：x\n```",
        ),
    ])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: fake)
    resp = client.post("/api/skills/assistant/stream", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "改标题"}],
    })
    assert resp.status_code == 200, resp.text
    frames = _frames(resp.text)
    assert frames[0] == {"type": "reasoning_delta", "text": "先看结构"}
    types = [f["type"] for f in frames[:-1]]
    assert types == ["reasoning_delta", "delta", "doc_delta"]
    assert "已优化" in frames[1]["text"]
    assert "# 探针 Skill" in frames[2]["text"]
    done = frames[-1]
    assert done["type"] == "done"
    assert "# 探针 Skill" in done["content"]
    assert done["reply"].startswith("已优化。")
    assert "预览已更新" in done["reply"]
    assert done["checks"] is not None
    # 非流式/流式共用同一消息组装口径（system + 当前全文 + 历史）
    assert fake.stream_calls == 1
    # 思考开关/推理档位交给模型 meta 链（chat_models_meta）
    assert fake.stream_kwargs[0].get("thinking_level") == ""


def test_stream_route_create_mode_repairs(client, monkeypatch):
    """创作模式：首版自检有问 → status 帧 + 一次自修复；done 取问题更少的一版。"""
    fake = _FakeStreamAdapter(
        [StreamChunk(type="text_delta", text="初稿\n```markdown\n# 新 Skill\n```")],
        repair_text="修好了。\n```markdown\n# 修复版 Skill\n```",
    )
    calls = {"n": 0}

    def fake_validate(content, *, create_mode):  # noqa: ARG001
        calls["n"] += 1
        return ["缺少章节"] if calls["n"] == 1 else []

    monkeypatch.setattr(pr, "validate_skill_draft", fake_validate)
    monkeypatch.setattr(
        pr, "repair_messages", lambda base, content, issues: base,
    )
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: fake)
    resp = client.post("/api/skills/assistant/stream", json={
        "content": "", "messages": [{"role": "user", "content": "做个新技能"}],
        "mode": "create",
    })
    assert resp.status_code == 200, resp.text
    frames = _frames(resp.text)
    assert any(f["type"] == "status" for f in frames)
    done = frames[-1]
    assert done["type"] == "done"
    assert "# 修复版 Skill" in done["content"]
    assert done["reply"].startswith("修好了。")
    assert done["checks"] == {"passed": True, "issues": []}
    assert fake.chat_calls == 1


def test_stream_route_sentinel_doc_frames(client, monkeypatch):
    """哨兵路径：说明进 delta，文档进 doc_delta（聊天区不重复贴全文）。"""
    fake = _FakeStreamAdapter([
        StreamChunk(type="text_delta", text="已生成。\n"),
        StreamChunk(
            type="text_delta",
            text=(
                "<<<SKILL_DOC>>>\n---\nname: 甲\ndescription: 乙\n---\n"
                "## 制作流程\n流程\n<<<END_SKILL_DOC>>>"
            ),
        ),
    ])
    monkeypatch.setattr(pr, "_resolve_chat_adapter", lambda provider, model: fake)
    resp = client.post("/api/skills/assistant/stream", json={
        "content": "", "messages": [{"role": "user", "content": "做个技能"}],
        "mode": "create",
    })
    assert resp.status_code == 200, resp.text
    frames = _frames(resp.text)
    chat_text = "".join(f["text"] for f in frames if f["type"] == "delta")
    doc_text = "".join(f["text"] for f in frames if f["type"] == "doc_delta")
    assert "<<<SKILL_DOC>>>" not in chat_text
    assert "## 制作流程" not in chat_text
    assert "## 制作流程" in doc_text
    assert "<<<END_SKILL_DOC>>>" not in doc_text
    done = frames[-1]
    assert done["type"] == "done"
    assert done["content"].startswith("---")
    assert "自检" in done["reply"] or "预览已更新" in done["reply"]


def test_stream_route_llm_failure_emits_error(client, monkeypatch):
    monkeypatch.setattr(
        pr, "_resolve_chat_adapter", lambda provider, model: _BoomStreamAdapter(),
    )
    resp = client.post("/api/skills/assistant/stream", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "改"}],
    })
    assert resp.status_code == 200, resp.text
    frames = _frames(resp.text)
    assert frames[-1]["type"] == "error"
    assert "boom" in frames[-1]["message"]
    assert all(f["type"] != "done" for f in frames)


def test_stream_route_empty_body_400(client):
    resp = client.post(
        "/api/skills/assistant/stream", json={"content": "", "messages": []},
    )
    assert resp.status_code == 400
