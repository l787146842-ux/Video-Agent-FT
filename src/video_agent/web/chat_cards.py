# -*- coding: utf-8 -*-
"""聊天卡片纯辅助函数（任务 #12 交叉验证：chat_service.py 行数棘轮越线等价归位）。

doc_written 打戳与视频内联卡条目过滤均为无副作用纯函数，供
chat_service._real_stream 透传/持久化路径消费；独立成模块同时便于单测钉死。
"""
from typing import Any, Dict, Optional

from src.video_agent.core.sse_events import SSE_DOC_WRITTEN


def _stamp_doc_written(payload: Optional[Dict[str, Any]], turn_id: str) -> Dict[str, Any]:
    """ ：doc_written 即显事件打戳本轮 turn_id。

    发射端（agent_loop/fc_tool_runner）无 turn_id 概念，打戳归透传层
    （turn_id 在 _real_stream 起始生成）；前端即显卡据此与 done 主消息
    同 turnId 严格归组（显式 id 原则延伸，不再依赖相邻兜底）。
    """
    out = dict(payload or {"type": SSE_DOC_WRITTEN})
    out["turn_id"] = turn_id
    return out


def _video_card_items(payload: Dict[str, Any]) -> list:
    """视频内联预览卡条目过滤（done payload chat_inserts 中 kind=video 且带 url 项）。

    与 imageCard 契约对称：瞬态 SSE 不作唯一可见性，随历史持久化后
    刷新/replay 不丢卡。
    """
    return [
        it for it in (payload.get("chat_inserts") or [])
        if isinstance(it, dict)
        and str(it.get("kind") or "") == "video"
        and str(it.get("url") or "")
    ]
