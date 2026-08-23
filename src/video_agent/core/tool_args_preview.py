"""工具输入参数预览（裁剪脱敏）纯函数域（任务 #2 时间线分级展开）。

tool_started SSE 事件与 tracer.record_action 落盘的 args 一律经本模块
redact_tool_args 处理：时间线详情卡只展示「关键字段截断预览」，
全文/大负载/base64 媒体不出后端（脱敏契约，vitest/pytest 钉死）。

规则：
- 长文本字段（document_write.content 等）只留前 PREVIEW_CHAR_LIMIT 字预览；
- 键名含 base64/data_uri 等媒体负载关键字，或值形如 data: URI → 剔除为占位符；
- 裸 base64 值形状启发式（FIX-6）：长（≥128）且前 512 字符全为 base64
  字母表（含空白）的字符串视为媒体负载剔除——补通用键名下无 data: 前缀
  base64 截断外泄的口子，与模块自述脱敏契约对齐；
- 整体 args JSON 序列化后不得超过 MAX_ARGS_JSON_BYTES（超限逐字段降档截断）。
"""
import json
import re
from typing import Any, Dict

# 单字段长文本预览上限（字符）：document_write.content 全文不外出
PREVIEW_CHAR_LIMIT = 300
# 整体 args JSON 体积上限（字节，utf-8 序列化后）
MAX_ARGS_JSON_BYTES = 2048
# 触发整体上限后的逐字段降档截断长度
_FALLBACK_STR_LIMIT = 120
# 脱敏关键字（键名小写包含即剔除值）：媒体 base64/data_uri 负载
_SENSITIVE_KEY_TOKENS = ("base64", "data_uri", "datauri", "b64")
# 脱敏占位符（值被剔除时的可见标记）
REDACTED_PLACEHOLDER = "<已脱敏>"
# 裸 base64 值形状启发式参数（FIX-6）：长度下限与前缀扫描窗口
_BARE_B64_MIN_LEN = 128
_BARE_B64_SCAN_LEN = 512
# base64 字母表（含空白：换行/空格是 MIME 分块 base64 的合法形态）
_BARE_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _looks_like_bare_base64(value: str) -> bool:
    """裸 base64 负载启发式：长（≥128）且前 512 字符全为 base64 字母表
    （含空白）即判定为媒体负载。中文创作提示词含非 ASCII、代码片段含
    括号/引号等标点，均在前缀窗口内即被排除，不误伤。"""
    if len(value) < _BARE_B64_MIN_LEN:
        return False
    return bool(_BARE_B64_RE.match(value[:_BARE_B64_SCAN_LEN]))


def truncate_text(text: str, limit: int = PREVIEW_CHAR_LIMIT) -> str:
    """长文本截断预览（保留前 limit 字 + 全文字数提示）。"""
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return text[:limit] + f"…（已截断，共 {len(text)} 字）"


def _is_sensitive_key(key: str) -> bool:
    k = str(key).lower()
    return any(tok in k for tok in _SENSITIVE_KEY_TOKENS)


def _redact_value(key: str, value: Any, str_limit: int) -> Any:
    if _is_sensitive_key(key):
        return REDACTED_PLACEHOLDER
    if isinstance(value, str):
        # data URI 媒体负载：无论键名一律剔除
        if value.startswith("data:"):
            return REDACTED_PLACEHOLDER
        # 裸 base64 值形状启发式（通用键名下也不出后端）
        if _looks_like_bare_base64(value):
            return REDACTED_PLACEHOLDER
        return truncate_text(value, str_limit)
    if isinstance(value, dict):
        return {k: _redact_value(k, v, str_limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, v, str_limit) for v in value]
    return value


def _json_bytes(d: Dict[str, Any]) -> int:
    return len(json.dumps(d, ensure_ascii=False, default=str).encode("utf-8"))


def redact_tool_args(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """工具入参 → 时间线安全预览（裁剪 + 脱敏 + 体积上限）。

    name 预留分工具差异化裁剪（当前统一规则已覆盖 document_write.content
    长文本截断）；返回新 dict，不改调用方原 args。
    """
    if not isinstance(args, dict) or not args:
        return {}
    out = {k: _redact_value(k, v, PREVIEW_CHAR_LIMIT) for k, v in args.items()}
    # 整体体积上限：超限后所有字符串降档截断；仍超限则只保留短字段
    if _json_bytes(out) > MAX_ARGS_JSON_BYTES:
        out = {k: _redact_value(k, v, _FALLBACK_STR_LIMIT) for k, v in args.items()}
    if _json_bytes(out) > MAX_ARGS_JSON_BYTES:
        slim: Dict[str, Any] = {}
        for k, v in out.items():
            candidate = dict(slim)
            candidate[k] = v
            if _json_bytes(candidate) > MAX_ARGS_JSON_BYTES:
                break
            slim = candidate
        out = slim
    return out
