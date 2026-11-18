"""音频错误码 → 可操作提示单测（2026-10-30）。

用户看不懂 `AccessDenied.Unpurchased`、`Endpoint.AccessDenied` 这类原始码，
也不知道下一步该去哪点。这里钉死「已收录的码必须给出动作」与
「未收录的码不篡改（返回空串，继续展示原始 message）」两条契约。
"""
import json

from src.video_agent.adapters.audio_error_hints import HINTS_BY_CODE, friendly_hint
from src.video_agent.adapters.dashscope_audio import _http_error


def test_exact_code_wins_over_prefix():
    # AccessDenied.Unpurchased 必须先于 AccessDenied 命中（前者带“关掉用完即停开关”动作）
    hint = friendly_hint("AccessDenied.Unpurchased")
    assert "用完即停" in hint
    assert hint != HINTS_BY_CODE["AccessDenied"]


def test_prefix_code_falls_back_to_parent():
    assert friendly_hint("AccessDenied.SomeUnknownSuffix") == HINTS_BY_CODE["AccessDenied"]
    assert "dashscope.aliyuncs.com" in friendly_hint("Endpoint.AccessDenied")


def test_unknown_code_is_not_rewritten():
    # 未收录 → 空串，调用方继续展示原始 code/message（不掩盖细节）
    assert friendly_hint("") == ""
    assert friendly_hint("InvalidParameter") == ""


def test_engine_418_maps_to_voice_mismatch_hint():
    """同一个 InvalidParameter 下，Engine 418 = 音色 ID 与模型版本不匹配。"""
    hint = friendly_hint("InvalidParameter", "[cosyvoice:]Engine return error code: 418")
    assert "音色 ID" in hint and "longanhuan_v3.1" in hint


def test_http_error_418_uses_voice_hint():
    body = json.dumps({
        "code": "InvalidParameter",
        "message": "[cosyvoice:]Engine return error code: 418",
    })
    err = _http_error(400, body, context="语音合成")
    assert "音色 ID" in str(err)
    assert "Engine return error code" not in str(err)


def test_http_error_prefers_hint_over_raw_body():
    body = json.dumps({"code": "Endpoint.AccessDenied", "message": "Workspace endpoint access denied."})
    err = _http_error(403, body, context="音效生成")
    assert "dashscope.aliyuncs.com" in str(err)
    assert "Workspace endpoint access denied" not in str(err)


def test_http_error_keeps_raw_body_for_unknown_code():
    body = json.dumps({"code": "SomethingNew", "message": "boom detail"})
    err = _http_error(400, body, context="音效生成")
    assert "SomethingNew" in str(err)
    assert "boom detail" in str(err)


def test_http_error_survives_non_json_body():
    err = _http_error(502, "<html>bad gateway</html>", context="音乐生成")
    assert "502" in str(err)
    assert err.retryable is True
