"""P2-1 提示词字节稳定性测试：

状态上下文（模型可见面）在内容未变时必须字节级稳定——供应商前缀
缓存（KV-cache）按字节匹配，任何每次必变的字段（如 updated_at）都会
击穿命中。本组用例钉死：
- 仅易变时间戳变化 → build_agent_context 输出字节一致
- 内容真实变化 → 输出字节必须变化（稳定性不以丢信息为代价）
- updated_at 不再出现在模型可见面
"""
import copy
import json

from src.video_agent.state.context_builder import build_agent_context


def _sample_state():
    return {
        "keyElements": [
            {
                "id": "ke-1", "title": "主角", "desc": "少年",
                "drafts": [{
                    "id": "d-1", "label": "主角定妆", "tag": "",
                    "mediaType": "image", "prompt": "一段提示词",
                    "model": "m", "imgUrl": "", "videoUrl": "", "audioUrl": "",
                }],
            }
        ],
        "shots": [],
        "audioItems": [],
        "assets": [],
        "documents": [{
            "name": "制片规格.md",
            "updated_at": "2026-08-26T00:00:00",
            "content": "规格正文" * 60,
        }],
        "uploadedDocs": [],
        "interaction": {},
        "flowEvents": [],
    }


def test_bytes_stable_when_only_volatile_timestamp_changes():
    """内容未变、仅 updated_at 变 → 模型可见字节必须一致（缓存命中前提）"""
    s1 = _sample_state()
    s2 = copy.deepcopy(s1)
    s2["documents"][0]["updated_at"] = "2026-08-27T12:34:56"
    assert build_agent_context(s1, "bound") == build_agent_context(s2, "bound")


def test_bytes_change_when_content_changes():
    """内容真实变化 → 字节必须变化（稳定性不以丢信息为代价）"""
    s1 = _sample_state()
    s2 = copy.deepcopy(s1)
    s2["documents"][0]["content"] = "完全不同的规格正文"
    assert build_agent_context(s1, "bound") != build_agent_context(s2, "bound")


def test_updated_at_absent_from_model_visible_context():
    """updated_at 已移出模型可见面（前端视图不受影响，仍随 raw state 下发）"""
    ctx = build_agent_context(_sample_state(), "bound")
    assert "updated_at" not in ctx
    doc = json.loads(ctx)["documents"][0]
    assert set(doc.keys()) == {"name", "char_count", "preview"}


def test_cache_returns_identical_bytes():
    """缓存命中路径返回与首算完全一致的字节"""
    s = _sample_state()
    cache = {}
    first = build_agent_context(s, "bound", cache=cache)
    second = build_agent_context(s, "bound", cache=cache)
    assert first == second
