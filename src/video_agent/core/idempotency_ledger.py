"""轮内幂等键账本（T4）：写类工具重复提交按 `idempotency_key` 去重。

语义（T4 轻量版）：
- 空键直通过不去重：`idempotency_key` 是写类工具的可选字段，留空时行为不变；
- 同键返回首次结果：含失败结果（首次失败也被缓存，避免重复触发副作用）；
  同键不同参也按首次结果返回——键视为提交身份凭证，参数不参与比对；
- 生命周期随轮：由 FCToolRunner 实例持有，轮始经 reset() 清空，
  不持久化进 StateManager（状态唯一写入点纪律，Rule 3）。
"""
from typing import Dict, Optional

from src.video_agent.tools.base import ToolResult


class IdempotencyLedger:
    """幂等键 → 首次执行结果（轮内去重，不落盘）"""

    def __init__(self) -> None:
        self._records: Dict[str, ToolResult] = {}

    def check(self, key: str) -> Optional[ToolResult]:
        """查键对应首次结果；空键或未登记返回 None（空键直通过不去重）"""
        if not key:
            return None
        return self._records.get(key)

    def record(self, key: str, result: ToolResult) -> None:
        """登记首次结果（成败皆记，避免重复副作用）；空键不登记，
        同键已有登记则以首次为准（不覆盖）"""
        if not key:
            return
        self._records.setdefault(key, result)

    def reset(self) -> None:
        """轮始清空：账本只随轮生效，跨轮同键不串"""
        self._records.clear()
