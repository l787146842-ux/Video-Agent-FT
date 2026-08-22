"""
记忆向量存储 split-brain 一致性测试（任务 #25）

覆盖：
- 降级导出成功 / 失败两分支（mock Chroma 故障注入）
- 初始化即失败直接降级
- 降级期双写（新写入落 JSON 兜底库）
- 恢复对账回灌（JSON 有而 Chroma 无的差集回灌）与对账失败不半恢复
- 告警触发（loguru warning 显式告警 + live_metrics 计数）
- 检索路径节流自动恢复
"""
import json
import tempfile
from pathlib import Path

import pytest
from loguru import logger

from src.video_agent.core.live_metrics import get_degradations, reset_degradations
from src.video_agent.memory.models import MemoryRecord
from src.video_agent.memory.vector_store import VectorStore


class FakeChromaCol:
    """内存版 Chroma 集合替身，支持按操作名注入故障"""

    def __init__(self):
        self.docs = {}   # id -> content
        self.metas = {}  # id -> metadata
        self.fail = {}   # op name -> Exception（注入故障）

    def _check(self, op):
        if op in self.fail:
            raise self.fail[op]

    def add(self, ids, documents, metadatas):
        self._check("add")
        for i, rid in enumerate(ids):
            self.docs[rid] = documents[i]
            self.metas[rid] = metadatas[i]

    def get(self, ids=None, include=None):
        self._check("get")
        if ids is not None:
            found = [rid for rid in ids if rid in self.docs]
            return {"ids": found, "metadatas": [self.metas[r] for r in found]}
        return {
            "ids": list(self.docs),
            "documents": [self.docs[r] for r in self.docs],
            "metadatas": [self.metas[r] for r in self.docs],
        }

    def query(self, query_texts, n_results):
        self._check("query")
        ids = list(self.docs)[:n_results]
        return {
            "ids": [ids],
            "documents": [[self.docs[r] for r in ids]],
            "metadatas": [[self.metas[r] for r in ids]],
            "distances": [[0.5] * len(ids)],
        }

    def update(self, ids, metadatas):
        self._check("update")
        for i, rid in enumerate(ids):
            self.metas[rid] = metadatas[i]

    def delete(self, ids):
        self._check("delete")
        for rid in ids:
            self.docs.pop(rid, None)
            self.metas.pop(rid, None)

    def count(self):
        self._check("count")
        return len(self.docs)


def _meta(content=""):
    return {"kind": "summary", "source": "", "created_at": 1.0,
            "project_id": "", "pinned": False}


@pytest.fixture()
def mem_dir():
    """自管理临时目录（规避 pytest 9.x + Win 的 tmp_path 符号链接清理 bug）"""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(autouse=True)
def clean_metrics():
    reset_degradations()
    yield
    reset_degradations()


@pytest.fixture()
def log_capture():
    """捕获 warning 级日志（告警口径断言用）"""
    messages = []
    sink_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
    yield messages
    logger.remove(sink_id)


def make_store(mem_dir, monkeypatch, col):
    """以 FakeChromaCol 为后端的 chromadb 模式存储"""
    monkeypatch.setattr(
        VectorStore, "_try_init_chroma", staticmethod(lambda path: col))
    return VectorStore(mem_dir, backend="chromadb")


def _deg_count(point: str) -> int:
    return sum(d["count"] for d in get_degradations() if d["point"] == point)


def _fallback_ids(mem_dir: Path) -> set:
    raw = json.loads((mem_dir / "fallback.json").read_text(encoding="utf-8"))
    return {r["id"] for r in raw["records"]}


# ---------- 降级导出两分支 ----------

def test_degrade_export_success(mem_dir, monkeypatch, log_capture):
    """运行期故障：导出成功才降级，Chroma 存量随降级进入 JSON 兜底库"""
    col = FakeChromaCol()
    col.add(["m1", "m2"], ["记忆甲", "记忆乙"], [_meta(), _meta()])
    store = make_store(mem_dir, monkeypatch, col)
    assert store.using_chromadb

    col.fail["add"] = RuntimeError("chroma down")
    store.add(MemoryRecord(id="m3", content="新记忆"))

    assert store.degraded and not store.using_chromadb and store.dual_write
    # 导出的存量 + 降级期新写入全部落兜底库
    assert _fallback_ids(mem_dir) == {"m1", "m2", "m3"}
    assert _deg_count("vector_store.degrade") == 1
    assert _deg_count("vector_store.export_failed") == 0
    assert any("导出" in m and "2 条" in m for m in log_capture)


def test_degrade_export_failure_data_gap(mem_dir, monkeypatch, log_capture):
    """导出失败分支：降级 + 显式告警数据缺口，live_metrics 独立计数"""
    col = FakeChromaCol()
    col.add(["m1", "m2"], ["记忆甲", "记忆乙"], [_meta(), _meta()])
    store = make_store(mem_dir, monkeypatch, col)

    col.fail["add"] = RuntimeError("write broken")
    col.fail["get"] = RuntimeError("read broken")
    store.add(MemoryRecord(id="m3", content="新记忆"))

    assert store.degraded
    # 只有新写入落了兜底库，Chroma 存量不可达（数据缺口）
    assert _fallback_ids(mem_dir) == {"m3"}
    assert _deg_count("vector_store.degrade") == 1
    assert _deg_count("vector_store.export_failed") == 1
    assert any("数据缺口" in m for m in log_capture)


def test_init_failure_direct_degrade(mem_dir, monkeypatch, log_capture):
    """初始化即失败：无存量可导出，直接降级且不报错"""
    monkeypatch.setattr(
        VectorStore, "_try_init_chroma", staticmethod(lambda path: None))
    store = VectorStore(mem_dir, backend="chromadb")
    assert store.degraded and not store.using_chromadb
    store.add(MemoryRecord(id="m1", content="初始化失败后的记忆"))
    assert store.count() == 1
    assert _fallback_ids(mem_dir) == {"m1"}
    # 初始化失败属环境预期降级：只告警不计 live_metrics（watchdog 口径为意外降级）
    assert _deg_count("vector_store.degrade") == 0
    assert any("初始化失败" in m for m in log_capture)


# ---------- 降级期双写 ----------

def test_degraded_dual_write_persists(mem_dir, monkeypatch):
    """降级期每条新写入同时落 JSON 兜底库（重新加载仍可见）"""
    col = FakeChromaCol()
    store = make_store(mem_dir, monkeypatch, col)
    col.fail["add"] = RuntimeError("chroma down")
    store.add(MemoryRecord(id="m1", content="降级期写入一"))

    store.add(MemoryRecord(id="m2", content="降级期写入二"))
    store.add(MemoryRecord(id="m3", content="降级期写入三"))

    # 以纯 JSON 后端重新加载兜底文件验证持久化
    store2 = VectorStore(mem_dir, backend="json")
    assert {r.id for r in store2.all_records()} == {"m1", "m2", "m3"}
    # 降级期语义检索诚实返回 None（走关键词路径）
    assert store.search_semantic("任意查询", 3) is None


# ---------- 恢复对账 ----------

def test_recover_reconcile_backfill(mem_dir, monkeypatch):
    """恢复对账：JSON 有而 Chroma 无的差集回灌，回灌后退出双写"""
    col = FakeChromaCol()
    col.add(["m1", "m2"], ["记忆甲", "记忆乙"], [_meta(), _meta()])
    store = make_store(mem_dir, monkeypatch, col)
    col.fail["add"] = RuntimeError("chroma down")
    store.add(MemoryRecord(id="m3", content="降级期写入"))
    assert store.degraded

    # Chroma 恢复（模拟重启后存量丢失的空集合）
    fresh_col = FakeChromaCol()
    monkeypatch.setattr(
        VectorStore, "_try_init_chroma", staticmethod(lambda path: fresh_col))
    assert store.try_recover() is True

    # 差集全量回灌
    assert set(fresh_col.docs) == {"m1", "m2", "m3"}
    assert store.degraded is False and store.dual_write is False
    assert store.last_reconcile["backfilled"] == 3
    assert store.last_reconcile["json_total"] == 3
    # 恢复后退出双写：新写入只进 Chroma
    store.add(MemoryRecord(id="m4", content="恢复后写入"))
    assert "m4" in fresh_col.docs and store.using_chromadb


def test_recover_no_diff_noop(mem_dir, monkeypatch):
    """恢复但无差集：Chroma 存量完好时回灌 0 条也正常退出双写"""
    col = FakeChromaCol()
    col.add(["m1"], ["记忆甲"], [_meta()])
    store = make_store(mem_dir, monkeypatch, col)
    col.fail["query"] = RuntimeError("query broken")
    assert store.search_semantic("x", 3) is None  # 查询故障触发降级（导出成功）
    assert store.degraded

    col.fail.pop("query")
    store._last_recover_attempt = 0.0  # 跳过节流窗口
    assert store.search_semantic("x", 3) is not None  # 节流到期自动恢复
    assert store.degraded is False
    assert store.last_reconcile["backfilled"] == 0
    assert store.last_reconcile["chroma_existing"] == 1


def test_recover_reconcile_failure_stays_degraded(mem_dir, monkeypatch, log_capture):
    """对账回灌失败不半恢复：整体退回降级态并告警计数"""
    col = FakeChromaCol()
    col.add(["m1"], ["记忆甲"], [_meta()])
    store = make_store(mem_dir, monkeypatch, col)
    col.fail["add"] = RuntimeError("chroma down")
    store.add(MemoryRecord(id="m2", content="降级期写入"))

    bad_col = FakeChromaCol()
    bad_col.fail["add"] = RuntimeError("read-only replica")
    monkeypatch.setattr(
        VectorStore, "_try_init_chroma", staticmethod(lambda path: bad_col))
    reset_degradations()  # 清零降级触发阶段的计数，单独度量本次对账
    assert store.try_recover() is False

    assert store.degraded and store.dual_write
    assert not bad_col.docs  # 半恢复被拒绝
    assert _deg_count("vector_store.reconcile_failed") == 1
    assert any("对账回灌失败" in m for m in log_capture)


def test_auto_recover_throttled_on_search(mem_dir, monkeypatch):
    """检索路径自动恢复带节流：窗口内不重连，窗口到期后恢复"""
    col = FakeChromaCol()
    col.add(["m1"], ["记忆甲"], [_meta()])
    store = make_store(mem_dir, monkeypatch, col)
    col.fail["query"] = RuntimeError("query broken")
    assert store.search_semantic("x", 3) is None
    assert store.degraded

    col.fail.pop("query")
    # 节流窗口内：不尝试重连，仍处降级
    assert store.search_semantic("x", 3) is None
    assert store.degraded
    # 窗口到期：自动恢复并恢复语义检索
    store._last_recover_attempt = 0.0
    assert store.search_semantic("x", 3) is not None
    assert store.degraded is False
