"""FC 工具执行与回喂（从 planner.py 拆出，批次5 文件瘦身）。

承载：
- Function Calling tool_calls 的执行循环（含 read_skill 短路、生图参数注入、过程时间线事件）
- 工具结果回喂消息的格式化与惰性压缩（token 治理）

planner.py 对下列符号保留同名委托，既有调用/测试路径不变。
"""
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.config import settings
from src.video_agent.core.sse_events import SSE_TOOL_FINISHED, SSE_TOOL_STARTED
from src.video_agent.core.token_budget import estimate_messages_tokens
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.tools.base import ToolResult

# 回喂消息的识别前缀（与 format_tool_results 首行保持一致）
FEEDBACK_MARKER = "（系统）本轮调用的工具已执行完毕，结果如下："
# 旧轮回喂被压缩后的占位文案
FEEDBACK_COMPRESSED = (
    "（系统）此前轮次工具读回的文档全文已从上下文移除以节约空间；"
    "其中的流程与约束仍须遵守，如确需复核原文请重新调用对应 read_* 工具。"
)

# read_* 系列：读回的全文必须完整回喂进上下文（渐进式披露的「借阅归还」）；
# 其他写入类工具只回报成功与否，避免重复携带大 JSON 膨胀上下文
FEEDBACK_FULL_TOOLS = {"read_skill", "read_project_doc", "read_uploaded_doc", "read_draft"}
# 单次回喂总量保险丝（read_* 各自已有 max_doc_chars 截断，这里防多文档叠加）
FEEDBACK_MAX_TOTAL_CHARS = 100000


def should_compress_feedback(messages: List[Dict[str, Any]]) -> bool:
    """惰性压缩决策：消息估算总量达到 token 预算的 feedback_compress_ratio
    才压缩旧轮全文回喂；未达到则保留全文保质量（短对话零损失）"""
    ratio = min(max(settings.feedback_compress_ratio, 0.0), 1.0)
    if ratio >= 1.0:
        return False
    budget = int(settings.context_window_size * settings.token_budget_ratio)
    threshold = int(budget * ratio)
    return estimate_messages_tokens(messages) >= threshold


def compress_prior_feedback(messages: List[Dict[str, Any]]) -> None:
    """把 messages 里已有的工具结果回喂消息压缩为占位文案（原地修改）。

    时机：新一轮回喂 append 之前调用，因此现存的所有回喂消息都属「旧轮」。
    read_* 全文只保留最近一轮，更早的以一句话占位——约束效力靠提示词延续，
    全文本身已写入草稿/文档，需要时模型可重新 read。
    """
    for m in messages:
        content = m.get("content", "")
        if m.get("role") == "user" and isinstance(content, str) \
                and content.startswith(FEEDBACK_MARKER):
            m["content"] = FEEDBACK_COMPRESSED


def render_read_result(name: str, data: Dict[str, Any]) -> str:
    """按 read_* 工具类型渲染读回全文"""
    if name == "read_draft":
        parts: List[str] = []
        for d in (data.get("drafts") or []):
            parts.append(
                f"【草稿 {d.get('index', '')}「{d.get('label', '')}」"
                f"（{d.get('group_title', '')}，draft_id={d.get('draft_id', '')}）】\n{d.get('prompt', '')}"
            )
        return "\n\n".join(parts) if parts else "（无内容）"
    doc_name = data.get("name", "")
    content = data.get("content", "") or "（空）"
    return f"【{doc_name}】\n{content}"


def format_tool_results(tool_results: List[Dict[str, Any]]) -> str:
    """把本轮 FC 工具执行结果格式化为回喂消息。

    read_* 工具携带读回的全文（Skill 流程/规格/剧本/草稿提示词），
    必须让模型在后续轮次真正看到，否则按需加载形同虚设。
    """
    lines: List[str] = [FEEDBACK_MARKER]
    total = 0
    for tr in tool_results:
        name = str(tr.get("name", ""))
        if not tr.get("ok"):
            lines.append(f"- {name}：执行失败 —— {tr.get('error') or '未知错误'}")
            continue
        if name not in FEEDBACK_FULL_TOOLS:
            lines.append(f"- {name}：执行成功")
            continue
        data = tr.get("data") or {}
        body = render_read_result(name, data)
        if total + len(body) > FEEDBACK_MAX_TOTAL_CHARS:
            lines.append(f"- {name}：执行成功（全文因总量超限未附，请勿重复读取，按已有信息继续）")
            continue
        total += len(body)
        lines.append(
            f"- {name} 执行成功，以下是读回的全文（后续任务必须遵守其中流程与约束，"
            f"不要重复调用同一工具）：\n{body}"
        )
    return "\n".join(lines) if len(lines) > 1 else ""


def describe_fc_tool(name: str, args: Dict[str, Any]) -> str:
    """FC 工具的中文简述（与 studio-actions 描述风格对齐）"""
    title = str(args.get("title") or "").strip()
    draft_id = str(args.get("draft_id") or "").strip()
    label = str(args.get("label") or "").strip()
    doc = str(args.get("key") or args.get("name") or "").strip()
    if name == "storyboard_create_group":
        return f"新建分组「{title or '未命名'}」"
    if name == "storyboard_patch_draft":
        return f"更新草稿「{label or draft_id or '当前草稿'}」"
    if name == "storyboard_add_draft":
        return f"新增草稿「{label or '未命名'}」"
    if name == "storyboard_delete_group":
        return f"删除分组 {args.get('group_id', '')}"
    if name == "storyboard_confirm_draft":
        return f"确认草稿「{label or draft_id or '当前草稿'}」"
    if name == "storyboard_media_to_chat":
        return "插入故事板媒体到对话输入框"
    if name == "read_draft":
        return f"读取草稿「{str(args.get('draft_id') or '未知')}」提示词全文"
    if name == "document_write":
        return f"写入文档「{doc or '未命名'}」"
    if name == "read_uploaded_doc":
        return f"读取上传文档「{str(args.get('name') or args.get('doc_id') or '未知')}」"
    if name == "read_skill":
        return f"加载 Skill「{str(args.get('name') or '未知')}」完整流程"
    if name == "read_project_doc":
        return f"读取规格文档「{str(args.get('name') or '未知')}」"
    if name in ("generate_image", "image_generate"):
        return "发起生图"
    if name == "generate_video":
        return "发起视频生成"
    if name == "workflow_pause":
        return "请求阶段确认"
    return f"执行工具 {name}"


class FCToolRunner:
    """执行 Function Calling 返回的 tool_calls（planner 的 FC 执行臂）"""

    def __init__(self, tool_manager) -> None:
        self.tool_manager = tool_manager

    async def execute(
        self, response: ChatResponse, image_provider: str = "", image_aspect_ratio: str = "",
        on_status=None, on_event=None, injected_skill: str = "",
    ) -> Tuple[int, str, List[str], List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
        """执行 Function Calling 返回的 tool_calls。
        返回 (applied_count, confirmation_message, image_urls, chat_inserts, action_log, tool_results)"""
        applied = 0
        confirmation = ""
        image_urls: List[str] = []
        chat_inserts: List[Dict[str, Any]] = []
        action_log: List[str] = []
        tool_results: List[Dict[str, Any]] = []
        tracer = AgentTracer.get_instance()
        for ci, call in enumerate(response.tool_calls):
            func = call.get("function", {}) if isinstance(call, dict) else {}
            name = func.get("name", "")
            args_raw = func.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}

            # 过程时间线：工具开始（前端渲染运行态条目）
            tool_event_id = str(call.get("id") or f"fc-{ci}") if isinstance(call, dict) else f"fc-{ci}"
            start_summary = describe_fc_tool(name, args)
            if on_event is not None:
                await on_event({
                    "type": SSE_TOOL_STARTED,
                    "id": tool_event_id,
                    "name": name,
                    "summary": start_summary,
                })
            _tool_t0 = time.monotonic()

            # --- 生图模型强制注入：用中间面板选中的 provider 覆盖 mock ---
            if name == "generate_image" and image_provider:
                if "adapter_provider" not in args or args.get("adapter_provider") in ("mock", "", None):
                    args["adapter_provider"] = image_provider
                    logger.info("[Planner] Injected image gen provider from draft: %s",
                                image_provider)
            # --- 画面比例注入：用中间面板选中的比例 ---
            if name == "generate_image" and image_aspect_ratio:
                if not args.get("aspect_ratio"):
                    args["aspect_ratio"] = image_aspect_ratio
                    logger.info("[Planner] Injected image gen aspect ratio from draft: %s",
                                image_aspect_ratio)

            # read_skill 短路：选中 Skill 全文已硬注入 system prompt，重复 read 只是
            # 浪费一轮工具往返 + 全文回喂 token（prompt 里的「不要再 read」靠模型自觉，此处硬保障）
            if name == "read_skill" and injected_skill:
                wanted_skill = str(args.get("name") or "").strip()
                if wanted_skill and wanted_skill == injected_skill.strip():
                    result = ToolResult(success=True, data={
                        "content": f"Skill「{wanted_skill}」全文已在本轮 system prompt 中注入，无需重复读取，直接遵循其中的规则即可。",
                        "already_injected": True,
                    })
                    logger.info(f"[Planner] read_skill 短路：「{wanted_skill}」已注入，跳过工具调用")
                else:
                    result = await self.tool_manager.invoke_tool(name, args)
            else:
                result = await self.tool_manager.invoke_tool(name, args)
            _tool_ms = (time.monotonic() - _tool_t0) * 1000
            if result.success:
                applied += 1
                if name == "workflow_pause":
                    confirmation = args.get("message", "请确认以上内容。")
                desc = describe_fc_tool(name, args)
                action_log.append(desc)
                # 推理过程可视化：每完成一个工具就推一条状态
                if on_status is not None:
                    await on_status(f"已完成：{desc}")
                # 过程时间线：工具完成 + trace 记录
                if on_event is not None:
                    await on_event({
                        "type": SSE_TOOL_FINISHED,
                        "id": tool_event_id,
                        "ok": True,
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": desc,
                    })
                tracer.record_action(name=name, summary=desc, elapsed_ms=_tool_ms, ok=True)
                tool_results.append({"name": name, "ok": True, "data": result.data})
                # --- 收集 generate_image 产出的图片 URL ---
                data = result.data
                if data and "image_urls" in data:
                    urls = data["image_urls"]
                    if isinstance(urls, list):
                        image_urls.extend(urls)
                # --- 收集 storyboard_media_to_chat 产出的对话输入框插入项 ---
                if data and "chat_inserts" in data:
                    inserts = data["chat_inserts"]
                    if isinstance(inserts, list):
                        chat_inserts.extend(inserts)
            else:
                logger.warning(f"[Planner] Tool '{name}' failed: {result.error}")
                if on_event is not None:
                    await on_event({
                        "type": SSE_TOOL_FINISHED,
                        "id": tool_event_id,
                        "ok": False,
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": str(result.error or "执行失败")[:120],
                    })
                tracer.record_action(
                    name=name, summary=start_summary, elapsed_ms=_tool_ms, ok=False,
                )
                tool_results.append({
                    "name": name, "ok": False,
                    "error": str(result.error or "执行失败")[:200],
                })
        return applied, confirmation, image_urls, chat_inserts, action_log, tool_results
