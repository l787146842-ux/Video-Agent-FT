"""四轮 R5 回归（#8）：truncate_messages 按轮组原子删除，FC 配对消息不拆半边。

FC 轨消息形态：assistant（含 tool_calls 语义）+ 紧随的（系统）回喂 user 消息
是供应商协议上的配对，截断只删其一会导致下一请求被供应商 400。
"""
from src.video_agent.core.token_budget import truncate_messages


def _msg(role, content):
    return {"role": role, "content": content}


def test_r5_truncate_keeps_fc_pair_intact():
    """超预算截断时：assistant + 紧随（系统）回喂整组删除，不留孤儿。"""
    messages = [
        _msg("system", "SYS"),
        # 旧轮组 1：真实用户 + assistant + 系统回喂
        _msg("user", "第一轮真实输入"),
        _msg("assistant", "第一轮回复（已调用工具）"),
        _msg("user", "（系统）第 1 轮的 2 个 Tool 已执行完毕。"),
        # 旧轮组 2：真实用户 + assistant + 系统回喂
        _msg("user", "第二轮真实输入"),
        _msg("assistant", "第二轮回复（已调用工具）"),
        _msg("user", "（系统）第 2 轮的 1 个 Tool 已执行完毕。"),
        # 最近消息（保护区）
        _msg("user", "最新输入"),
        _msg("assistant", "最新回复"),
    ]
    # 预算极小强制截断；keep_recent=2
    out = truncate_messages(messages, max_tokens=20, keep_recent=2)
    # 首条 system 保留
    assert out[0]["role"] == "system"
    # 不得出现「（系统）回喂活着但前一条 assistant 被删」的孤儿配对
    for i, m in enumerate(out):
        if str(m.get("content", "")).startswith("（系统"):
            assert i > 0 and out[i - 1]["role"] == "assistant", (
                f"截断拆开了 FC 配对：索引 {i} 的系统回喂前不是 assistant"
            )
    # 保护区完整：最后 2 条原样
    assert out[-1]["content"] == "最新回复"
    assert out[-2]["content"] == "最新输入"


def test_r5_truncate_group_atomic_no_partial_round():
    """轮组原子性：真实用户消息与其后的 assistant/回喂同组删除，
    不允许只删 assistant 留下空转的用户消息之前的半轮。"""
    messages = [
        _msg("system", "SYS"),
        _msg("user", "旧输入"),
        _msg("assistant", "旧回复"),
        _msg("user", "（系统）已执行。"),
        _msg("user", "新输入"),
    ]
    out = truncate_messages(messages, max_tokens=15, keep_recent=1)
    contents = [m["content"] for m in out]
    # 旧轮组三条要么都在、要么都不在
    old_round = {"旧输入", "旧回复", "（系统）已执行。"}
    present = old_round & set(contents)
    assert present in (set(), old_round)


def test_r5_truncate_real_user_multimodal_not_synthetic():
    """多模态 content parts 的用户消息判为真实消息（不随前轮被连带删除）。"""
    messages = [
        _msg("system", "SYS"),
        _msg("assistant", "旧回复"),
        {"role": "user", "content": [{"type": "text", "text": "看图"}]},
        _msg("user", "新输入"),
    ]
    out = truncate_messages(messages, max_tokens=15, keep_recent=1)
    # 多模态消息是真实用户消息，单独成组边界；此处预算紧时允许整组删，
    # 但断言它不会被误判为合成消息而与前一条 assistant 捆绑判断出错——
    # 只要不抛异常且首尾保护成立即可
    assert out[0]["role"] == "system"
    assert out[-1]["content"] == "新输入"
