"""
Agent 混合记忆系统测试

覆盖：
- 关键词评分 / 时间衰减 / 混合排序
- 向量存储 JSON 降级读写
- 摘要间隔触发与降级摘要
- build_context 模板渲染
"""
import tempfile
import time
from pathlib import Path

import pytest

from src.video_agent.memory.manager import MemoryManager
from src.video_agent.memory.models import MemoryRecord
from src.video_agent.memory.retriever import (
    hybrid_rank, keyword_score, time_decay, tokenize,
)
from src.video_agent.memory.summarizer import fallback_summary, summarize_dialog
from src.video_agent.memory.vector_store import VectorStore


@pytest.fixture()
def mem_dir():
    """自管理临时目录（规避 pytest 9.x + Win 的 mem_dir 符号链接清理 bug）"""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ---------- 分词与关键词 ----------

def test_tokenize_mixed():
    tokens = tokenize("制作 Cinematic 风格的科幻短片")
    assert "cinematic" in tokens
    assert "科幻" in tokens  # 中文按 bigram（P3-14：单字切分退役）


def test_keyword_score_overlap():
    rec = MemoryRecord(content="用户偏好赛博朋克风格的夜景", keywords=["赛博朋克"])
    high = keyword_score("赛博朋克夜景怎么拍", rec)
    low = keyword_score("今天天气如何", rec)
    assert high > 0
    assert low == 0


def test_keyword_score_empty():
    rec = MemoryRecord(content="")
    assert keyword_score("任意查询", rec) == 0.0


# ---------- 时间衰减 ----------

def test_time_decay_half_life():
    now = time.time()
    assert time_decay(now, now, 30) == pytest.approx(1.0)
    assert time_decay(now - 30 * 86400, now, 30) == pytest.approx(0.5)
    assert time_decay(now - 60 * 86400, now, 30) == pytest.approx(0.25)


def test_time_decay_zero_half_life():
    assert time_decay(0, time.time(), 0) == 1.0


# ---------- 混合排序 ----------

def test_hybrid_rank_keyword_path():
    now = time.time()
    rec_rel = MemoryRecord(content="赛博朋克风格", created_at=now - 60 * 86400)
    rec_new = MemoryRecord(content="完全不相关的内容", created_at=now)
    ranked = hybrid_rank([rec_rel, rec_new], "赛博朋克", half_life_days=30, now=now)
    assert ranked and ranked[0].id == rec_rel.id
    # 无关记录 relevance=0 被过滤
    assert all(r.id != rec_new.id for r in ranked)


def test_hybrid_rank_semantic_scores():
    now = time.time()
    r1 = MemoryRecord(content="甲", created_at=now)
    r2 = MemoryRecord(content="乙", created_at=now)
    ranked = hybrid_rank(
        [r1, r2], "查询",
        semantic_scores={r1.id: 0.9, r2.id: 0.1},
        now=now, top_k=1,
    )
    assert len(ranked) == 1
    assert ranked[0].id == r1.id
    assert ranked[0].score > 0


# ---------- 向量存储（JSON 降级） ----------

def test_vector_store_json_fallback(mem_dir):
    store = VectorStore(mem_dir, backend="json")
    assert not store.using_chromadb
    rec = MemoryRecord(content="测试记忆内容", source="测试")
    store.add(rec)
    assert store.count() == 1
    assert store.search_semantic("查询", 5) is None

    # 重新加载（持久化生效）
    store2 = VectorStore(mem_dir, backend="json")
    assert store2.count() == 1
    assert store2.all_records()[0].content == "测试记忆内容"


# ---------- 摘要 ----------

def test_fallback_summary_truncation():
    text = fallback_summary("做一个科幻短片" * 20, "好的，我来拆解" * 20)
    assert "用户要求" in text
    assert len(text) < 300


@pytest.mark.asyncio
async def test_summarize_dialog_with_llm():
    async def fake_llm(prompt: str) -> str:
        return "用户想做赛博朋克风格短片"
    result = await summarize_dialog("做短片", "好的", fake_llm)
    assert result == "用户想做赛博朋克风格短片"


@pytest.mark.asyncio
async def test_summarize_dialog_llm_failure_fallback():
    async def bad_llm(prompt: str) -> str:
        raise RuntimeError("LLM down")
    result = await summarize_dialog("做短片", "好的", bad_llm)
    assert "用户要求" in result


# ---------- MemoryManager ----------

@pytest.mark.asyncio
async def test_record_dialog_interval(mem_dir):
    mgr = MemoryManager(persist_dir=mem_dir, backend="json", summary_interval=2)
    r1 = await mgr.record_dialog("第一轮对话", "回复一")
    assert r1 is None  # 未达间隔
    r2 = await mgr.record_dialog("第二轮对话", "回复二")
    assert r2 is not None
    assert mgr.count() == 1
    assert mgr.backend_name == "json"


@pytest.mark.asyncio
async def test_build_context_renders(mem_dir):
    mgr = MemoryManager(persist_dir=mem_dir, backend="json", summary_interval=1)
    await mgr.record_dialog("我要做赛博朋克风格的短片", "好的，已为你规划")
    ctx = mgr.build_context("赛博朋克短片继续")
    assert "历史记忆" in ctx
    assert "赛博朋克" in ctx


def test_build_context_empty_query(mem_dir):
    mgr = MemoryManager(persist_dir=mem_dir, backend="json", summary_interval=1)
    assert mgr.build_context("") == ""
    assert mgr.build_context("   ") == ""


# ---------- 4.7：写入去重 / 命中可视化 / 管理 API 底座 ----------

@pytest.mark.asyncio
async def test_record_dialog_dedup_skips_similar_summary(mem_dir):
    """写入去重：与已有记忆关键词高度重叠的摘要不再重复堆积"""
    mgr = MemoryManager(persist_dir=mem_dir, backend="json", summary_interval=1)
    r1 = await mgr.record_dialog("我要做赛博朋克风格的短片", "好的")
    assert r1 is not None
    assert mgr.count() == 1
    # 同类对话再次触发几乎相同的摘要 → 被去重跳过
    r2 = await mgr.record_dialog("我要做赛博朋克风格的短片", "好的，已为你规划")
    assert r2 is None
    assert mgr.count() == 1


@pytest.mark.asyncio
async def test_build_context_with_hits_returns_hit_details(mem_dir):
    """命中可视化：检索结果同时返回注入块与命中明细"""
    mgr = MemoryManager(persist_dir=mem_dir, backend="json", summary_interval=1)
    await mgr.record_dialog("我要做赛博朋克风格的短片", "好的")
    ctx, hits = mgr.build_context_with_hits("赛博朋克短片继续")
    assert "赛博朋克" in ctx
    assert hits and "content" in hits[0] and "date" in hits[0]
    # 无命中时两者均为空
    ctx2, hits2 = mgr.build_context_with_hits("")
    assert ctx2 == "" and hits2 == []


@pytest.mark.asyncio
async def test_list_and_delete_records(mem_dir):
    """管理底座：清单按项目过滤 + 删除（不存在返回 False）"""
    mgr = MemoryManager(persist_dir=mem_dir, backend="json", summary_interval=1)
    await mgr.record_dialog("项目甲的对话", "回复", project_id="proj-a")
    await mgr.record_dialog("项目乙完全不相关的对话", "回复", project_id="proj-b")
    assert len(mgr.list_records()) == 2
    only_a = mgr.list_records(project_id="proj-a")
    assert len(only_a) == 1 and only_a[0].project_id == "proj-a"
    assert mgr.delete_record(only_a[0].id) is True
    assert mgr.delete_record("mem-not-exist") is False
    assert len(mgr.list_records()) == 1


@pytest.mark.asyncio
async def test_pin_record_orders_first(mem_dir):
    """置顶（M4）：置顶记忆永远排在清单最前，不存在返回 False"""
    mgr = MemoryManager(persist_dir=mem_dir, backend="json", summary_interval=1)
    r1 = await mgr.record_dialog("项目甲的对话内容", "回复", project_id="proj-a")
    r2 = await mgr.record_dialog("项目乙完全不同的对话", "回复", project_id="proj-b")
    assert r1 is not None and r2 is not None
    # 置顶较早的 r1 → 排到最新写入的 r2 前面
    assert mgr.pin_record(r1.id, True) is True
    ordered = mgr.list_records()
    assert ordered[0].id == r1.id and ordered[0].pinned is True
    # 取消置顶 → 恢复时间序（r2 更新在前）
    assert mgr.pin_record(r1.id, False) is True
    assert mgr.list_records()[0].id == r2.id
    assert mgr.pin_record("mem-not-exist", True) is False
