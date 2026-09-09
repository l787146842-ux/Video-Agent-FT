"""质量守护改进回归测试（token 治理副作用修复）。

覆盖：
- ① read_uploaded_doc / read_project_doc 分段续读（超长文档不再丢尾部）
（③ 旧轮回喂惰性压缩已随 v4 批 E3 退役：会话事件流 + 修剪器/阈值压缩
  覆盖其职责，退役记录见 CHANGELOG 2026-09-09 批 E3）
"""
import pytest

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
