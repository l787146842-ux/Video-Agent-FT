"""
记忆管理器（单例）：统筹写入（摘要）与读取（混合检索上下文注入）。

- 写入：每 N 轮对话触发一次摘要（memory_summary_interval），后台异步不阻塞 SSE
- 读取：build_context(user_message) 渲染 prompts/memory/context_template.md
"""
import asyncio
import threading
import time
from datetime import datetime
from typing import Awaitable, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.memory.models import MemoryRecord
from src.video_agent.memory.retriever import hybrid_rank, tokenize
from src.video_agent.memory.summarizer import summarize_dialog
from src.video_agent.memory.vector_store import VectorStore
from src.video_agent.utils.paths import DATA_DIR
from src.video_agent.utils.prompts import render_prompt

SummarizeFn = Callable[[str], Awaitable[str]]

# 写入去重阈值（4.7）：新旧记忆关键词集 Jaccard 重叠 ≥ 此值视为同一条，
# 跳过写入防同类摘要反复堆积
_DUP_KEYWORD_JACCARD = 0.6


class MemoryManager:
    """Agent 混合记忆系统入口（线程安全单例）"""

    _instance: Optional["MemoryManager"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        persist_dir=None,
        backend: Optional[str] = None,
        summary_interval: Optional[int] = None,
    ):
        base = persist_dir or (DATA_DIR / "memory")
        self._store = VectorStore(base, backend or settings.memory_vector_backend)
        self._dialog_counts: Dict[str, int] = {}  # B6/F51：按 project_id 分桶
        self._write_lock = asyncio.Lock()
        # 实例级覆盖（测试友好）；默认读全局配置
        self._summary_interval = summary_interval or settings.memory_summary_interval

    @classmethod
    def get_instance(cls) -> "MemoryManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """测试用：重置单例"""
        with cls._instance_lock:
            cls._instance = None

    # ---------- 读取：构建注入上下文 ----------

    @staticmethod
    def _project_visible(record: MemoryRecord, project_id: str) -> bool:
        """项目隔离过滤：未指定项目时全部可见；记录无项目标记（历史遗留）时不隔离"""
        if not project_id or not record.project_id:
            return True
        return record.project_id == project_id

    def retrieve(
        self, user_message: str, top_k: Optional[int] = None, project_id: str = "",
    ) -> List[MemoryRecord]:
        """混合检索相关记忆（按项目隔离，P1 修复）"""
        top_k = top_k or settings.memory_max_results
        semantic = self._store.search_semantic(user_message, top_k * 2)
        if semantic is not None:
            semantic = [(r, s) for r, s in semantic if self._project_visible(r, project_id)]
            records = [r for r, _ in semantic]
            scores = {r.id: s for r, s in semantic}
        else:
            records = [
                r for r in self._store.all_records() if self._project_visible(r, project_id)
            ]
            scores = None
        return hybrid_rank(
            records,
            user_message,
            half_life_days=float(settings.memory_time_decay_days),
            top_k=top_k,
            semantic_scores=scores,
        )

    def build_context(self, user_message: str, project_id: str = "") -> str:
        """检索相关记忆并渲染注入模板；无相关记忆返回空串"""
        ctx, _hits = self.build_context_with_hits(user_message, project_id=project_id)
        return ctx

    def build_context_with_hits(
        self, user_message: str, project_id: str = "",
    ) -> "tuple[str, list]":
        """检索 + 渲染注入模板，返回 (上下文块, 命中明细)（4.7 命中可视化：
        命中项随 done payload 下发前端展示，记忆不再是黑盒注入）"""
        if not settings.memory_enabled:
            return "", []
        if not user_message or not user_message.strip():
            return "", []
        try:
            records = self.retrieve(user_message, project_id=project_id)
        except Exception as e:
            logger.warning(f"[Memory] 检索失败: {e}")
            return "", []
        if not records:
            return "", []
        lines = []
        hits = []
        for r in records:
            day = datetime.fromtimestamp(r.created_at).strftime("%m-%d") if r.created_at else "----"
            lines.append(f"- [{day}] {r.content}")
            hits.append({"id": r.id, "date": day, "content": r.content})
        return render_prompt("memory/context_template.md", memories="\n".join(lines)), hits

    # ---------- 写入去重与管理 ----------

    def _find_duplicate(self, content: str, project_id: str) -> Optional[MemoryRecord]:
        """写入去重检测（4.7）：与已有记忆的关键词集 Jaccard 重叠 ≥ 阈值视为同一条"""
        new_kw = set(tokenize(content)[:10])
        if not new_kw:
            return None
        try:
            candidates = self.retrieve(content, top_k=3, project_id=project_id)
        except Exception:
            return None
        for r in candidates:
            old_kw = set(r.keywords or tokenize(r.content)[:10])
            if not old_kw:
                continue
            inter = len(new_kw & old_kw)
            union = len(new_kw | old_kw)
            if union and inter / union >= _DUP_KEYWORD_JACCARD:
                return r
        return None

    def list_records(self, project_id: str = "") -> List[MemoryRecord]:
        """全量记忆清单（管理 API 用）；指定项目时只返回该项目的记忆；
        排序：置顶优先，其余按时间新→旧（M4）"""
        records = self._store.all_records()
        if project_id:
            records = [r for r in records if r.project_id == project_id]
        return sorted(
            records,
            key=lambda r: (not r.pinned, -(r.created_at or 0.0)),
        )

    def pin_record(self, record_id: str, pinned: bool) -> bool:
        """置顶/取消置顶一条记忆（M4 管理 API 用）；不存在返回 False"""
        return self._store.set_pinned(record_id, pinned)

    def delete_record(self, record_id: str) -> bool:
        """删除一条记忆（管理 API 用）；不存在返回 False"""
        return self._store.delete(record_id)

    # ---------- 写入：对话摘要 ----------

    async def record_dialog(
        self,
        user_message: str,
        agent_reply: str,
        summarize_fn: Optional[SummarizeFn] = None,
        project_id: str = "",
    ) -> Optional[MemoryRecord]:
        """
        记录一轮对话（按 memory_summary_interval 间隔触发摘要写入）。
        返回写入的 MemoryRecord；未触发/未启用返回 None。
        """
        if not settings.memory_enabled:
            return None
        # B6/F51：摘要触发计数按项目分桶（此前全局单例计数，跨项目混合触发：
        # A 项目 2 条 + B 项目 1 条会触发第 3 条的摘要）
        self._dialog_counts[str(project_id or "")] = \
            self._dialog_counts.get(str(project_id or ""), 0) + 1
        if self._dialog_counts[str(project_id or "")] % max(1, self._summary_interval) != 0:
            return None

        content = await summarize_dialog(user_message, agent_reply, summarize_fn)
        if not content:
            return None

        # 写入去重（4.7）：同类对话反复触发相似摘要时不再重复堆积
        dup = self._find_duplicate(content, project_id)
        if dup is not None:
            logger.info(f"[Memory] 跳过重复记忆（与 {dup.id} 高度相似）: {content[:40]}…")
            return None

        record = MemoryRecord(
            content=content,
            source=str(user_message)[:40],
            keywords=tokenize(content)[:10],
            project_id=project_id,
        )
        async with self._write_lock:
            try:
                self._store.add(record)
                logger.info(f"[Memory] 已写入记忆（共 {self._store.count()} 条）: {content[:40]}…")
            except Exception as e:
                logger.error(f"[Memory] 写入失败: {e}")
                return None
        return record

    def record_dialog_background(
        self,
        user_message,
        agent_reply: str,
        summarize_fn: Optional[SummarizeFn] = None,
        project_id: str = "",
    ) -> None:
        """fire-and-forget 后台记录（不阻塞 SSE 响应流）"""
        if not settings.memory_enabled:
            return
        # 多模态 content 提取文本
        if not isinstance(user_message, str):
            user_message = str(user_message)

        async def _safe():
            try:
                await self.record_dialog(user_message, agent_reply, summarize_fn,
                                         project_id=project_id)
            except Exception as e:
                logger.warning(f"[Memory] 后台记录失败: {e}")

        try:
            asyncio.get_running_loop().create_task(_safe())
        except RuntimeError:
            # 无运行中事件循环（CLI/测试同步上下文）：静默跳过
            pass

    # ---------- 统计 ----------

    def count(self) -> int:
        return self._store.count()

    @property
    def backend_name(self) -> str:
        return "chromadb" if self._store.using_chromadb else "json"

    @property
    def dialog_count(self) -> int:
        return sum(self._dialog_counts.values())
