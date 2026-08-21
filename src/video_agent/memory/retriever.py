"""
混合检索排序：语义得分（可选） + 关键词重叠 + 时间衰减。

评分公式：final = 0.6 * relevance + 0.4 * decay
- relevance：语义检索得分（ChromaDB），或关键词重叠率（降级路径）
- decay：指数时间衰减，半衰期可配置
"""
import re
import time
from typing import Dict, List, Optional

from src.video_agent.memory.models import MemoryRecord

# 英文/数字按词，中文按连续片段捕获（下一步展开为 bigram）
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[一-鿿]+")


def tokenize(text: str) -> List[str]:
    """中英文混合分词：英文单词 + 中文 bigram。

    中文单字切分曾使 fallback 后端关键词近乎失效（「用」「户」这类
    通用单字淹没有效信号），改 bigram 后「用户」「要求」才是可匹配的
    词；单字残段（长度 1 的片段）原样保留。"""
    tokens: List[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if len(tok) == 1 and '一' <= tok <= '鿿':
            tokens.append(tok)
        elif tok[0].isascii():
            tokens.append(tok)
        else:
            tokens.extend(tok[i] + tok[i + 1] for i in range(len(tok) - 1))
    return tokens


def _bigrams(tokens: List[str]) -> List[str]:
    """兼容层：旧存量记录的关键词为单字切分，检索时把相邻单字
    补展为 bigram，与新写入的 bigram 关键词对齐（新分词下基本透传）"""
    chars = [t for t in tokens if len(t) == 1 and '一' <= t <= '鿿']
    words = [t for t in tokens if len(t) > 1]
    return words + chars + [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def keyword_score(query: str, record: MemoryRecord) -> float:
    """查询与记录的关键词重叠率（0~1）"""
    q_tokens = set(_bigrams(tokenize(query)))
    if not q_tokens:
        return 0.0
    r_tokens = set(_bigrams(tokenize(record.content + " " + " ".join(record.keywords))))
    if not r_tokens:
        return 0.0
    overlap = len(q_tokens & r_tokens)
    return overlap / (len(q_tokens) ** 0.5) / (len(r_tokens) ** 0.5) if overlap else 0.0


def time_decay(created_at: float, now: Optional[float] = None, half_life_days: float = 30.0) -> float:
    """指数时间衰减（0~1），半衰期 half_life_days 天"""
    now = now if now is not None else time.time()
    age_days = max(0.0, (now - created_at) / 86400.0)
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def hybrid_rank(
    records: List[MemoryRecord],
    query: str,
    half_life_days: float = 30.0,
    top_k: int = 5,
    semantic_scores: Optional[Dict[str, float]] = None,
    now: Optional[float] = None,
) -> List[MemoryRecord]:
    """
    混合排序：
    - semantic_scores 提供时 relevance 用语义得分，否则用关键词重叠率
    - 得分 ≤ 0 的记录被过滤
    """
    now = now if now is not None else time.time()
    scored: List[MemoryRecord] = []
    for rec in records:
        if semantic_scores is not None:
            relevance = semantic_scores.get(rec.id, 0.0)
        else:
            relevance = keyword_score(query, rec)
        decay = time_decay(rec.created_at, now, half_life_days)
        final = 0.6 * relevance + 0.4 * decay * min(relevance * 2.0, 1.0)
        if final <= 0:
            continue
        scored.append(rec.model_copy(update={"score": round(final, 4)}))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]
