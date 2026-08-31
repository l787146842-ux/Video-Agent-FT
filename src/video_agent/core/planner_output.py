"""轮次产出组装域。

承载：agent_loop 结束后的轮末组装——FC 闸机警告并入、暂停轮客观完成
记账、纯工具轮占位文案替换、收集器去重合并、PlannerResponse 构造。

response_factory 以 callable 注入（同 agent_loop 的 llm_call 惯例），
避免与 planner.py 循环导入；planner.py 传入 PlannerResponse 类本身。
"""
from typing import Any, Callable, Dict, List, Optional

from src.video_agent.core.agent_loop import AgentLoopResult
from src.video_agent.core.gates_cards import summary_already_visible
from src.video_agent.core.stage_deliverables import render_stage_deliverables


def _executed_tool_names(loop_result: AgentLoopResult) -> List[str]:
    """本轮 trace 中成功执行的工具名（保序，供成果渲染器判定）。

    trace 在 agent_loop 返回前已 finish_trace，steps[].actions[] 可用；
    无 trace（测试桩等）返回空列表。
    """
    names: List[str] = []
    trace = getattr(loop_result, "trace", None) or {}
    for step in (trace.get("steps") or []):
        for act in (step.get("actions") or []):
            if act.get("ok") and str(act.get("name") or "").strip():
                names.append(str(act["name"]))
    return names


def append_costly_retry_action(
    loop_result: AgentLoopResult,
    costly_failures: List[str],
) -> bool:
    """花钱生成失败不静默（Q22 裁决 2026-09-01）：轮末机械附一键重试选项卡。

    原因警告已由 fc_tool_runner 随 gate_warnings 上抛（用户可见），
    本函数只补确定性交互入口：重试 = 机械重发上一条用户消息。
    暂停确认轮/已有重试建议不叠加（避免双入口干扰定夺）；
    返回是否附加（供测试断言）。
    """
    if (
        costly_failures
        and not loop_result.confirmation
        and not any(
            str(a.get("kind") or "") == "retry"
            for a in loop_result.suggested_actions
        )
    ):
        loop_result.suggested_actions.append(
            {"kind": "retry", "label": "重试", "value": ""})
        return True
    return False


def assemble_response(
    loop_result: AgentLoopResult,
    *,
    executor: Any,
    response_factory: Callable[..., Any],
    fc_warnings_collector: Optional[List[str]] = None,
    action_log_collector: Optional[List[str]] = None,
    chat_inserts_collector: Optional[List[Dict[str, Any]]] = None,
    docs_written_collector: Optional[List[str]] = None,
    image_urls_collector: Optional[List[str]] = None,
    confirmation_options_collector: Optional[List[Dict[str, Any]]] = None,
    analysis_summary: str = "",
    aggregate_action_log: Optional[Callable[[List[str]], List[str]]] = None,
) -> Any:
    """轮末组装 PlannerResponse（planner.handle_message 尾段唯一落点）。

    FC 轨闸机警告并入 warnings；executor 与收集器
    的 chat_inserts/documents 按 URL/名称去重保序；文档卡片已即时可见，
    正文不重复补「本轮已写入文档」交代（防同屏双显）。
    """
    # FC 轨闸机文案并入结果 warnings（文本轨由 agent_loop 直接写入），
    # 前端据此渲染常驻警告行 +「本次放行」按钮（拦截可见，双轨对齐）
    if fc_warnings_collector:
        seen = set(loop_result.warnings)
        for w in fc_warnings_collector:
            if w and w not in seen:
                loop_result.warnings.append(w)
                seen.add(w)

    # 成果正文通道：本轮成功执行的阶段工具成果由层 9
    # 确定性渲染进正文（模型只短交代，成果展示不再依赖模型自觉）；
    # 判重内置——模型 prose 已含总结时不重复追加。
    _state = getattr(executor, "state", None) or {}
    _deliverable = render_stage_deliverables(_state, _executed_tool_names(loop_result))
    if _deliverable:
        _t = str(loop_result.text or "")
        _summary = str((_state.get("analysis") or {}).get("summary") or "")
        if not summary_already_visible(_t, _summary):
            loop_result.text = (
                f"{_t.rstrip()}\n\n{_deliverable}".strip() if _t.strip() else _deliverable
            )
    elif loop_result.confirmation and analysis_summary:
        # 无成果块命中时的历史语义兜底：暂停轮补一行客观事实（判重内置），
        # 防模型 prose 停留在执行前承诺导致后续轮次误判未执行而重跑执行器。
        _t = str(loop_result.text or "")
        if _t.strip() and "剧本分析已完成" not in _t:
            loop_result.text = _t.rstrip() + "\n\n（剧本分析已完成并存档工作台）"

    # 纯工具轮无总结文字时，用实际操作清单替换无信息量的占位文案：
    # 占位文案进入历史后模型看不出先前轮次做了什么（读文档/写文档/请求确认），
    # 用户下一条「确认」进来就会失去参照、从头重复同一套操作
    # 粗粒度聚合（阶段反馈不逐卡罗列）：聚合函数由调用方注入，
    # 保持 core 不依赖 web 层（与 executor_factory 回落模式同惯例）
    if aggregate_action_log is not None and loop_result.applied_actions and (
        not loop_result.text.strip() or "模型未输出总结文字" in loop_result.text
    ):
        merged_log = aggregate_action_log((action_log_collector or []) + executor.action_log)
        if merged_log:
            loop_result.text = (
                f"已执行 {loop_result.applied_actions} 个操作：" + "；".join(merged_log[:12])
            )

    # chat_inserts：FC 路径收集 + executor 收集，按 URL 去重
    merged_inserts: List[Dict[str, Any]] = []
    seen_urls = set()
    for it in ((chat_inserts_collector or []) + executor.chat_inserts):
        u = it.get("url")
        if u and u not in seen_urls:
            seen_urls.add(u)
            merged_inserts.append(it)
    # 文档卡片：文本轨 executor.documents_written + FC 轨 docs_written_collector，去重保序
    merged_docs: List[str] = []
    seen_docs = set()
    for dn in (executor.documents_written + (docs_written_collector or [])):
        if dn and dn not in seen_docs:
            seen_docs.add(dn)
            merged_docs.append(dn)

    # 阶段完成卡片粗粒度展示：连续同类操作合并（如「新建关键元素分组 ×3」），
    # 不逐张卡片罗列；随消息持久化与 done payload 一并下发
    full_log = (action_log_collector or []) + executor.action_log
    merged_action_log = aggregate_action_log(full_log) if aggregate_action_log is not None else full_log
    return response_factory(
        text=loop_result.text,
        applied_actions=loop_result.applied_actions,
        steps=loop_result.steps,
        warnings=loop_result.warnings,
        confirmation=loop_result.confirmation,
        documents_written=merged_docs,
        image_urls=image_urls_collector or [],
        chat_inserts=merged_inserts,
        action_log=merged_action_log,
        confirmation_options=loop_result.confirmation_options or (confirmation_options_collector or []),
        trace=loop_result.trace,
        suggested_actions=loop_result.suggested_actions,
    )
