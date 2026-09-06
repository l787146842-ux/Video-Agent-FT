"""重试续跑现场域（任务#6：出错重试改为带上下文续跑）。

职责：
- 失败现场收集：优先取既有 trace 账本（core/tracer：steps 内含每步工具调用
  与结果；失败轮的 partial trace 由 agent_loop 异常路径归档落账），
  失败原因回落/补充自聊天历史持久化的错误消息（⚠️ 前缀气泡，
  chat_errors 统一出口）；前端不拼字符串回传。
- 续跑前置块组装：固定话术外置 prompts/shared/retry_resume.md（Rule 6），
  现场数据渲染进模板，作为用户消息前置块注入（用户原消息原样保留其后，
  持久化的用户气泡不含本块）。
- 用户无感知回落：取不到现场/任何异常一律返回空串，调用方回落原机械重发，
  重试本身绝不因续跑组装而报错。
"""
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.core.tracer import AgentTracer
from src.video_agent.utils.prompts import load_prompt_section

__all__ = ["build_retry_resume_note", "collect_failure_scene", "render_scene"]

_RESUME_PROMPT_PATH = "shared/retry_resume.md"
_RESUME_SECTION = "RESUME_NOTE"
# 现场规模封顶：防长任务 trace 把前置块撑爆（预算友好）
_MAX_ACTION_ENTRIES = 12
_DETAIL_MAX_CHARS = 120
_ERROR_MAX_CHARS = 300
# 内部过程条目非业务工具，不进现场清单
_INTERNAL_ACTION_NAMES = ("model_reasoning", "bad_output_retry")
# 视为「失败轮」的 step finish_reason 集合
# output_truncated（五项修法批 2）：输出预算截断收轮，重试续跑同样受益于失败现场
_FAILED_FINISH_REASONS = ("error", "bad_output", "output_truncated")


def _trace_failed(trace: Dict[str, Any]) -> bool:
    """trace 是否带失败标记（失败摘要/失败 finish_reason/失败动作）。"""
    if str(trace.get("error") or "").strip():
        return True
    for step in trace.get("steps") or []:
        if str(step.get("finish_reason") or "") in _FAILED_FINISH_REASONS:
            return True
        for act in step.get("actions") or []:
            if isinstance(act, dict) and act.get("ok") is False:
                return True
    return False


def _find_scene_trace(traces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """定位现场来源 trace（新→旧）：优先失败轮；无失败标记时取最近一条
    有执行记录的轮（如用户停止轮，进度现场同样有续跑价值）。"""
    for t in traces or []:
        if _trace_failed(t):
            return t
    for t in traces or []:
        if any((s.get("actions") or []) for s in (t.get("steps") or [])):
            return t
    return None


def _last_error_chat_message(svc) -> str:
    """最近一条用户消息之后的最近一条错误气泡正文（⚠️ 前缀 = chat_errors
    统一出口）。限定在最后一条 user 消息之后：失败气泡必在触发重试的
    用户消息之后，避免极端时序下拼出「进度是新轮、原因是旧错误」的错位现场。"""
    try:
        msgs = svc.get_chat_messages() or []
        last_user_idx = max(
            (i for i, m in enumerate(msgs) if m.get("sender") == "user"),
            default=-1,
        )
        for m in reversed(msgs[last_user_idx + 1:]):
            if m.get("sender") != "agent":
                continue
            text = str(m.get("text") or "").strip()
            if text.startswith("⚠️"):
                return text[len("⚠️"):].strip()[:_ERROR_MAX_CHARS]
    except Exception as e:
        logger.debug("[RetryResume] 错误消息回溯失败（忽略）: {}", e)
    return ""


def collect_failure_scene(svc) -> Optional[Dict[str, Any]]:
    """收集结构化失败现场；无现场可还原时返回 None。

    返回 {"progress": [{name, ok, detail}], "failed_at": str, "error": str}：
    progress = 按序工具调用账本（只留最近 N 条）；failed_at = 中断点；
    error = 失败原因（trace 归档摘要优先，聊天错误气泡回落）。
    """
    try:
        traces = AgentTracer.get_instance().get_recent_traces(limit=3)
    except Exception as e:
        logger.debug("[RetryResume] trace 读取失败（忽略）: {}", e)
        traces = []
    trace = _find_scene_trace(traces)
    progress: List[Dict[str, Any]] = []
    failed_at = ""
    error = ""
    if trace:
        error = str(trace.get("error") or "").strip()[:_ERROR_MAX_CHARS]
        for step in trace.get("steps") or []:
            for act in step.get("actions") or []:
                if not isinstance(act, dict):
                    continue
                name = str(act.get("name") or "").strip()
                if not name or name in _INTERNAL_ACTION_NAMES:
                    continue
                ok = act.get("ok") is not False
                detail = str(act.get("result_summary") or act.get("summary") or "").strip()
                detail = detail[:_DETAIL_MAX_CHARS]
                progress.append({"name": name, "ok": ok, "detail": detail})
                if not ok and not failed_at:
                    failed_at = f"执行到工具 {name} 时失败" + (f"：{detail}" if detail else "")
        progress = progress[-_MAX_ACTION_ENTRIES:]
    chat_error = _last_error_chat_message(svc)
    if chat_error and not error:
        error = chat_error
    if not progress and not error:
        return None
    if not failed_at and error:
        failed_at = "模型调用阶段中断（尚无工具失败记录）"
    return {"progress": progress, "failed_at": failed_at, "error": error}


def render_scene(scene: Dict[str, Any]) -> str:
    """现场字典 → 结构化文本块（清单 + 中断点 + 失败原因）。"""
    lines: List[str] = []
    progress = scene.get("progress") or []
    if progress:
        lines.append("已执行的调用（按时间顺序，✔=已成功落盘，✘=失败）：")
        for p in progress:
            mark = "✔" if p.get("ok") else "✘"
            line = f"- {mark} {p.get('name')}"
            detail = str(p.get("detail") or "").strip()
            if detail:
                line += f" —— {detail}"
            lines.append(line)
    if scene.get("failed_at"):
        lines.append(f"中断点：{scene['failed_at']}")
    if scene.get("error"):
        lines.append(f"失败原因：{scene['error']}")
    return "\n".join(lines)


def build_retry_resume_note(svc) -> str:
    """组装续跑前置块；无现场/模板缺失/任何异常一律返回空串（静默回落）。"""
    try:
        scene = collect_failure_scene(svc)
        if not scene:
            return ""
        tpl = load_prompt_section(_RESUME_PROMPT_PATH, _RESUME_SECTION)
        if not tpl:
            return ""
        return tpl.replace("{{scene}}", render_scene(scene)).strip()
    except Exception as e:
        logger.debug("[RetryResume] 续跑现场组装失败，回落机械重发: {}", e)
        return ""
