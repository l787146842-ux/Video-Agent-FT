"""质量守护改进回归测试（token 治理副作用修复）。

覆盖：
- ① read_uploaded_doc / read_project_doc 分段续读（超长文档不再丢尾部）
- ③ 旧轮 read_* 回喂惰性压缩（短对话保全文，逼近预算才压缩）
"""
import pytest

from src.video_agent.core.fc_tool_runner import (
    FEEDBACK_COMPRESSED,
    FEEDBACK_MARKER,
    compress_prior_feedback,
    should_compress_feedback,
)
from src.video_agent.core.planner import Planner
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.document_tools import (
    ReadProjectDocInput,
    ReadProjectDocTool,
    ReadUploadedDocInput,
    ReadUploadedDocTool,
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


# ---------- ① 分段续读 ----------

class TestChunkedReadUploadedDoc:
    async def test_long_doc_readable_in_chunks(self, svc):
        """超过 max_doc_chars(30000) 的文档：首段给续读指引，传 start 取尾部"""
        full = "A" * 30000 + "B" * 10000  # 40000 字 > 上限
        svc.state_dict["uploadedDocs"] = [
            {"id": "d1", "name": "长剧本.md", "content": full, "char_count": 40000},
        ]
        tool = ReadUploadedDocTool()
        # 第一段：前 30000 字 + 续读指引
        r1 = await tool.aexecute(ReadUploadedDocInput(name="长剧本.md"))
        assert r1.success
        assert r1.data["content"].startswith("A" * 100)
        assert "start=30000" in r1.data["content"]
        assert "B" * 10 not in r1.data["content"]
        # 第二段：拿到尾部内容，不再丢结尾
        r2 = await tool.aexecute(ReadUploadedDocInput(name="长剧本.md", start=30000))
        assert r2.success
        assert "B" * 100 in r2.data["content"]
        assert "start=" not in r2.data["content"]
        # 读完后再读：明确报错而不是静默返回空
        r3 = await tool.aexecute(ReadUploadedDocInput(name="长剧本.md", start=40000))
        assert not r3.success and "已读完" in r3.error

    async def test_short_doc_unchanged(self, svc):
        """上限内的文档行为不变：全文返回、无续读提示"""
        svc.state_dict["uploadedDocs"] = [
            {"id": "d2", "name": "短故事.md", "content": "短文全文", "char_count": 4},
        ]
        tool = ReadUploadedDocTool()
        r = await tool.aexecute(ReadUploadedDocInput(name="短故事.md"))
        assert r.success and r.data["content"] == "短文全文"


class TestChunkedReadProjectDoc:
    async def test_project_doc_chunked(self, svc):
        full = "C" * 30000 + "D" * 5000
        svc.state_dict["documents"] = [
            {"id": "doc1", "name": "Final_Video_Spec.md", "content": full,
             "updated_at": "2026-08-04T00:00:00Z"},
        ]
        tool = ReadProjectDocTool()
        r1 = await tool.aexecute(ReadProjectDocInput(name="Final_Video_Spec.md"))
        assert r1.success and "start=30000" in r1.data["content"]
        r2 = await tool.aexecute(ReadProjectDocInput(name="Final_Video_Spec.md", start=30000))
        assert r2.success and "D" * 100 in r2.data["content"]


# ---------- ③ 惰性压缩决策 ----------

class TestLazyFeedbackCompression:
    def test_small_conversation_keeps_full_text(self):
        """短对话远未达预算：不压缩，保质量"""
        msgs = [{"role": "user", "content": "短消息"}]
        assert should_compress_feedback(msgs) is False

    def test_huge_conversation_triggers_compression(self):
        """逼近 token 预算（默认预算 128000*0.8 的 50% ≈ 51200 token）：触发压缩"""
        msgs = [{"role": "user", "content": "x" * 600000}]  # tiktoken≈75000/启发式≈150000 token，双估算器都超阈
        assert should_compress_feedback(msgs) is True

    def test_compression_still_works_when_triggered(self):
        """触发压缩后旧轮全文确实被替换为占位"""
        msgs = [
            {"role": "user", "content": FEEDBACK_MARKER + "\n- read_skill：三万字全文"},
        ]
        compress_prior_feedback(msgs)
        assert msgs[0]["content"] == FEEDBACK_COMPRESSED
