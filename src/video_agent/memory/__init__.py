"""
Agent 混合记忆系统

- 摘要触发：每 memory_summary_interval 轮对话一次（后台异步）
- 检索注入：build_context() → system prompt（语义 + 关键词 + 时间衰减）
- 存储：ChromaDB 优先，JSON 文件降级
"""
from src.video_agent.memory.manager import MemoryManager
from src.video_agent.memory.models import MemoryRecord

__all__ = ["MemoryManager", "MemoryRecord"]
