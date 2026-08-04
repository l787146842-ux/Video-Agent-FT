"""
记忆管理器（单例）：统筹写入（摘要）与读取（混合检索上下文注入）。

- 写入：每 N 轮对话触发一次摘要（memory_summary_interval），后台异步不阻塞 SSE
- 读取：build_context(user_message) 渲染 prompts/memory/context_template.md
"""
import asyncio
import threading
import time
from datetime import datetime
from typing import Awaitable, Callable, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.memory.models import MemoryRecord
from src.video_agent.memory.retriever import hybrid_rank, tokenize
from src.video_agent.memory.summarizer import summarize_dialog
from src.video_agent.memory.vector_store import VectorStore
from src.video_agent.utils.paths import DATA_DIR
from src.video_agent.utils.prompts import render_prompt

SummarizeFn = Callable[[str], Awaitable[str]]


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
        self._dialog_count = 0
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
        if not settings.memory_enabled:
            return ""
        if not user_message or not user_message.strip():
            return ""
        try:
            records = self.retrieve(user_message, project_id=project_id)
        except Exception as e:
            logger.warning(f"[Memory] 检索失败: {e}")
            return ""
        if not records:
            return ""
        lines = []
        for r in records:
            day = datetime.fromtimestamp(r.created_at).strftime("%m-%d") if r.created_at else "----"
            lines.append(f"- [{day}] {r.content}")
        return render_prompt("memory/context_template.md", memories="\n".join(lines))

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
        self._dialog_count += 1
        if self._dialog_count % max(1, self._summary_interval) != 0:
            return None

        content = await summarize_dialog(user_message, agent_reply, summarize_fn)
        if not content:
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
        return self._dialog_count
