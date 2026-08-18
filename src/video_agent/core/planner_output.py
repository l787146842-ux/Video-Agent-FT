"""轮次产出组装域（八轮 B2 自 planner.py 切出）。

承载：agent_loop 结束后的轮末组装——FC 闸机警告并入、暂停轮客观完成
记账、纯工具轮占位文案替换、双轨收集器去重合并、PlannerResponse 构造。

response_factory 以 callable 注入（同 agent_loop 的 llm_call 惯例），
避免与 planner.py 循环导入；planner.py 传入 PlannerResponse 类本身。
"""
from typing import Any, Callable, Dict, List, Optional

from src.video_agent.core.agent_loop import AgentLoopResult


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

    双轨对齐：FC 轨闸机警告并入 warnings；文本轨 executor 与 FC 轨收集器
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

    # 暂停轮客观完成记账（0818 架构板正批 E3 保留）：模型 prose 可能停留在
    # 执行前承诺（「接下来我先解析」），历史只含文本时下一轮会误判未执行而
    # 重跑执行器；补一行客观事实（判重内置）。总结展示不再平台强注入。
    if loop_result.confirmation and analysis_summary:
        _t = str(loop_result.text or "")
        if _t.strip() and "剧本分析已完成" not in _t:
            loop_result.text = _t.rstrip() + "\n\n（剧本分析已完成并存档工作台）"

    # 纯工具轮无总结文字时，用实际操作清单替换无信息量的占位文案：
    # 占位文案进入历史后模型看不出上一轮做了什么（读文档/写文档/请求确认），
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

    # chat_inserts：FC 路径收集 + 文本解析路径 executor 收集，按 URL 去重
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
