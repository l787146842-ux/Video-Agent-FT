"""FC 响应合并域。

LLM 响应中 FC tool_calls 的执行与收集器合并胶水：执行委托注入的
execute_fn（Planner._execute_fc_tools，测试可 monkeypatch），
暂停确认经 confirmation_collector 结构化上抛（对齐 AskUserQuestion 范式，
不再合成文本动作块）；各收集器跨多步累积（图片/插入媒体/操作日志/
确认选项/文档/闸机文案）。
"""
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple


async def merge_fc_response(
    response: Any,
    execute_fn: Callable[..., Awaitable[Tuple]],
    *,
    image_urls_collector: Optional[List[str]] = None,
    chat_inserts_collector: Optional[List[Dict[str, Any]]] = None,
    action_log_collector: Optional[List[str]] = None,
    confirmation_options_collector: Optional[List[Dict[str, Any]]] = None,
    docs_written_collector: Optional[List[str]] = None,
    fc_warnings_collector: Optional[List[str]] = None,
    image_provider: str = "",
    image_aspect_ratio: str = "",
    on_status=None,
    on_event=None,
    injected_skill: str = "",
    selected_draft_id: str = "",
    selected_type: str = "",
    gate_override: Any = False,
    confirmation_collector: Optional[Dict[str, Any]] = None,
) -> Tuple:
    """处理 LLM 响应中的 FC tool_calls。

    返回 (content, finish_reason, fc_applied, tool_results, fc_warnings)，
    tool_results: [{name, ok, data, error}] 供回喂进对话上下文；
    fc_warnings: 本批闸机拦截/豁免的用户可见文案。
    暂停确认经 confirmation_collector 结构化上抛（{message, options, pause_id}）。
    """
    if response.tool_calls:
        # 前 10 字段位置解包兼容（测试桩可返纯 10 元组）；第 11 尾部字段
        # pause_id（问即停，ADR-0006）按长取值，缺失回落空串
        _fc_res = tuple(await execute_fn(
            response, image_provider=image_provider, image_aspect_ratio=image_aspect_ratio,
            on_status=on_status, on_event=on_event, injected_skill=injected_skill,
            selected_draft_id=selected_draft_id, selected_type=selected_type,
            gate_override=gate_override,
        ))
        (fc_applied, fc_confirmation, image_urls,
         chat_inserts, fc_action_log, fc_confirmation_options,
         fc_tool_results, fc_docs_written, fc_warnings,
         fc_pause_overflow) = _fc_res[:10]
        fc_pause_id = str(_fc_res[10] or "") if len(_fc_res) > 10 else ""
        if image_urls_collector is not None:
            image_urls_collector.extend(image_urls)
        if chat_inserts_collector is not None:
            chat_inserts_collector.extend(chat_inserts)
        if action_log_collector is not None:
            action_log_collector.extend(fc_action_log)
        if confirmation_options_collector is not None:
            confirmation_options_collector.extend(fc_confirmation_options)
        if docs_written_collector is not None:
            docs_written_collector.extend(fc_docs_written)
        if fc_warnings_collector is not None:
            fc_warnings_collector.extend(fc_warnings)
        if fc_confirmation or fc_pause_id:
            # 确认结构化直通：文案+选项+pause_id 写入 collector 随 5 元组上抛
            # agent_loop，不合成文本动作块回绕解析；正文原样返回
            if confirmation_collector is not None:
                confirmation_collector["message"] = fc_confirmation
                confirmation_collector["options"] = fc_confirmation_options
                # 三通道分离 B：超长 pause message 原文随 collector 上抛，
                # 经 _extra.pause_overflow 由 agent_loop 追加进正文
                if fc_pause_overflow:
                    confirmation_collector["overflow"] = fc_pause_overflow
                # 问即停：发行点签发的 pause_id 随同上抛（幂等登记依据）
                if fc_pause_id:
                    confirmation_collector["pause_id"] = fc_pause_id
            # 空正文兜底：FC 模型常只发暂停工具不带正文，确认文案作可见正文
            visible = (response.content or "").strip()
            if not visible:
                visible = fc_confirmation
            # 确认轮返回 execute_fn 已解出的真实 fc_applied——暂停轮的
            # 工具执行事实如实入账（停止相位/空输出重试守卫/
            # applied_actions/trace）。
            return visible, response.finish_reason, fc_applied, fc_tool_results, fc_warnings
        return response.content, response.finish_reason, fc_applied, fc_tool_results, fc_warnings
    return response.content, response.finish_reason, 0, [], []
