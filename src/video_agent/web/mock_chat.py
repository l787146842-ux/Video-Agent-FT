"""mock 供应商的流式聊天模拟（从 chat_service.py 拆出）。

仅调试/演示用：本地规则生成回复 + 模拟流式 delta 推送，
与真实供应商路径共用 executor / 记忆 / 持久化通道。
"""
import asyncio
import time
import uuid

from src.video_agent.core.sse_events import SSE_DELTA, SSE_DONE, SSE_STATUS, status_event
from src.video_agent.core import workflow_runtime
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
        # mock 路径同样携带轮次标识（同类全覆盖）；
        # 提前生成，供用户消息后的规格卡补落同轮聚合
        turn_id = uuid.uuid4().hex[:12]
        if use_studio_context:
            bind_attachments(svc, body.attachments)
            store_uploaded_docs(svc, body.attachments)
            # 铁律自动加载：每轮确保「执行铁律.md」独立文档存在（幂等）
            from src.video_agent.core import spec_rules

            if spec_rules.ensure_iron_rules_doc(svc.state_dict):
                svc.save_debounced()
            # 暂停回应结构化消费（与真实轨 consume_pause_response 同语义；
            # chat_consume 导入本模块，反向导入会成环，同下方规格卡先例内联）
            _pr = getattr(body, "pause_response", None) or {}
            _pid = str(_pr.get("pause_id") or "").strip()
            _inter_pm = svc.state_dict.get("interaction") or {}
            _pause_answered = None
            if _pid and str((_inter_pm.get("active_pause") or {}).get("pause_id") or "") == _pid:
                workflow_runtime.reduce_interaction(svc, pop_flags=("active_pause",))
                _pause_answered = {
                    "pause_id": _pid,
                    "value": str(_pr.get("value") or ""),
                    "label": str(_pr.get("label") or ""),
                }
            svc.add_chat_message(
                "user", user_text,
                doc_blocks=getattr(body, "doc_blocks", None) or None,
                skill_blocks=getattr(body, "skill_blocks", None) or None,
                pause_answered=_pause_answered,
                kind=getattr(body, "system_action", "") or "",
            )
            # v2 批2：挂起补卡机制退役；向导规格卡投影由 chat_service
            # 按 write_spec 提交结果于用户消息后落库（mock 轨同构）
        #自查补漏：mock 路径 status 同走 key 化（#1 同类全覆盖）
        await emit(status_event("agent.mockRunning", "mock 模式：本地规则生成…", {}))
        # 单轨化：mock 动作以结构化 dict 直达执行器，不经文本块解析
        visible, actions = mock_llm_reply(llm_user_text, svc.build_agent_context(body.asset_mode))
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
                turn_id=turn_id,
            )
            # 文档完成卡片：独立条目持久化，刷新后可重建（同轮 turnId 聚合）
            for doc_name in executor.documents_written:
                svc.add_chat_message("agent", "", doc_card=doc_name, turn_id=turn_id)
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
        "turn_id": turn_id,
    }})
    # 记忆系统：mock 路径同样记录（无 LLM 摘要，降级截取），按项目隔离（与 planner 真实路径对齐）
    MemoryManager.get_instance().record_dialog_background(
        user_text, visible, project_id=svc.active_project_id
    )
