"""P3-14(c) 记忆召回 query 扩展 + fallback bigram 分词单测。

覆盖：query = 用户消息 + 当前阶段标签 + 激活 Skill 名；
中文 bigram 分词（替换单字切分）；旧单字关键词的检索兼容。
"""
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.memory.models import MemoryRecord
from src.video_agent.memory.retriever import hybrid_rank, keyword_score, tokenize


# ---------- bigram 分词 ----------

def test_tokenize_chinese_bigrams():
    """中文连续片段展开为 bigram，不再产出单字"""
    tokens = tokenize("用户要求赛博朋克风格")
    assert "用户" in tokens
    assert "户要" in tokens
    assert "赛博" in tokens
    assert "用" not in tokens  # 单字切分退役
    assert "户" not in tokens


def test_tokenize_single_char_kept():
    """孤立的单字中文片段原样保留（无法组 bigram）"""
    tokens = tokenize("好 a1")
    assert "好" in tokens
    assert "a1" in tokens


def test_keyword_score_with_legacy_single_char_keywords():
    """旧存量记录关键词为单字时，检索仍可命中（兼容层）"""
    rec = MemoryRecord(
        content="用户偏好赛博朋克风格的夜景",
        keywords=["用", "户", "偏", "好"],  # 旧 fallback.json 形态
    )
    assert keyword_score("赛博朋克夜景", rec) > 0


def test_hybrid_rank_matches_bigram_topic():
    """bigram 主题词命中：相关记忆排前，无关记忆被过滤"""
    import time

    now = time.time()
    rec_rel = MemoryRecord(content="用户确认采用赛博朋克风格", created_at=now)
    rec_off = MemoryRecord(content="完全无关的天气闲聊内容", created_at=now)
    ranked = hybrid_rank([rec_rel, rec_off], "赛博朋克风格继续", now=now)
    assert ranked and ranked[0].id == rec_rel.id
    assert all(r.id != rec_off.id for r in ranked)


# ---------- query 扩展拼接 ----------

class _Ctx:
    def __init__(self, history=None, skill_name=""):
        self.history = history or []
        self.skill_name = skill_name


def _builder(raw_state=None):
    return PromptBuilder(
        get_skill_docs=lambda: None,
        get_project_id=lambda: "proj_001",
        get_raw_state=(lambda: raw_state) if raw_state is not None else None,
    )


def test_query_concatenates_user_stage_skill():
    """query = 用户消息 + 阶段标签 + Skill 名"""
    pb = _builder(raw_state={})  # 无分组 → 规格规划阶段
    ctx = _Ctx(history=[{"role": "user", "content": "继续"}],
               skill_name="AI-短剧一站式生成")
    q = pb.memory_recall_query(ctx)
    assert q == "继续 规格规划 AI-短剧一站式生成"


def test_query_without_skill_and_stage():
    """无 Skill、阶段不可探测时只保留用户消息"""
    pb = _builder()  # get_raw_state=None → detect_stage 返回 ""
    ctx = _Ctx(history=[{"role": "user", "content": "改一下色调"}])
    assert pb.memory_recall_query(ctx) == "改一下色调"


def test_query_empty_user_message_still_has_context():
    """用户消息缺失时仍可用阶段+Skill 兜底检索"""
    pb = _builder(raw_state={})
    ctx = _Ctx(history=[{"role": "assistant", "content": "好的"}],
               skill_name="水墨风格武侠短片")
    assert pb.memory_recall_query(ctx) == "规格规划 水墨风格武侠短片"


def test_build_system_prompt_uses_expanded_query():
    """接线：build_system_prompt 的记忆检索改用扩展后的 query"""
    import inspect

    src = inspect.getsource(PromptBuilder.build_system_prompt)
    assert "memory_recall_query" in src
    assert "self.last_user_text(context)" not in src
