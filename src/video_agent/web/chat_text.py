"""聊天文本纯函数块（M7：从 chat_service.py 拆出）。

确认/审阅信号判定、历史截断、逐卡枚举压缩——均为无状态纯函数，
不依赖 FastAPI/StateManager，便于单测与复用。
chat_service.py 保留这些名字的 re-export 以兼容既有导入。
"""
import re
from typing import Dict, List

# ---------- 确认/审阅信号语义（P1-2 修复：只有确认/选择类消息才晋升草稿） ----------

# 短消息级确认词（独立成句的「好/可以/OK/行」等）
_SHORT_CONFIRM = {
    "确认", "确认。", "继续", "继续。", "可以", "可以。", "可以的",
    "好", "好的", "好。", "好的。", "没问题", "没问题。", "ok", "ok。",
    "行", "行。", "同意", "通过", "就按这个", "就这么办",
}
# 任意位置出现即视为确认信号的关键词（含确认向导选项 label 的常见开头）
_CONFIRM_KEYWORDS = (
    "确认", "继续", "没问题", "同意", "就按", "采用", "通过",
    "生成", "出图", "开始为", "选择", "保持", "可以，", "按这个",
)
# 选择式表达：选/用 第 N 个、第 N 项、2 号 等
_SELECT_RE = re.compile(
    r"(选|用|点)[择用]?\s*(第\s*[一二三四五六七八九十\d]+\s*[个项条号]|\d+\s*[号个项条])"
)
# 审阅信号（解除 storyboard_pending 用）：确认信号或涉及故事板内容的调整表达
_REVIEW_KEYWORDS = (
    "调整", "修改", "改成", "改为", "换成", "增加", "添加", "新增", "删除", "移除",
    "元素", "分镜", "镜头", "音频", "角色", "场景", "道具", "标题", "描述",
    "结构", "拆分", "草案", "提示词", "规格", "时长", "画幅", "风格", "声音",
    "语言", "内容", "卡片",
)


def _is_confirm_signal(text: str) -> bool:
    """是否属于「确认/继续/选择候选项/生成」类信号。

    只有这类消息才允许把已展示的草稿晋升为「已确认」（放行生成闸）；
    随手追问无关问题（如「今天天气如何」）不构成确认。"""
    t = (text or "").strip().lower()
    if not t:
        return False
    if t in _SHORT_CONFIRM:
        return True
    if _SELECT_RE.search(t):
        return True
    return any(w in t for w in _CONFIRM_KEYWORDS)


def _is_review_signal(text: str) -> bool:
    """是否属于「已审阅故事板」类信号（确认 或 对结构/草稿给出调整意见）。"""
    t = (text or "").strip().lower()
    if not t:
        return False
    if _is_confirm_signal(t):
        return True
    return any(w in t for w in _REVIEW_KEYWORDS)


# ---------- 正文精简兜底 ----------

def _compact_card_enumeration(text: str) -> str:
    """正文精简兜底：模型违反「回复输出纪律」逐卡枚举时压缩为一句汇总。

    只压缩明显的卡片枚举行（「N 组 N 卡」「Shot N」「Element_xxx」列表），
    命中 ≥3 行才触发，保留首尾段落，不碰其他内容。
    """
    lines = (text or "").splitlines()
    hit_idx: List[int] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if re.match(r"^-\s*\*{0,2}\d+\s*组\s*\d+\s*卡", s):
            hit_idx.append(i)
        elif re.match(r"^\d+[.)、]\s*\*{0,2}Shot\s*\d+", s, re.IGNORECASE):
            hit_idx.append(i)
        elif re.match(r"^-\s*\*{0,2}Element_\S+", s):
            hit_idx.append(i)
    if len(hit_idx) < 3:
        return text
    # 找最长的连续命中区间（允许中间夹 1 个空行）
    runs: List[tuple] = []
    start = prev = hit_idx[0]
    for idx in hit_idx[1:]:
        if idx - prev <= 2:
            prev = idx
        else:
            runs.append((start, prev))
            start = prev = idx
    runs.append((start, prev))
    a, b = max(runs, key=lambda r: r[1] - r[0])
    head = "\n".join(lines[:a]).rstrip()
    tail_lines = list(lines[b + 1:])
    while tail_lines and not tail_lines[0].strip():
        tail_lines.pop(0)
    tail = "\n".join(tail_lines).strip()
    summary = "（逐卡明细已写入左侧故事板，此处不再逐条罗列）"
    parts: List[str] = []
    if head:
        parts.append(head)
    parts.append(summary)
    if tail:
        parts.append(tail)
    return "\n\n".join(parts)


# ---------- 历史截断（token 浪费治理） ----------

_HISTORY_ASSISTANT_MAX_CHARS = 600          # 非最新 assistant 回复的总上限（头+尾合计）
# 历史消息截断（token 浪费治理）：assistant 回复的有价值内容（草稿 prompt/规格文档）
# 已在工作台状态 JSON 里，旧回复全文重复注入毫无意义；user 消息是用户指令，保持全文。
_HISTORY_ASSISTANT_RECENT_MAX_CHARS = 2000  # 最新一条 assistant 回复的上限（紧邻决策与下一步计划最相关，保真度优先）
_HISTORY_HEAD_CHARS = 300                   # 旧回复保留头部（开头常是结论/总结）
_HISTORY_TAIL_CHARS = 300                   # 旧回复保留尾部（结尾常是下一步建议/待办决策）


def truncate_history(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """组装发给 LLM 的历史：assistant 超长消息截断，user 消息全文保留。

    截断策略（质量优化版）：
    - 最新一条 assistant 回复：保留前 2000 字（上一轮的决策/下一步与当前追问最相关）；
    - 更早的 assistant 回复：保留头 300 + 尾 300（旧版只留头部，
      会丢掉结尾的下一步建议与待确认事项）；
    - 截断处附说明，让模型知道完整内容可从工作台状态 JSON 获取。
    """
    last_assistant_idx = -1
    for i, m in enumerate(messages):
        if m.get("role", "user") == "assistant":
            last_assistant_idx = i

    out: List[Dict[str, str]] = []
    for i, m in enumerate(messages):
        role = m.get("role", "user")
        content = m.get("content", "")
        if not isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            if i == last_assistant_idx:
                if len(content) > _HISTORY_ASSISTANT_RECENT_MAX_CHARS:
                    content = (
                        content[:_HISTORY_ASSISTANT_RECENT_MAX_CHARS]
                        + "\n…（最新回复超长已截断，完整内容见工作台状态 JSON 与项目文档）"
                    )
            elif len(content) > _HISTORY_ASSISTANT_MAX_CHARS:
                head = content[:_HISTORY_HEAD_CHARS]
                tail = content[-_HISTORY_TAIL_CHARS:]
                content = (
                    head
                    + "\n…（历史回复中部已省略，只保留首尾）…\n"
                    + tail
                    + "\n…（历史回复已截断，最新完整内容见工作台状态 JSON）"
                )
        out.append({"role": role, "content": content})
    return out
