"""mock 供应商的流式聊天模拟（批次5 从 chat_service.py 拆出）。

仅调试/演示用：本地规则生成回复 + 模拟流式 delta 推送，
与真实供应商路径共用 executor / 记忆 / 持久化通道。
"""
import asyncio
import time

from src.video_agent.core.sse_events import SSE_DELTA, SSE_DONE, SSE_STATUS
from src.video_agent.memory import MemoryManager
from src.video_agent.web.attachments import bind_attachments, store_uploaded_docs
from src.video_agent.web.mock_llm import mock_llm_reply


async def mock_stream(svc, executor, body, user_text, llm_user_text,
                      use_studio_context, emit, t0, meta_builder) -> None:
    """mock 供应商的流式模拟。

    meta_builder: (elapsed_secs, steps, applied) -> str，由 chat_service 注入
    （耗时角标文案与真实路径保持一致）。
    注意：本函数在 svc.lock 内调用 executor.execute（同步、不重复取锁）。
    """
    async with svc.lock:
        if use_studio_context:
            bind_attachments(svc, body.attachments)
            store_uploaded_docs(svc, body.attachments)
            svc.add_chat_message(
                "user", user_text,
                doc_blocks=getattr(body, "doc_blocks", None) or None,
                skill_blocks=getattr(body, "skill_blocks", None) or None,
            )
        await emit({"type": SSE_STATUS, "text": "mock 模式：本地规则生成…"})
        raw_reply = mock_llm_reply(llm_user_text, svc.build_agent_context(body.asset_mode))
        actions = executor.parse_actions_from_reply(raw_reply)
        visible = executor.strip_action_blocks(raw_reply) or raw_reply
        for i in range(0, len(visible), 8):
            await emit({"type": SSE_DELTA, "text": visible[i:i + 8]})
            await asyncio.sleep(0.02)
        applied = executor.execute(actions)
        if use_studio_context:
            svc.add_chat_message(
                "agent", visible, model_name=body.model or "",
                meta=meta_builder(time.monotonic() - t0, 1, applied),
                applied_actions=applied,
                action_log=executor.action_log,
            )
            # 文档完成卡片：独立条目持久化，刷新后可重建
            for doc_name in executor.documents_written:
                svc.add_chat_message("agent", "", doc_card=doc_name)
    await emit({"type": SSE_DONE, "payload": {
        "text": visible,
        "applied_actions": applied,
        "steps": 1,
        "warnings": ["当前为 mock 供应商，回复由本地规则生成，未调用真实 LLM"],
        "confirmation": "",
        "documents_written": executor.documents_written,
        "chat_inserts": executor.chat_inserts,
        "state": svc.get_full_snapshot(),
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
    }})
    # 记忆系统：mock 路径同样记录（无 LLM 摘要，降级截取），按项目隔离（与 planner 真实路径对齐）
    MemoryManager.get_instance().record_dialog_background(
        user_text, visible, project_id=svc.active_project_id
    )
