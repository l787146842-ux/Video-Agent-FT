"""SSE 连接诊断（D2 批 commit1）：任务事件流订阅的全程取证留痕。

背景（3333 取证，proj-1789706227）：服务端轮步连续、暂停落账正常，前端却整屏冻死；
核对代码后发现 subscribe 回放首帧 / event_seq 去重 / 15s 注释心跳**均已存在**，
缺的是连接级取证——一条连接何时建立、发了几帧、最后 seq 到哪、以何种方式结束
（客户端断开 / 终态帧 / 保险丝 / 关停），日志里看不出，D2「取证优先」裁决无数据可抓。

本模块只计数与收尾打日志，**不参与任何控制流**（纯加性观测，回退 = 不构造实例）；
路由层每条连接持一个实例。心跳计数含注释心跳帧（代理保活腿），frames 只计 data 帧。
"""
from __future__ import annotations

import time

from loguru import logger


class SseConnDiag:
    """单条 SSE 订阅的连接级诊断计数器（纯计数 + 收尾一次性日志，零副作用）。"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.started_at = time.time()
        self.frames = 0          # data 帧计数
        self.heartbeats = 0      # 注释心跳计数
        self.last_seq = 0        # 已下发帧的 event_seq 高水位
        self.closed_by = ""      # 首次 close 的原因（幂等锁定）

    def note_frame(self, seq: object) -> None:
        """记一条 data 帧；seq 取帧内 event_seq（旧帧无此键时只计数）。"""
        self.frames += 1
        try:
            n = int(seq or 0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            n = 0
        if n > self.last_seq:
            self.last_seq = n

    def note_heartbeat(self) -> None:
        self.heartbeats += 1

    def close(self, reason: str) -> None:
        """收尾留痕（幂等：首因锁定，finally 兜底调用不会覆盖明确原因）。"""
        if self.closed_by:
            return
        self.closed_by = reason
        logger.info(
            "[SseDiag] task={} close={} frames={} heartbeats={} last_seq={} alive_s={:.1f}",
            self.task_id, reason, self.frames, self.heartbeats,
            self.last_seq, time.time() - self.started_at,
        )


__all__ = ["SseConnDiag"]
