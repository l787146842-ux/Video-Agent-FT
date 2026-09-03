"""FC 工具结果回喂家族。

承载：工具结果回喂消息的格式化（read_* 全文「借阅归还」、执行器 detail 随喂、
view_storyboard_media 多模态回喂）与旧轮回喂的惰性压缩/图片剥离（token 治理）
+ 已投影工具结果的消化（tool-result 消化杠杆）+ FC 工具中文简述。

fc_tool_runner.py 与本模块消费方一律直连本模块（re-export 壳已随批次 E3 收敛删除）。
"""
import re
from typing import Any, Dict, List, Union

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.context_prune import prune_tool_feedback
from src.video_agent.core.token_budget import estimate_messages_tokens
from src.video_agent.utils.prompts import load_prompt_section

# 回喂模板外置：prompts/planner/feedback.md 为单一事实源（M-2 同口径：
# 代码不内联逐字兜底——那是双源漂移根因；分节缺失时仅 warning + 最小占位）
_FEEDBACK_FILE = "planner/feedback.md"


def _load_feedback_section(key: str, minimal: str) -> str:
    """外置分节为唯一文案源：分节在场即原样返回（与
    load_prompt_section 相等，供同源断言）；缺失时不内联逐字正式文案
    （双源漂移根因），仅 logger.warning + 最小功能性占位。"""
    text = load_prompt_section(_FEEDBACK_FILE, key)
    if text:
        return text
    logger.warning(f"[fc_feedback] prompts/{_FEEDBACK_FILE}::{key} 分节缺失，使用最小占位")
    return minimal


# 回喂消息的识别前缀（与 format_tool_results 首行保持一致）
FEEDBACK_MARKER = _load_feedback_section("FEEDBACK_MARKER", "（系统）本轮工具执行结果：")
# 旧轮回喂被压缩后的占位文案
FEEDBACK_COMPRESSED = _load_feedback_section(
    "FEEDBACK_COMPRESSED", "（系统）旧轮工具回喂已压缩。")
# 旧轮图片剥离后的占位说明（feedback.md::FEEDBACK_IMAGES_STRIPPED，
# 与 FEEDBACK_COMPRESSED 对称：只陈述客观事实 + 可执行恢复路径）
FEEDBACK_IMAGES_STRIPPED = _load_feedback_section(
    "FEEDBACK_IMAGES_STRIPPED", "（系统）此前轮次加载的故事板图片已从上下文移除。")
# read_* 全文超单次回喂总量上限时的客观数据行后缀
#（feedback.md::READ_RESULT_BODY_OMITTED；只陈述事实，不嵌引导说教）
READ_RESULT_BODY_OMITTED = _load_feedback_section(
    "READ_RESULT_BODY_OMITTED", "执行成功（全文未附）")

# read_* 系列：读回的全文必须完整回喂进上下文（渐进式披露的「借阅归还」）；
# 其他写入类工具只回报成功与否，避免重复携带大 JSON 膨胀上下文
FEEDBACK_FULL_TOOLS = {"read_skill", "read_project_doc", "read_uploaded_doc", "read_draft", "read_state_group"}
# 按需调图工具：读回的图片以多模态 parts 回喂（模型真正「看到」画面）
FEEDBACK_IMAGE_TOOL = "view_storyboard_media"
# 单次回喂总量保险丝（read_* 各自已有 max_doc_chars 截断，这里防多文档叠加）
FEEDBACK_MAX_TOTAL_CHARS = 100000

# 结果已完整投影进工作台状态 JSON 的写类工具：只有它们的回喂行才可被消化。
# 读回类（read_*）与调图（view_storyboard_media）的结果不在状态 JSON 里，
# 消化即丢信息，硬排除在外；失败行同样不消化（错误信息模型需要）
PROJECTED_STATE_TOOLS = frozenset({
    "storyboard_create_group", "storyboard_patch_draft", "storyboard_add_draft",
    "storyboard_delete_group", "storyboard_confirm_draft", "document_write",
})
# 消化后的指针文案：保留工具名+成败摘要，指向状态 JSON 事实源
#（外置 feedback.md::DIGEST_POINTER；{name} 为 str.format 占位，非 {{var}} 模板）
DIGEST_POINTER = _load_feedback_section(
    "DIGEST_POINTER", "{name}：执行成功（详情已省略，最新状态以工作台状态 JSON 为准）")
# 失败结构化回喂的建议语族（外置 feedback.md::FAILURE_HINT_*，
# 分支判定在本模块 compose_failure_feedback，文案单一事实源在分节）
FAILURE_HINT_REPEAT = _load_feedback_section(
    "FAILURE_HINT_REPEAT", "该工具已连续失败 2 次，不得再次重试；可向用户说明原因。")
FAILURE_HINT_VALIDATION = _load_feedback_section(
    "FAILURE_HINT_VALIDATION", "入参/定位问题：修正入参后再试，不得用原参重试。")
FAILURE_HINT_RETRYABLE = _load_feedback_section(
    "FAILURE_HINT_RETRYABLE", "生产端标注该失败可重试：可重试一次。")
FAILURE_HINT_NON_RETRYABLE = _load_feedback_section(
    "FAILURE_HINT_NON_RETRYABLE", "该失败不宜原参盲重试：可向用户说明困难。")
FAILURE_HINT_DEFAULT = _load_feedback_section(
    "FAILURE_HINT_DEFAULT", "可调整参数后重试一次，或先向用户说明困难。")
# 可消化行识别：回喂正文行「- 工具名：执行成功…」（与 format_tool_results 一致）
_DIGEST_LINE_RE = re.compile(r"^- ([A-Za-z_][A-Za-z0-9_]*)：执行成功")


def should_compress_feedback(messages: List[Dict[str, Any]], context_window: int = 0) -> bool:
    """惰性压缩决策：消息估算总量达到 token 预算的 feedback_compress_ratio
    才压缩旧轮全文回喂；未达到则保留全文保质量（短对话零损失）。

    预算按当前模型窗口计算（传 context_window），
    未传/传 0 回落全局 settings.context_window_size（兼容旧调用）。"""
    ratio = min(max(settings.feedback_compress_ratio, 0.0), 1.0)
    if ratio >= 1.0:
        return False
    window = context_window if context_window and context_window > 0 else settings.context_window_size
    budget = int(window * settings.token_budget_ratio)
    threshold = int(budget * ratio)
    return estimate_messages_tokens(messages) >= threshold


def compress_prior_feedback(
    messages: List[Dict[str, Any]], keep_recent: int = 2,
) -> None:
    """把 messages 里已有的工具结果回喂消息压缩为占位文案（原地修改）。

    时机：新一次回喂 append 之前调用，因此现存的所有回喂消息都属「旧轮」。
    read_* 全文只保留最近 keep_recent 条（近因保护：与
    digest_projected_tool_results 的 keep_recent 语义对齐），更早的以一句话
    占位——约束效力靠提示词延续，全文本身已写入草稿/文档，需要时模型
    可重新 read。
    多模态回喂（含图片 parts 的 list content）同样压成纯文本占位，
    旧轮图片不再占用 vision token。
    """
    fb_idx = [
        i for i, m in enumerate(messages)
        if m.get("role") == "user" and (
            (isinstance(m.get("content"), str)
             and str(m["content"]).startswith(FEEDBACK_MARKER))
            or (isinstance(m.get("content"), list)
                and next((p.get("text", "") for p in m["content"]
                          if isinstance(p, dict) and p.get("type") == "text"),
                         "").startswith(FEEDBACK_MARKER)))
    ]
    eligible = fb_idx[:-keep_recent] if keep_recent > 0 else fb_idx
    for i in eligible:
        messages[i]["content"] = FEEDBACK_COMPRESSED


def digest_projected_tool_results(
    messages: List[Dict[str, Any]],
    max_chars: int = 0,
    keep_recent: int = 2,
) -> int:
    """tool-result 消化（最安全杠杆）：历史中已投影进状态 JSON 的写类工具
    结果回喂行超过 max_chars 字符时，替换为「摘要 + 状态已在工作台 JSON」指针。

    硬约束（丢信息风险归零）：
    - 只消化 PROJECTED_STATE_TOOLS 白名单内的工具行（结果已完整投影进
      每轮刷新的工作台状态 JSON）；read_* 全文/调图/失败行一律不碰；
    - 最近 keep_recent 条回喂保留原文（模型正在依据它们工作）；
    - max_chars <= 0 整体关闭（settings.tool_result_digest_chars=0 一键关）。
    原地修改，返回被消化的行数（幂等：已消化行短于阈值不会二次命中）。
    """
    if max_chars <= 0:
        return 0
    fb_idx = []
    for i, m in enumerate(messages):
        content = m.get("content", "")
        if m.get("role") != "user" or not isinstance(content, str):
            continue
        if content.startswith(FEEDBACK_MARKER):
            fb_idx.append(i)
    # 最近 keep_recent 条回喂保留原文
    eligible = fb_idx[:-keep_recent] if keep_recent > 0 else fb_idx
    digested = 0
    for i in eligible:
        m = messages[i]
        out_lines: List[str] = []
        changed = False
        for line in str(m.get("content", "")).splitlines():
            hit = _DIGEST_LINE_RE.match(line)
            if (hit and hit.group(1) in PROJECTED_STATE_TOOLS
                    and len(line) > max_chars):
                out_lines.append("- " + DIGEST_POINTER.format(name=hit.group(1)))
                digested += 1
                changed = True
            else:
                out_lines.append(line)
        if changed:
            m["content"] = "\n".join(out_lines)
    return digested


def strip_prior_feedback_images(messages: List[Dict[str, Any]]) -> None:
    """把旧轮多模态回喂里的图片 parts 移除，只保留文本（原地修改）。

    时机：新一次含图片的回喂 append 之前。上下文里始终只保留最近一次
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
        kept.append({"type": "text", "text": FEEDBACK_IMAGES_STRIPPED})
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
            # （一句话总结只报「执行成功」被模型吞掉）
            data = tr.get("data") or {}
            detail = str(data.get("detail") or "").strip()
            # 上下文剪枝：只剪回喂进 history 的副本，白名单起步
            # （生成类大返回）；写类工具不在白名单，其回喂行归 digest 杠杆管
            detail = prune_tool_feedback(name, detail)
            if detail and total + len(detail) <= FEEDBACK_MAX_TOTAL_CHARS:
                total += len(detail)
                lines.append(f"- {name}：执行成功，{detail}")
                continue
            lines.append(f"- {name}：执行成功")
            continue
        data = tr.get("data") or {}
        body = render_read_result(name, data)
        # 上下文剪枝：read_* 全文回喂超阈保留头尾、中段换 PRUNE 标记行
        # （start= 续读兜底）；只剪回喂副本，工具原始返回/state/产物文件不动
        body = prune_tool_feedback(name, body)
        if total + len(body) > FEEDBACK_MAX_TOTAL_CHARS:
            # P3 状态即数据：只陈述客观事实（全文未附及原因），不嵌引导说教
            lines.append(f"- {name}：{READ_RESULT_BODY_OMITTED}")
            continue
        total += len(body)
        # P3 状态即数据 + 语气转化：数据体只留客观结果，READ_RESULT_NOTE 引导语已退役
        lines.append(f"- {name} 执行成功，全文如下：\n{body}")
    if len(lines) <= 1:
        return ""
    text = "\n".join(lines)
    if not image_parts:
        return text
    return (
        [{"type": "text", "text": text}]
        + image_parts
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


def compose_failure_feedback(
    name: str, error_text: str, fail_count: int,
    error_code: str = "", retryable: bool = False,
) -> str:
    """执行器失败结构化回喂（层 8）：客观报告 + 单句下一步。

    T5 结构化错误轴：生产端已标注 error_code 时直接用作分类前缀，
    未标注回落文本分类（classify_tool_failure）；retryable 微调重试建议。
    同工具第二次失败升级建议为「不得重试、向用户说明」，
    掐掉主模型盲重试空转。
    """
    kind = str(error_code or "") or classify_tool_failure(error_text)
    raw = str(error_text or "未知错误")[:120]
    if fail_count >= 2:
        hint = FAILURE_HINT_REPEAT
    elif kind == "validation":
        hint = FAILURE_HINT_VALIDATION
    elif retryable:
        hint = FAILURE_HINT_RETRYABLE
    elif kind in ("canvas", "other"):
        hint = FAILURE_HINT_NON_RETRYABLE
    else:
        hint = FAILURE_HINT_DEFAULT
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
    if name == "image_generate":
        if str(args.get("mode") or "batch").strip().lower() == "single":
            return "对话内单张生图"
        return "发起生图"
    if name == "generate_video":
        return "发起视频生成"
    if name == "workflow_pause":
        return "请求阶段确认"
    return f"执行工具 {name}"
