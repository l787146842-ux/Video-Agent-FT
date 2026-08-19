"""FC 工具结果回喂家族（八轮 B1 自 fc_tool_runner.py 切出，零行为变更）。

承载：工具结果回喂消息的格式化（read_* 全文「借阅归还」、执行器 detail 随喂、
view_storyboard_media 多模态回喂）与旧轮回喂的惰性压缩/图片剥离（token 治理，
业界基准 C3 唯一代码落点）+ FC 工具中文简述。

fc_tool_runner.py 对本模块全部符号保留 re-export（壳清单登记于该文件尾部注释，
13.7 惯例），既有调用/测试的 import 路径不变。
"""
from typing import Any, Dict, List, Union

from src.video_agent.config import settings
from src.video_agent.core.token_budget import estimate_messages_tokens
from src.video_agent.utils.prompts import load_prompt_section

# 回喂模板外置（814R1 恢复）：prompts/planner/feedback.md 为单一事实源，代码留内置兜底
_FEEDBACK_FILE = "planner/feedback.md"

# 回喂消息的识别前缀（与 format_tool_results 首行保持一致）
FEEDBACK_MARKER = load_prompt_section(_FEEDBACK_FILE, "FEEDBACK_MARKER") or (
    "（系统）本轮调用的工具已执行完毕，结果如下：")
# 旧轮回喂被压缩后的占位文案
FEEDBACK_COMPRESSED = load_prompt_section(_FEEDBACK_FILE, "FEEDBACK_COMPRESSED") or (
    "（系统）此前轮次工具读回的文档全文已从上下文移除以节约空间；"
    "其中的流程与约束仍须遵守，如确需复核原文请重新调用对应 read_* 工具。"
)

# read_* 系列：读回的全文必须完整回喂进上下文（渐进式披露的「借阅归还」）；
# 其他写入类工具只回报成功与否，避免重复携带大 JSON 膨胀上下文
FEEDBACK_FULL_TOOLS = {"read_skill", "read_project_doc", "read_uploaded_doc", "read_draft"}
# 按需调图工具：读回的图片以多模态 parts 回喂（模型真正「看到」画面）
FEEDBACK_IMAGE_TOOL = "view_storyboard_media"
# 单次回喂总量保险丝（read_* 各自已有 max_doc_chars 截断，这里防多文档叠加）
FEEDBACK_MAX_TOTAL_CHARS = 100000


def should_compress_feedback(messages: List[Dict[str, Any]], context_window: int = 0) -> bool:
    """惰性压缩决策：消息估算总量达到 token 预算的 feedback_compress_ratio
    才压缩旧轮全文回喂；未达到则保留全文保质量（短对话零损失）。

    814R1 恢复：预算按当前模型窗口计算（传 context_window），
    未传/传 0 回落全局 settings.context_window_size（兼容旧调用）。"""
    ratio = min(max(settings.feedback_compress_ratio, 0.0), 1.0)
    if ratio >= 1.0:
        return False
    window = context_window if context_window and context_window > 0 else settings.context_window_size
    budget = int(window * settings.token_budget_ratio)
    threshold = int(budget * ratio)
    return estimate_messages_tokens(messages) >= threshold


def compress_prior_feedback(messages: List[Dict[str, Any]]) -> None:
    """把 messages 里已有的工具结果回喂消息压缩为占位文案（原地修改）。

    时机：新一轮回喂 append 之前调用，因此现存的所有回喂消息都属「旧轮」。
    read_* 全文只保留最近一轮，更早的以一句话占位——约束效力靠提示词延续，
    全文本身已写入草稿/文档，需要时模型可重新 read。
    多模态回喂（含图片 parts 的 list content）同样压成纯文本占位，
    旧轮图片不再占用 vision token。
    """
    for m in messages:
        content = m.get("content", "")
        if m.get("role") != "user":
            continue
        if isinstance(content, str) and content.startswith(FEEDBACK_MARKER):
            m["content"] = FEEDBACK_COMPRESSED
        elif isinstance(content, list):
            first_text = next(
                (p.get("text", "") for p in content
                 if isinstance(p, dict) and p.get("type") == "text"),
                "",
            )
            if first_text.startswith(FEEDBACK_MARKER):
                m["content"] = FEEDBACK_COMPRESSED


def strip_prior_feedback_images(messages: List[Dict[str, Any]]) -> None:
    """把旧轮多模态回喂里的图片 parts 移除，只保留文本（原地修改）。

    时机：新一轮含图片的回喂 append 之前。上下文里始终只保留最新一轮
    加载的图片：模型逐条草稿「调图 → 写提示词 → 调下一批图」，旧图对后续
    推理无价值且 vision token 昂贵，剥离后模型需要时可重新调用加载。
    """
    for m in messages:
        content = m.get("content", "")
        if m.get("role") != "user" or not isinstance(content, list):
            continue
        if not any(isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            continue
        kept = [p for p in content if not (isinstance(p, dict) and p.get("type") == "image_url")]
        kept.append({
            "type": "text",
            "text": "（系统）此前轮次加载的故事板图片已从上下文移除以节约空间；"
                     "如后续仍需看到它们，重新调用 view_storyboard_media 加载。",
        })
        m["content"] = kept


def render_read_result(name: str, data: Dict[str, Any]) -> str:
    """按 read_* 工具类型渲染读回全文"""
    if name == "read_draft":
        parts: List[str] = []
        for d in (data.get("drafts") or []):
            parts.append(
                f"【草稿 {d.get('index', '')}「{d.get('label', '')}」"
                f"（{d.get('group_title', '')}，draft_id={d.get('draft_id', '')}）】\n{d.get('prompt', '')}"
            )
        return "\n".join(parts) if parts else "（无内容）"
    doc_name = data.get("name", "")
    content = data.get("content", "") or "（空）"
    return f"【{doc_name}】\n{content}"


def format_tool_results(tool_results: List[Dict[str, Any]]) -> Union[str, List[Dict[str, Any]]]:
    """把本轮 FC 工具执行结果格式化为回喂消息。

    read_* 工具携带读回的全文（Skill 流程/规格/剧本/草稿提示词），
    必须让模型在后续轮次真正看到，否则按需加载形同虚设。
    view_storyboard_media 携带读回的图片（data URI）时，返回多模态
    content parts（文本 + image_url），让模型真正「看到」画面。
    """
    lines: List[str] = [FEEDBACK_MARKER]
    image_parts: List[Dict[str, Any]] = []
    total = 0
    for tr in tool_results:
        name = str(tr.get("name", ""))
        if not tr.get("ok"):
            lines.append(f"- {name}：执行失败 —— {tr.get('error') or '未知错误'}")
            continue
        if name == FEEDBACK_IMAGE_TOOL:
            data = tr.get("data") or {}
            imgs = data.get("images") or []
            for im in imgs:
                if not isinstance(im, dict) or not im.get("data_uri"):
                    continue
                image_parts.append({
                    "type": "text",
                    "text": f"[图片：{im.get('label', '')}]（draft_id={im.get('draft_id', '')}）",
                })
                image_parts.append({"type": "image_url", "image_url": {"url": im["data_uri"]}})
            lines.append(f"- {name}：执行成功，已加载 {len(imgs)} 张图片（紧随本段文字之后，可直接看到画面）")
            for n in (data.get("notes") or []):
                lines.append(f"  · {n}")
            continue
        if name not in FEEDBACK_FULL_TOOLS:
            # 执行器类工具（script_analyze 等）的 detail 必须随回喂传给模型
            # （3333 事故：一句话总结只报「执行成功」被模型吞掉）
            data = tr.get("data") or {}
            detail = str(data.get("detail") or "").strip()
            if detail and total + len(detail) <= FEEDBACK_MAX_TOTAL_CHARS:
                total += len(detail)
                lines.append(f"- {name}：执行成功，{detail}")
                continue
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
    if len(lines) <= 1:
        return ""
    text = "\n".join(lines)
    if not image_parts:
        return text
    return (
        [{"type": "text", "text": text}]
        + image_parts
        + [{
            "type": "text",
            "text": (
                "（系统）以上图片仅供当前正在处理的草稿使用；写完对应提示词后，"
                "处理下一条草稿时请重新调用 view_storyboard_media 加载需要的图片，"
                "不要凭记忆描述已不在上下文中的画面。"
            ),
        }]
    )


def classify_tool_failure(error_text: str) -> str:
    """执行器失败客观分类（层 8 结构化回喂用）。"""
    t = str(error_text or "")
    if "无法解析" in t or "未返回 JSON" in t or "非 JSON" in t:
        return "output_format"
    if "超时" in t or "timeout" in t.lower():
        return "timeout"
    if "HTTP 5" in t or "流式请求失败" in t or "空内容" in t:
        return "upstream"
    return "other"


def compose_failure_feedback(name: str, error_text: str, fail_count: int) -> str:
    """执行器失败结构化回喂（层 8）：客观报告 + 单句下一步。

    同工具第二次失败升级建议为「不得重试、向用户说明」，
    掐掉主模型盲重试空转。
    """
    kind = classify_tool_failure(error_text)
    raw = str(error_text or "未知错误")[:120]
    if fail_count >= 2:
        hint = "不得再次重试该工具，向用户说明原因并给出替代选择"
    else:
        hint = "可调整参数后重试一次，或先向用户说明困难"
    return f"[{kind}] {raw} 建议：{hint}"


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
    if name == "view_storyboard_media":
        n = len(args.get("draft_ids") or []) if isinstance(args.get("draft_ids"), list) else 0
        return f"加载故事板图片进上下文（{n} 个目标）" if n else "加载故事板图片进上下文"
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
    if name in ("workflow_pause", "request_confirmation"):
        return "请求阶段确认"
    return f"执行工具 {name}"
