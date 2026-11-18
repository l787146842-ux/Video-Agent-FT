"""音频供应商错误码 → 可操作的中文提示（单一事实源）。

原始错误码（`AccessDenied.Unpurchased`、`Endpoint.AccessDenied` …）用户看不懂，
也不知道下一步该点哪里。这里只收录「需要用户去控制台做点动作」的码，
每个提示必须包含**下一步动作**，否则不收录（泛泛的"调用失败"没有价值）。

未收录的码返回空串，调用方继续展示原始 code + message（不掩盖细节）。
"""
from typing import Dict, List, Tuple

HINTS_BY_CODE: Dict[str, str] = {
    # 百炼：免费额度用完即停开着 / 模型未开通
    "AccessDenied.Unpurchased": (
        "该模型未开通，或免费额度已用完且「免费额度用完即停」仍开着。"
        "请在百炼控制台模型详情页关掉该开关，或点「立即申请」开通"
    ),
    # 百炼：模型级未开通（音乐/音色设计常见）
    "AccessDenied": (
        "该模型未开通。请在百炼控制台「模型广场」找到该模型并开通；"
        "邀测模型需在模型详情页点「立即申请」（约半个工作日审批）"
    ),
    # 百炼：工作空间专属域名与 Key 不匹配
    "Endpoint.AccessDenied": (
        "当前工作空间域名与这个 API Key 不匹配。"
        "请把请求地址改成通用域名 https://dashscope.aliyuncs.com/compatible-mode/v1"
    ),
}

# 按 message 片段命中的提示（同一个 code 下不同原因需不同动作）
HINTS_BY_MESSAGE: List[Tuple[str, str]] = [
    # 百炼 CosyVoice/Qwen TTS：音色 ID 与模型版本不匹配（Engine 418）
    (
        "Engine return error code: 418",
        "音色 ID 与当前模型版本不匹配：请填音色设计返回的 voice_id，"
        "或该模型对应版本的平台音色（如 longanhuan_v3.1）",
    ),
]


def friendly_hint(code: str, message: str = "") -> str:
    """错误码（或 message 片段）→ 可操作提示；未收录返回空串。"""
    text = str(message or "")
    for marker, hint in HINTS_BY_MESSAGE:
        if marker in text:
            return hint
    c = str(code or "").strip()
    if not c:
        return ""
    exact = HINTS_BY_CODE.get(c)
    if exact:
        return exact
    for key, hint in HINTS_BY_CODE.items():
        if c.startswith(key):
            return hint
    return ""


__all__ = ["HINTS_BY_CODE", "HINTS_BY_MESSAGE", "friendly_hint"]
