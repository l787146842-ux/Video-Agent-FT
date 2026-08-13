"""实时上下文用量度量（888 反馈：用量数字一轮任务结束才变）。

静态估算（持久化聊天记录 + 状态上下文）不含本轮进行中的消息与工具回喂，
轮内数字恒定。主对话循环每次 LLM 调用前把截断后的真实消息记入本注册表，
context-usage 接口优先取新鲜 live 值，静态估算作兜底——推理中 5s 轮询即可
看到用量随步骤增长。
"""
import time
from typing import Any, Dict, List, Optional

from src.video_agent.core.token_budget import estimate_messages_tokens

# project_id → {"est_tokens": int, "ts": float}
_LIVE: Dict[str, Dict[str, Any]] = {}
# live 值有效期：超过该时长（推理已结束/异常退出）回落静态估算
_VALID_SECS = 180.0


def record_live_context(project_id: str, messages: List[Dict[str, Any]]) -> None:
    """记录一次 LLM 调用的真实上下文规模（截断后口径）。异常静默不影响主流程。"""
    if not project_id:
        return
    try:
        _LIVE[project_id] = {
            "est_tokens": estimate_messages_tokens(messages),
            "ts": time.time(),
        }
    except Exception:
        pass


def get_live_context(project_id: str) -> Optional[Dict[str, Any]]:
    """取最近一次 live 记录；过期或不存在返回 None。"""
    rec = _LIVE.get(project_id or "")
    if not rec or time.time() - rec["ts"] > _VALID_SECS:
        return None
    return rec
