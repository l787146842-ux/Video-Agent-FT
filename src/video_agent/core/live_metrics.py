"""实时上下文用量度量（888 反馈：用量数字任务结束才变）。

静态估算（持久化聊天记录 + 状态上下文）不含本轮进行中的消息与工具回喂，
轮内数字恒定。主对话循环每次 LLM 调用前把截断后的真实消息记入本注册表，
context-usage 接口优先取新鲜 live 值，静态估算作兜底——推理中 5s 轮询即可
看到用量随步骤增长。
"""
from loguru import logger
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
    except Exception as _e:
        logger.debug("[live_metrics] 忽略异常: {}", _e)


# system prompt 组装明细（prompt_builder 写入，context-usage 返回）
_SECTIONS: Dict[str, Dict[str, int]] = {}


def record_sections(project_id: str, sections: Dict[str, int]) -> None:
    """记录最近一次 system prompt 各段字符数（组装层可观测性，调试端点用）。"""
    if project_id:
        _SECTIONS[project_id] = dict(sections)


def get_sections(project_id: str) -> Dict[str, int]:
    return dict(_SECTIONS.get(project_id or "", {}))


def get_live_context(project_id: str) -> Optional[Dict[str, Any]]:
    """取最近一次 live 记录；过期或不存在返回 None。"""
    rec = _LIVE.get(project_id or "")
    if not rec or time.time() - rec["ts"] > _VALID_SECS:
        return None
    return rec


# 核心探测点「预期外降级」遥测——接线断裂从静默 False 变为可观测计数
# （模式：md 幸存但代码无人读，探测点异常降级 False 无人察觉）。
# point → {"count": int, "first_ts": float, "last_ts": float}
_DEGRADATIONS: Dict[str, Dict[str, Any]] = {}
# 滚动上限：点位过多时丢弃最旧（防遥测自身膨胀）
_DEGRADATION_MAX_POINTS = 200


def record_degradation(point: str, project_id: str = "") -> None:
    """记录一次核心探测点的意外降级（异常捕获回落默认值时调用）。

    point 命名约定：`模块.探测点名`（如 agent_loop._wizard_active）；
    project_id 可空（空记全局桶）。只计数不落盘——这是运行期健康信号。
    """
    key = f"{point}@{project_id or '_global'}"
    rec = _DEGRADATIONS.get(key)
    now = time.time()
    if rec:
        rec["count"] += 1
        rec["last_ts"] = now
    else:
        if len(_DEGRADATIONS) >= _DEGRADATION_MAX_POINTS:
            oldest = min(_DEGRADATIONS.items(), key=lambda kv: kv[1]["last_ts"])[0]
            _DEGRADATIONS.pop(oldest, None)
        _DEGRADATIONS[key] = {"point": point, "project_id": project_id or "",
                              "count": 1, "first_ts": now, "last_ts": now}


def get_degradations() -> List[Dict[str, Any]]:
    """全部降级计数（按最近触发时间倒序），调试端点暴露用。"""
    return sorted(_DEGRADATIONS.values(), key=lambda r: r["last_ts"], reverse=True)


def reset_degradations() -> None:
    """测试用：清空降级计数。"""
    _DEGRADATIONS.clear()
