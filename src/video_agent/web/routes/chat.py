"""
/api/chat — 截断重答（edit-and-resend）。

语义：定位当前活跃对话最后一条「非系统动作」的用户消息 →
丢弃其后的全部消息（持久化层真正删除）→ 可选替换该消息正文
（保留 turnId 等元数据）→ 复用 start_agent_task 以正常发送的
同一通路起 agent 任务（任务式传输，响应体与 /agent/tasks 一致）。

- agent 忙碌时 409（与前端 busyGuard 同语义：SSE worker 或后台任务在跑）；
- 无用户消息可重答时 400；错误响应走 ErrorPayload 结构化契约。

时序不变式（全部在同一把 svc.lock 临界区内完成）：
1. 忙碌判定（防 TOCTOU：判定与任务注册同临界区，双击只成一单）；
2. 截断前完成全部校验与前置解析——先读原文判空、先解析并校验
   provider/model，任何 4xx 都在破坏性截断之前返回；
3. 冲刷在途防抖写后执行截断（版本闸拒绝 → 409 STATE_CONFLICT，不起任务）。
"""
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.video_agent.exceptions import StateConflictError
from src.video_agent.state import chat_tail_ops
from src.video_agent.state.manager import StateManager
from src.video_agent.web import agent_task_manager
from src.video_agent.web import chat_service
from src.video_agent.web import provider_config
from src.video_agent.web.error_payload import classify_legacy_code
from src.video_agent.web.routes import agent as agent_routes

router = APIRouter()

# 重答携带的历史窗口（与前端 submit-message 取最近 N 条的口径对齐）
_HISTORY_WINDOW = 10


class TruncateResendRequest(BaseModel):
    # 编辑后的新正文；null/缺省 = 不替换正文，仅丢弃尾部后按原文重答
    text: Optional[str] = None
    # 可选显式指定供应商/模型/推理档位：缺省时沿用服务端默认解析
    # （_resolve_chat_target）；显式传入时校验供应商存在且启用、模型在其
    # 聊天模型清单内，非法返回 400
    provider: Optional[str] = None
    model: Optional[str] = None
    thinking_level: Optional[str] = None


def _error(status: int, legacy_code: str, message: str) -> JSONResponse:
    """结构化错误响应（ErrorPayload 契约：detail/message/code/kind/error_code）"""
    return JSONResponse(
        status_code=status,
        content=classify_legacy_code(legacy_code, message).http_body(legacy_code),
    )


def _agent_busy(svc: StateManager) -> bool:
    """忙碌判定（与前端 busyGuard 同语义）：SSE 直连 worker 在跑，
    或当前项目仍有后台 agent 任务运行中。"""
    if any(not t.done() for t in agent_routes._CHAT_TASKS.values()):
        return True
    return bool(agent_task_manager.get_agent_task_manager().list_running(svc.active_project_id or ""))


def _resolve_chat_target() -> Tuple[str, str]:
    """服务端解析默认聊天供应商/模型。

    优先 primary 且启用的带聊天模型供应商；无可用时返回 ("", "")，
    由发送管线按既有逻辑报错。
    """
    candidates = [
        p for p in provider_config.load_merged_providers()
        if p.get("enabled") and (p.get("chat_models") or [])
    ]
    if not candidates:
        return "", ""
    chosen = next((p for p in candidates if p.get("primary")), None) or candidates[0]
    return str(chosen.get("id") or ""), str((chosen.get("chat_models") or [""])[0])


def _resolve_resend_target(body: TruncateResendRequest) -> Tuple[str, str]:
    """解析重答的 provider/model（截断前预检，非法抛 ValueError → 400）。

    显式传入 → 校验供应商存在且启用、模型在其聊天模型清单内；
    未传入 → 沿用服务端默认解析。mock 供应商恒可用（调试/演示通道）。
    """
    default_provider, default_model = _resolve_chat_target()
    provider = (body.provider or "").strip() or default_provider
    model = (body.model or "").strip()
    if not model and provider == default_provider:
        model = default_model
    if provider and provider != "mock":
        chosen = next(
            (p for p in provider_config.load_merged_providers()
             if p.get("id") == provider),
            None,
        )
        if chosen is None or not chosen.get("enabled"):
            raise ValueError(f"供应商 '{provider}' 不存在或未启用")
        models = [str(m) for m in (chosen.get("chat_models") or [])]
        if model and model not in models:
            raise ValueError(f"模型 '{model}' 不在供应商 '{provider}' 的聊天模型清单内")
        if not model and models:
            model = models[0]
    return provider, model


def _history_before(msgs: List[Dict[str, Any]], up_to: int) -> List[Dict[str, str]]:
    """把用户消息之前的保留消息转为发送携带的历史结构（与前端
    submit-message 的 history 形态一致：role/content，无正文的卡片条目跳过）。"""
    out: List[Dict[str, str]] = []
    for m in msgs[max(0, up_to - _HISTORY_WINDOW):up_to]:
        text = str(m.get("text") or "")
        if not text:
            continue
        out.append({
            "role": "assistant" if m.get("sender") == "agent" else "user",
            "content": text,
        })
    return out


@router.post("/chat/truncate-resend")
async def truncate_resend(body: TruncateResendRequest):
    """截断重答：丢弃最后一条用户消息之后的全部消息（真正删除）→
    text 非空且与原文不同时替换该消息正文（保留 turnId 与元数据）→
    以该消息内容起 agent 任务（与正常发送同路径）。

    响应体在 /agent/tasks 契约（{task_id, project_id}）基础上增 model
    字段（实际解析出的模型，供前端对齐选择器）。
    """
    svc = StateManager.get_instance()
    async with svc.lock:
        # 忙碌判定在锁内（防 TOCTOU）：判定 → 截断 → 任务注册同临界区原子完成，
        # 并发双击时第二个请求进来任务已登记，必判 busy
        if _agent_busy(svc):
            return _error(409, "AGENT_BUSY", "Agent 正在回复，请稍后再试")
        msgs = svc.get_chat_messages()
        idx = next(
            (i for i in range(len(msgs) - 1, -1, -1)
             if msgs[i].get("sender") == "user"
             and str(msgs[i].get("kind") or "") != "system_action"),
            -1,
        )
        if idx < 0:
            return _error(400, "NO_USER_MESSAGE", "对话中没有可重答的用户消息")
        # ---- 截断前完成全部校验与前置解析（破坏性操作零副作用前置）----
        new_text = (body.text or "").strip()
        original = str(msgs[idx].get("text") or "")
        # 仅在非空且与原文不同时替换（相同视为未编辑）
        replace_with = new_text if (new_text and new_text != original) else None
        user_text = replace_with if replace_with is not None else original
        if not user_text.strip():
            return _error(400, "EMPTY_MESSAGE", "用户消息正文为空，无法重答")
        try:
            provider, model = _resolve_resend_target(body)
        except ValueError as e:
            return _error(400, "INVALID_CHAT_TARGET", str(e))
        history = _history_before(msgs, idx)
        # ---- 破坏性截断（先冲刷在途防抖写，版本闸拒绝 → 409 冲突）----
        await chat_tail_ops.flush_pending_saves(svc)
        try:
            entry = svc.truncate_chat_tail(idx, replace_with)
        except StateConflictError:
            return _error(409, "STATE_CONFLICT", "状态冲突：磁盘已有更新写入，请刷新后重试")
        if entry is None:  # 防御：校验后消息列表被动变化（理论不可达）
            return _error(400, "NO_USER_MESSAGE", "对话中没有可重答的用户消息")
        user_text = str(entry.get("text") or "")
        req = agent_routes.ChatRequest(
            message=user_text,
            provider=provider,
            model=model,
            ms_model=model if provider == "modelscope" else "",
            messages=history,
            thinking_level=(body.thinking_level or "").strip(),
        )
        # 内部标记（非公共契约）：用户消息已落盘在历史尾部，
        # 发送管线各落盘点据此守卫不重复持久化
        token = chat_tail_ops.user_message_persisted.set(True)
        try:
            result = chat_service.start_agent_task(req)
        except Exception as e:
            # 不可预检的失败（极小窗口）：结构化 500，不遗留孤儿任务
            return _error(500, "INTERNAL_ERROR", f"起任务失败: {e}")
        finally:
            chat_tail_ops.user_message_persisted.reset(token)
        result["model"] = model
        return result
