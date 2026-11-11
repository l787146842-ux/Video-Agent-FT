"""Skill 助手文档流切分与全文提取（哨兵定界优先，围栏/裸文档回落）。

通用 Agent Skills 口径（2026-11-11）：文档 = frontmatter + Markdown 标题式正文，
不再有 `<planner>` 等标签章节。起点判定按 frontmatter / `# ` 标题；完整度
按二级标题数量评分；围栏截断时向最后一个围栏扩展。

流式切分与终态提取共用同一套起点判定：聊天区只拿哨兵外的说明文字，
预览只拿哨兵内的文档正文；哨兵缺失时回落到首个「像文档」的起点。
"""
import re
from typing import List, Optional, Tuple

DOC_START = "<<<SKILL_DOC>>>"
DOC_END = "<<<END_SKILL_DOC>>>"
# 助手端点专属帧名（不登记进 core/sse_events 的主链 TS 契约；
# 前端 lib/skill-assistant-stream 独立消费）
SSE_DOC_DELTA = "doc_delta"

_SENTINEL_START_RE = re.compile(r"<<<\s*SKILL_DOC\s*>>>")
_SENTINEL_END_RE = re.compile(r"<<<\s*END_SKILL_DOC\s*>>>")
# 围栏行（行首锚定）：文档内部的示例围栏也逐行可辨，不再被当成全文边界
_FENCE_LINE_RE = re.compile(r"(?m)^```[^\n]*$")
_FENCE_OPEN_RE = re.compile(r"(?m)^```(?:markdown|md)?[ \t]*$")
_FENCE_BLOCK_RE = re.compile(
    r"(?ms)^```(?:markdown|md)?[ \t]*\r?\n?(.*?)(?:^```[ \t]*\r?$|\Z)",
)
_FM_LINE_RE = re.compile(r"(?m)^---[ \t]*\r?$")
_H1_RE = re.compile(r"(?m)^#\s+\S")
_H2_RE = re.compile(r"(?m)^##\s+\S")


def _strip_open_fence(doc: str) -> str:
    """去掉文档首行的整篇围栏（模型无视「别再包围栏」时的兜底）。"""
    text = (doc or "").lstrip("\r\n")
    first, sep, rest = text.partition("\n")
    if sep and re.fullmatch(r"```(?:markdown|md)?[ \t]*", first.strip()):
        return rest
    return doc


def _finalize_doc(doc: str) -> str:
    """终态收口：去首尾空白、去整篇围栏（文档内部围栏原样保留）。"""
    lines = _strip_open_fence(doc or "").strip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.fullmatch(r"```[ \t]*", lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).strip()


def _has_frontmatter(content: str) -> bool:
    body = (content or "").lstrip("\ufeff\r\n ")
    return body.startswith("---") and "name:" in body[:500]


def _heading_count(content: str) -> int:
    return len(_H2_RE.findall(content or ""))


def _looks_like_skill_doc(content: str) -> bool:
    """像不像一份 Skill 文档：frontmatter / 至少两个二级标题 / 一级标题。"""
    body = (content or "").strip()
    if not body:
        return False
    if _has_frontmatter(body):
        return True
    if _heading_count(body) >= 2:
        return True
    return bool(_H1_RE.search(body))


def _looks_like_doc_head(snippet: str) -> bool:
    """围栏后紧随的内容是否像文档起点（防把说明里的示例块当全文）。"""
    head = (snippet or "")[:600]
    if _has_frontmatter(head):
        return True
    return bool(_H1_RE.search(head))


def _content_start(text: str, fence_end: int) -> int:
    """围栏行结束后的正文起点（当前行换行之后）。"""
    nl = text.find("\n", fence_end)
    return nl + 1 if nl != -1 else len(text)


def _doc_start_index(text: str) -> Optional[int]:
    """首个「像文档」的起点：围栏内容 > frontmatter > `# ` 标题。"""
    for m in _FENCE_OPEN_RE.finditer(text or ""):
        start = _content_start(text, m.end())
        if _looks_like_doc_head(text[start:start + 600]):
            return start
    for m in _FM_LINE_RE.finditer(text or ""):
        if "name:" in text[m.start():m.start() + 400]:
            return m.start()
    heading = _H1_RE.search(text or "")
    if heading:
        return heading.start()
    return None


def _split_state(text: str) -> Tuple[str, str, str]:
    """(chat, doc, mode)；mode ∈ none / fallback / sentinel_open / sentinel_closed。"""
    body = text or ""
    m = _SENTINEL_START_RE.search(body)
    if m:
        rest = body[m.end():]
        end = _SENTINEL_END_RE.search(rest)
        if end:
            return body[:m.start()] + rest[end.end():], rest[:end.start()], "sentinel_closed"
        return body[:m.start()], rest, "sentinel_open"
    start = _doc_start_index(body)
    if start is not None:
        return body[:start], body[start:], "fallback"
    return body, "", "none"


def _live_doc(doc: str) -> str:
    """实时预览口径：去整篇围栏与哨兵后的首行空白（保文档内部缩进）。"""
    return _strip_open_fence(doc or "").lstrip("\r\n")


def split_stream_text(text: str) -> Tuple[str, str]:
    """流式切分：返回 (聊天文字, 文档文字)；文档可能尚未生成完。"""
    chat, doc, mode = _split_state(text)
    if mode.startswith("sentinel"):
        doc = _live_doc(doc)
    return chat, doc


def _hold_tail(text: str, keep: int) -> str:
    """保留末尾 keep 个字符不发（防半截哨兵被当成正文/文档）。"""
    if keep <= 0 or len(text) <= keep:
        return ""
    return text[:-keep]


class DocStreamSplitter:
    """把累积文本切成 chat/doc 两路增量。

    每帧重新切分全量文本，只按长度差下发新增部分；哨兵未闭合时对
    结束标记做尾巴 holdback，避免 `<<<END_SKILL_` 这类半截文本闪进预览
    （终态 content 始终以 extract_skill_doc 的结果为权威）。
    """

    def __init__(self) -> None:
        self._sent_chat = 0
        self._sent_doc = 0

    def _emit(self, chat: str, doc: str) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        if len(chat) > self._sent_chat:
            out.append(("chat", chat[self._sent_chat:]))
            self._sent_chat = len(chat)
        if len(doc) > self._sent_doc:
            out.append(("doc", doc[self._sent_doc:]))
            self._sent_doc = len(doc)
        return out

    def feed(self, text: str) -> List[Tuple[str, str]]:
        chat, doc, mode = _split_state(text or "")
        if mode == "sentinel_open":
            doc = _hold_tail(_live_doc(doc), len(DOC_END) - 1)
        elif mode.startswith("sentinel"):
            doc = _live_doc(doc)
        elif mode == "none":
            chat = _hold_tail(chat, len(DOC_START) - 1)
        return self._emit(chat, doc)

    def flush(self, text: str) -> List[Tuple[str, str]]:
        """流结束收尾：不再 holdback，把剩余聊天/文档尾巴发完。"""
        chat, doc, mode = _split_state(text or "")
        if mode.startswith("sentinel"):
            doc = _live_doc(doc)
        return self._emit(chat, doc)


def _bare_skill_doc(text: str) -> str:
    """裸文档回落：模型没套围栏时，从文档起点截到文末。

    起点优先级：frontmatter（含 name:）> `# ` 标题。
    """
    body = text or ""
    candidates: List[str] = []
    for m in _FM_LINE_RE.finditer(body):
        if "name:" in body[m.start():m.start() + 400]:
            candidates.append(body[m.start():])
            break
    heading = _H1_RE.search(body)
    if heading:
        candidates.append(body[heading.start():])
    if not candidates:
        return ""
    return max(candidates, key=len).strip()


def _score_doc(content: str) -> int:
    """候选评分：二级标题数量优先，frontmatter/一级标题次之（0 = 不像文档）。"""
    heads = _heading_count(content)
    fm = 1 if _has_frontmatter(content) else 0
    head = 1 if _H1_RE.search(content or "") else 0
    return heads * 10 + fm * 5 + head


def _extend_to_last_fence(text: str, content_start: int) -> str:
    """从候选正文起点扩到最后一个围栏行：修复嵌套围栏把全文截断。"""
    last = None
    for m in _FENCE_LINE_RE.finditer(text or ""):
        if m.start() > content_start:
            last = m
    if last is None:
        return ""
    return (text or "")[content_start:last.start()]


def _clean_chat(chat: str) -> str:
    """聊天说明去哨兵；模型给整篇包了围栏时，把围栏行也从说明里去掉。"""
    text = _SENTINEL_START_RE.sub("", chat or "")
    text = _SENTINEL_END_RE.sub("", text)
    text = re.sub(r"(?m)^```[^\n]*\r?\n?", "", text)
    return text.strip()


def extract_skill_doc(text: str) -> Tuple[str, Optional[str], str]:
    """终态提取：返回 (聊天说明, Skill 全文|None, 来源)。

    来源 ∈ sentinel / fence / bare / none，供路由日志排障。
    """
    raw = text or ""
    chat, doc, mode = _split_state(raw)
    if mode.startswith("sentinel"):
        final = _finalize_doc(doc)
        if final and _looks_like_skill_doc(final):
            return _clean_chat(chat), final, "sentinel"
    candidates = []
    for idx, m in enumerate(_FENCE_BLOCK_RE.finditer(raw)):
        content = _finalize_doc(m.group(1))
        score = _score_doc(content)
        if score > 0:
            candidates.append((score, idx, m, content))
    if candidates:
        # 平票取更晚的完整版本（用户让模型「再改一版」时保留新版）
        _, _, best_match, best_content = max(candidates, key=lambda c: (c[0], c[1]))
        extended = _extend_to_last_fence(raw, best_match.start(1))
        if extended and _heading_count(extended) > _heading_count(best_content):
            best_content = _finalize_doc(extended)
        return _clean_chat(raw[:best_match.start()]), best_content, "fence"
    bare = _bare_skill_doc(raw)
    if bare:
        idx = raw.find(bare)
        return _clean_chat(raw[:idx] if idx >= 0 else ""), bare, "bare"
    return _clean_chat(raw), None, "none"
