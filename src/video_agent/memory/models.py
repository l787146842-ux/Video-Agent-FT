"""
记忆数据模型（pydantic，Rule: 状态模型统一校验）。
"""
import time
import uuid
from typing import List, Literal

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """一条长期记忆（对话摘要 / 事实 / 偏好）"""

    id: str = Field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:12]}")
    kind: Literal["summary", "fact", "preference"] = "summary"
    content: str = ""
    # 来源描述（如用户消息前 40 字，便于追溯）
    source: str = ""
    created_at: float = Field(default_factory=time.time)
    keywords: List[str] = Field(default_factory=list)
    # 检索阶段填充的临时得分（不持久化语义）
    score: float = 0.0
