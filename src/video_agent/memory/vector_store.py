"""
向量存储：ChromaDB 优先，未安装/初始化失败时降级为 JSON 文件 + 关键词检索。

降级策略保证记忆系统在任何环境可用（Rule: 诚实降级，不伪造语义检索结果）。
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.memory.models import MemoryRecord


class VectorStore:
    """记忆向量存储（双后端）"""

    def __init__(self, persist_dir: Path, backend: str = "chromadb"):
        self._dir = persist_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fallback_path = self._dir / "fallback.json"
        self._records: Dict[str, MemoryRecord] = {}
        self._col = None

        if backend == "chromadb":
            self._col = self._try_init_chroma(self._dir / "vectors")
        if self._col is None:
            self._load_fallback()

    # ---------- 初始化 ----------

    @staticmethod
    def _try_init_chroma(path: Path):
        try:
            import chromadb  # type: ignore
            client = chromadb.PersistentClient(path=str(path))
            return client.get_or_create_collection("agent_memory")
        except Exception as e:  # ImportError / embedding 初始化失败等
            logger.warning(f"[Memory] ChromaDB 不可用，降级为 JSON 关键词检索: {e}")
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

    # ---------- 公开 API ----------

    @property
    def using_chromadb(self) -> bool:
        return self._col is not None

    def add(self, record: MemoryRecord) -> None:
        if self._col is not None:
            try:
                self._col.add(
                    ids=[record.id],
                    documents=[record.content],
                    metadatas=[{
                        "kind": record.kind,
                        "source": record.source,
                        "created_at": record.created_at,
                        "project_id": record.project_id,
                        "pinned": bool(record.pinned),
                    }],
                )
                return
            except Exception as e:
                logger.warning(f"[Memory] ChromaDB 写入失败，降级 JSON: {e}")
                self._col = None
                self._load_fallback()
        self._records[record.id] = record
        self._save_fallback()

    def search_semantic(self, query: str, top_k: int) -> Optional[List[Tuple[MemoryRecord, float]]]:
        """语义检索（仅 ChromaDB 可用时）；返回 None 表示需降级关键词检索"""
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
                rec = MemoryRecord(
                    id=rid,
                    content=docs[i] if i < len(docs) else "",
                    kind=(metas[i] or {}).get("kind", "summary"),
                    source=(metas[i] or {}).get("source", ""),
                    created_at=(metas[i] or {}).get("created_at", 0.0),
                    project_id=(metas[i] or {}).get("project_id", ""),
                )
                # cosine distance → 相似度得分（越大越相关）
                score = 1.0 / (1.0 + (dists[i] if i < len(dists) else 1.0))
                out.append((rec, score))
            return out
        except Exception as e:
            logger.warning(f"[Memory] ChromaDB 查询失败，降级关键词检索: {e}")
            return None

    def all_records(self) -> List[MemoryRecord]:
        """全量记录（fallback 检索用；ChromaDB 后端同样支持，管理 API 用）"""
        if self._col is not None:
            try:
                res = self._col.get(include=["documents", "metadatas"])
                ids = res.get("ids", []) or []
                docs = res.get("documents", []) or []
                metas = res.get("metadatas", []) or []
                out: List[MemoryRecord] = []
                for i, rid in enumerate(ids):
                    m = metas[i] if i < len(metas) and metas[i] else {}
                    out.append(MemoryRecord(
                        id=rid,
                        content=docs[i] if i < len(docs) else "",
                        kind=m.get("kind", "summary"),
                        source=m.get("source", ""),
                        created_at=m.get("created_at", 0.0),
                        project_id=m.get("project_id", ""),
                        pinned=bool(m.get("pinned", False)),
                    ))
                return out
            except Exception as e:
                logger.warning(f"[Memory] ChromaDB 全量读取失败: {e}")
                return []
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
                logger.warning(f"[Memory] ChromaDB 置顶更新失败，降级 JSON: {e}")
                self._col = None
                self._load_fallback()
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
                logger.warning(f"[Memory] ChromaDB 删除失败，降级 JSON: {e}")
                self._col = None
                self._load_fallback()
        if record_id in self._records:
            del self._records[record_id]
            self._save_fallback()
            return True
        return False

    def count(self) -> int:
        if self._col is not None:
            try:
                return int(self._col.count())
            except Exception as _e:
                logger.debug("[vector_store] 忽略异常: {}", _e)
        return len(self._records)
