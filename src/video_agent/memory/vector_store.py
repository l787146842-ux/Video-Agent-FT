"""
向量存储：ChromaDB 优先，未安装/初始化失败时降级为 JSON 文件 + 关键词检索。

降级策略保证记忆系统在任何环境可用（Rule: 诚实降级，不伪造语义检索结果）。

split-brain 一致性状态机（任务 #25）：
- 状态：chroma（正常）⇄ degraded（JSON 兜底 + 双写）
- chroma→degraded：任一 Chroma 运行期故障先执行一次性 Chroma→JSON 导出，
  导出成功才视为数据可达地降级；导出失败则降级并显式告警数据缺口。
  初始化即失败时无存量可导出，直接降级。
- 降级期双写：新写入同时落 JSON 兜底库（内存字典 + 持久化文件），
  并在写入/检索时惰性尝试恢复。
- degraded→chroma：try_recover() 重连成功后对账——JSON 有而 Chroma 无的
  记录回灌 Chroma，记录对账结果后退出双写。
- 可观测：所有 split-brain 相关事件除 live_metrics 计数外，另发 loguru
  warning 级显式告警（含缺失条数 / 导出失败原因）。
"""
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.core.live_metrics import record_degradation
from src.video_agent.memory.models import MemoryRecord

# 降级期检索路径的自动恢复重试间隔（秒）：防 Chroma 持续故障时每次检索都重连
_RECOVER_RETRY_INTERVAL = 30.0


class VectorStore:
    """记忆向量存储（双后端 + split-brain 一致性状态机）"""

    def __init__(self, persist_dir: Path, backend: str = "chromadb"):
        self._dir = persist_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fallback_path = self._dir / "fallback.json"
        self._backend = backend
        self._records: Dict[str, MemoryRecord] = {}
        self._col = None
        # split-brain 状态机：降级中标记 + 降级期双写标记
        self._degraded = False
        self._dual_write = False
        self._last_recover_attempt = 0.0
        # 最近一次恢复对账结果（观测/测试用）：backfilled/chroma_existing/ts
        self.last_reconcile: Optional[Dict] = None

        if backend == "chromadb":
            self._col = self._try_init_chroma(self._dir / "vectors")
            if self._col is None:
                # 初始化即失败：客户端都建不起来，无存量可导出，直接降级。
                # 属环境决定的预期降级（此前无任何可达存储，无 split-brain 风险），
                # 只发显式告警不计 record_degradation（watchdog 口径为意外降级）
                self._degraded = True
                self._dual_write = True
                gap = ""
                if not self._fallback_path.exists() and (self._dir / "vectors").exists():
                    gap = "；Chroma 磁盘目录已存在但兜底库为空，若其中有存量则当前不可达（数据缺口，待恢复后对账回灌）"
                logger.warning(
                    f"[Memory] split-brain 防护：ChromaDB 初始化失败，降级为 JSON 关键词检索"
                    f"（初始化阶段无存量可导出，直接降级{gap}）")
        if self._col is None:
            self._load_fallback()

    # ---------- 初始化 ----------

    @staticmethod
    def _try_init_chroma(path: Path):
        """尝试初始化 Chroma 集合；失败返回 None（由调用方决定告警口径）"""
        try:
            import chromadb  # type: ignore
            client = chromadb.PersistentClient(path=str(path))
            return client.get_or_create_collection("agent_memory")
        except Exception:  # ImportError / embedding 初始化失败等
            return None

    def _load_fallback(self) -> None:
        if not self._fallback_path.exists():
            return
        try:
            raw = json.loads(self._fallback_path.read_text(encoding="utf-8"))
            for item in raw.get("records", []):
                rec = MemoryRecord(**item)
                self._records[rec.id] = rec
        except Exception as e:
            logger.error(f"[Memory] fallback 存储读取失败: {e}")

    def _save_fallback(self) -> None:
        payload = {"records": [r.model_dump() for r in self._records.values()]}
        tmp = self._fallback_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._fallback_path)

    # ---------- split-brain 状态机 ----------

    @staticmethod
    def _meta(record: MemoryRecord) -> Dict:
        """Chroma 元数据构造（写入/回灌共用，保证两侧口径一致）"""
        return {
            "kind": record.kind,
            "source": record.source,
            "created_at": record.created_at,
            "project_id": record.project_id,
            "pinned": bool(record.pinned),
        }

    @staticmethod
    def _record_from_chroma(rid: str, doc: str, meta: Optional[Dict]) -> MemoryRecord:
        m = meta or {}
        return MemoryRecord(
            id=rid,
            content=doc or "",
            kind=m.get("kind", "summary"),
            source=m.get("source", ""),
            created_at=m.get("created_at", 0.0),
            project_id=m.get("project_id", ""),
            pinned=bool(m.get("pinned", False)),
        )

    def _read_chroma_all(self) -> List[MemoryRecord]:
        """Chroma 全量读取（导出/对账用）；失败向上抛由调用方处置"""
        res = self._col.get(include=["documents", "metadatas"])
        ids = res.get("ids", []) or []
        docs = res.get("documents", []) or []
        metas = res.get("metadatas", []) or []
        return [
            self._record_from_chroma(rid, docs[i] if i < len(docs) else "",
                                     metas[i] if i < len(metas) else None)
            for i, rid in enumerate(ids)
        ]

    def _degrade_on_error(self, op: str, error: Exception) -> None:
        """Chroma 运行期故障统一入口：一次性导出后切 JSON 降级。

        - 导出成功：降级且数据可达（warning 含导出条数）
        - 导出失败：降级 + 显式告警数据缺口（warning 含失败原因）
        """
        exported = 0
        export_err: Optional[Exception] = None
        if self._col is not None:
            # 先载 JSON 兜底存量，再并入 Chroma 导出（同 id 以故障前的 Chroma 为准）
            self._load_fallback()
            try:
                chroma_recs = self._read_chroma_all()
                for rec in chroma_recs:
                    self._records[rec.id] = rec
                self._save_fallback()
                exported = len(chroma_recs)
            except Exception as e:
                export_err = e
        self._col = None
        self._degraded = True
        self._dual_write = True
        # 降级即重置恢复节流窗口：故障刚发生不立即重连，按间隔再试
        self._last_recover_attempt = time.time()
        record_degradation("vector_store.degrade")
        if export_err is not None:
            record_degradation("vector_store.export_failed")
            logger.warning(
                f"[Memory] split-brain 告警：Chroma {op}失败（{error}），"
                f"且 Chroma→JSON 导出也失败（{export_err}），降级为 JSON 关键词检索——"
                f"Chroma 内存量记录当前不可达，存在数据缺口，待恢复后对账回灌")
        else:
            logger.warning(
                f"[Memory] split-brain 防护：Chroma {op}失败（{error}），降级为 JSON 关键词检索；"
                f"已一次性导出 Chroma 存量 {exported} 条至兜底库，降级期数据可达")

    def try_recover(self) -> bool:
        """降级期尝试恢复 Chroma：重连成功则对账回灌并退出双写。

        对账口径：JSON 兜底库有而 Chroma 无的记录（差集）回灌 Chroma；
        回灌失败则保持降级不半恢复。返回是否已恢复 chroma 正常态。
        """
        if self._backend != "chromadb":
            return False
        if not self._degraded:
            return self._col is not None
        self._last_recover_attempt = time.time()
        col = self._try_init_chroma(self._dir / "vectors")
        if col is None:
            logger.debug("[Memory] Chroma 恢复尝试失败（仍不可用），保持 JSON 降级")
            return False
        try:
            existing_ids = set((col.get(include=[]) or {}).get("ids", []) or [])
            missing = [r for rid, r in self._records.items() if rid not in existing_ids]
            for rec in missing:
                col.add(ids=[rec.id], documents=[rec.content], metadatas=[self._meta(rec)])
        except Exception as e:
            # 半恢复比不恢复更危险（两侧各持一半）：回灌失败整体退回降级态
            record_degradation("vector_store.reconcile_failed")
            logger.warning(
                f"[Memory] split-brain 告警：Chroma 重连成功但对账回灌失败（{e}），"
                f"保持 JSON 降级，待下次恢复尝试")
            return False
        self.last_reconcile = {
            "backfilled": len(missing),
            "chroma_existing": len(existing_ids),
            "json_total": len(self._records),
            "ts": time.time(),
        }
        self._col = col
        self._degraded = False
        self._dual_write = False
        logger.warning(
            f"[Memory] split-brain 对账完成：Chroma 已恢复，JSON→Chroma 回灌 {len(missing)} 条"
            f"（Chroma 原有 {len(existing_ids)} 条，JSON 共 {len(self._records)} 条），退出降级双写")
        return True

    def _maybe_auto_recover(self) -> None:
        """检索路径的节流自动恢复（写入路径不节流：写入天然低频）"""
        if time.time() - self._last_recover_attempt < _RECOVER_RETRY_INTERVAL:
            return
        self.try_recover()

    # ---------- 公开 API ----------

    @property
    def using_chromadb(self) -> bool:
        return self._col is not None

    @property
    def degraded(self) -> bool:
        """是否处于 JSON 降级态（split-brain 状态机观测用）"""
        return self._degraded

    @property
    def dual_write(self) -> bool:
        """降级期双写是否生效（恢复对账后应退出）"""
        return self._dual_write

    def add(self, record: MemoryRecord) -> None:
        if self._col is not None:
            try:
                self._col.add(
                    ids=[record.id],
                    documents=[record.content],
                    metadatas=[self._meta(record)],
                )
                return
            except Exception as e:
                self._degrade_on_error("写入", e)
        # 降级态双写：新写入落 JSON 兜底库（内存字典 + 持久化文件），降级期记忆不丢
        self._records[record.id] = record
        self._save_fallback()
        if self._degraded:
            logger.debug(f"[Memory] 降级双写：记忆 {record.id} 已落 JSON 兜底库")
            # 惰性恢复：若 Chroma 已可用，对账会把本条一并回灌后退出双写
            self.try_recover()

    def search_semantic(self, query: str, top_k: int) -> Optional[List[Tuple[MemoryRecord, float]]]:
        """语义检索（仅 ChromaDB 可用时）；返回 None 表示需降级关键词检索"""
        if self._col is None:
            if self._degraded:
                self._maybe_auto_recover()
            if self._col is None:
                return None
        try:
            res = self._col.query(query_texts=[query], n_results=top_k)
            ids = res.get("ids", [[]])[0]
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            dists = res.get("distances", [[]])[0]
            out: List[Tuple[MemoryRecord, float]] = []
            for i, rid in enumerate(ids):
                rec = self._record_from_chroma(rid, docs[i] if i < len(docs) else "",
                                               metas[i] if i < len(metas) else None)
                # cosine distance → 相似度得分（越大越相关）
                score = 1.0 / (1.0 + (dists[i] if i < len(dists) else 1.0))
                out.append((rec, score))
            return out
        except Exception as e:
            self._degrade_on_error("语义检索", e)
            return None

    def all_records(self) -> List[MemoryRecord]:
        """全量记录（fallback 检索用；ChromaDB 后端同样支持，管理 API 用）"""
        if self._col is not None:
            try:
                return self._read_chroma_all()
            except Exception as e:
                self._degrade_on_error("全量读取", e)
        return list(self._records.values())

    def set_pinned(self, record_id: str, pinned: bool) -> bool:
        """置顶/取消置顶（M4 管理 API 用）；不存在返回 False"""
        if self._col is not None:
            try:
                existing = self._col.get(ids=[record_id], include=["metadatas"])
                if not existing.get("ids"):
                    return False
                meta = dict((existing.get("metadatas") or [{}])[0] or {})
                meta["pinned"] = bool(pinned)
                self._col.update(ids=[record_id], metadatas=[meta])
                return True
            except Exception as e:
                self._degrade_on_error("置顶更新", e)
        rec = self._records.get(record_id)
        if rec is None:
            return False
        rec.pinned = bool(pinned)
        self._save_fallback()
        return True

    def delete(self, record_id: str) -> bool:
        """删除一条记忆（管理 API 用）；不存在返回 False"""
        if self._col is not None:
            try:
                existing = self._col.get(ids=[record_id])
                if not existing.get("ids"):
                    return False
                self._col.delete(ids=[record_id])
                return True
            except Exception as e:
                self._degrade_on_error("删除", e)
        if record_id in self._records:
            del self._records[record_id]
            self._save_fallback()
            return True
        return False

    def count(self) -> int:
        if self._col is not None:
            try:
                return int(self._col.count())
            except Exception as e:
                self._degrade_on_error("计数", e)
        return len(self._records)
