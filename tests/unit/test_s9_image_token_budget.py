"""五轮 S9：图片 token 估算回归（#15b：vision token 计入预算）。"""
from src.video_agent.config import settings
from src.video_agent.core.token_budget import estimate_messages_tokens, truncate_messages


def test_s9_image_parts_counted_in_budget():
    text_only = [{"role": "user", "content": [{"type": "text", "text": "你好"}]}]
    with_image = [{"role": "user", "content": [
        {"type": "text", "text": "你好"},
        {"type": "image_url", "image_url": {"url": "http://x/a.png"}},
    ]}]
    diff = estimate_messages_tokens(with_image) - estimate_messages_tokens(text_only)
    assert diff == settings.image_token_estimate, "image_url 部分未按固定成本计入"


def test_s9_multiple_images_accumulate():
    msgs = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"http://x/{i}.png"}} for i in range(3)
    ]}]
    total = estimate_messages_tokens(msgs)
    assert total >= 3 * settings.image_token_estimate


def test_s9_truncate_protects_bounds_with_image_history():
    """带图历史触发截断时保护边界语义不变（首条 + 最近 N 条不删）"""
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(10):
        msgs.append({"role": "user", "content": f"用户消息{i}"})
        msgs.append({"role": "assistant", "content": [
            {"type": "text", "text": f"回复{i}"},
            {"type": "image_url", "image_url": {"url": f"http://x/{i}.png"}},
        ]})
    out = truncate_messages(msgs, max_tokens=2000, keep_recent=4)
    assert out[0]["role"] == "system"
    assert len(out) >= 5
    # 最近消息保留完整（含 image part）
    last = out[-1]
    assert isinstance(last["content"], list)
