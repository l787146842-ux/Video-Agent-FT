"""
OpenAI 兼容协议 Adapter — 覆盖 ModelScope / Gemini 反代 / 任何 OpenAI 兼容端点。

同时提供 Chat 和 Image 两种能力：
- OpenAICompatChatAdapter: LLM 对话（支持流式 + function calling）
- OpenAICompatImageAdapter: 图片生成（/images/generations + /chat/completions fallback）
"""
import asyncio
import base64
import binascii
import json
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from loguru import logger

from .base_chat import (
    BaseChatAdapter,
    ChatResponse,
    StreamChunk,
    dispatch_chat_request,
    extract_prompt_cache_usage,
    new_request_id,
)
from .base import BaseImageAdapter, ImageGenerationResponse
from src.video_agent.utils.prompts import load_prompt_section
from .errors import (
    KIND_NETWORK,
    KIND_REFUSAL,
    KIND_TIMEOUT,
    KIND_UPSTREAM,
    build_exception_error,
    build_status_error,
    is_transient_error,
)
from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError
from src.video_agent.utils.live_metrics import record_degradation
from src.video_agent.utils.json_rescue import rescue_tool_arguments
from src.video_agent.utils.model_limits import output_limit_for_model
from src.video_agent.utils.paths import ASSETS_DIR, DATA_DIR
from src.video_agent.utils.provider_config_loader import chat_model_meta
from src.video_agent.utils import gen_id
from src.video_agent.storage import get_storage

_DATA_URI_RE = re.compile(r"data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)")
_HTTP_IMAGE_RE = re.compile(r"https?://[^\s\)\"]+\.(?:png|jpg|jpeg|webp|gif)")


def _preclamp_max_tokens(requested: int, caps: Dict[str, int], model: str) -> int:
    """下发前按「400 钳制记忆」预钳 max_tokens（同 _unsupported_fields 探针
    记忆惯例：探明拒收后不再重发大值）。只降不升，显式小值不受影响。"""
    cap = caps.get(model)
    if cap is not None and requested > cap:
        return cap
    return requested


# ---------- 原始 SSE 落盘观测（诊断开关，settings.sse_capture 默认关） ----------

_SSE_CAPTURE_DIR = DATA_DIR / "sse_capture"
_SSE_CAPTURE_MAX_FILES = 500
_SSE_CAPTURE_LINE_CAP = 2000


class _SSECapture:
    """单次 LLM 流式调用的原始 SSE 碎片落盘器（抓假停/丢工具调用现行用）。

    逐 `data:` 行记录中转实际下发内容（截断到 2000 字/行防病态巨行），
    头部一条请求元数据、尾部一条收尾元数据（finish_reason/碎片数/工具数/
    异常）。文件写入 data/sse_capture/sse-*.jsonl，目录超 500 个滚动清理
    最旧。仅诊断用，不影响主流程：任何落盘异常静默降级为关闭。
    """

    def __init__(self, model: str, base_url: str, payload: Dict[str, Any]) -> None:
        self._fh = None
        self._chunks = 0
        try:
            _SSE_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            files = sorted(_SSE_CAPTURE_DIR.glob("sse-*.jsonl"))
            while len(files) >= _SSE_CAPTURE_MAX_FILES:
                files.pop(0).unlink(missing_ok=True)
            self._path = _SSE_CAPTURE_DIR / f"{gen_id('sse')}-{model.replace('/', '_')}.jsonl"
            self._fh = self._path.open("a", encoding="utf-8")
            self._meta({"__header__": {
                "ts": time.time(), "model": model, "base_url": base_url,
                "messages_n": len(payload.get("messages") or []),
                "tools_n": len(payload.get("tools") or []),
                "max_tokens": payload.get("max_tokens"),
                "stream": payload.get("stream"),
            }})
        except Exception as e:  # 落盘失败不阻断对话
            logger.debug(f"[OpenAICompat] SSE 落盘开启失败（忽略）: {e}")
            self._fh = None

    def _meta(self, obj: Dict[str, Any]) -> None:
        if self._fh is not None:
            try:
                self._fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
                self._fh.flush()
            except Exception as e:
                logger.debug(f"[OpenAICompat] SSE 落盘写失败（忽略）: {e}")
                self._fh = None

    def write_chunk(self, raw: str) -> None:
        self._chunks += 1
        self._meta({"__chunk__": self._chunks, "raw": raw[:_SSE_CAPTURE_LINE_CAP]})

    def close(self, **footer: Any) -> None:
        if self._fh is None:
            return
        self._meta({"__footer__": {"chunks": self._chunks, **footer}})
        try:
            self._fh.close()
        except Exception:
            pass
        self._fh = None


def _sse_capture_open(model: str, base_url: str, payload: Dict[str, Any]) -> Optional[_SSECapture]:
    """开关关闭或开启失败时返回 None（调用方全程空值短路）。"""
    if not settings.sse_capture:
        return None
    return _SSECapture(model, base_url, payload)


def _clamp_max_tokens_payload(payload: Dict[str, Any], body: str, model: str) -> Optional[int]:
    """400 拒收大 max_tokens → 按模型安全帽钳制（改值不剥离，区别于
    _strip_unsupported_on_400 的字段剥离）。仅当报文点名 max_tokens 且当前
    下发值超过该模型输出上限（model_output_limits.json 查表）时触发。
    返回钳制值（调用方据此重试一次并按模型记忆），无需钳制返回 None。"""
    if "max_tokens" not in body or not isinstance(payload.get("max_tokens"), int):
        return None
    cap = output_limit_for_model(model)
    if payload["max_tokens"] <= cap:
        return None
    payload["max_tokens"] = cap
    record_degradation("adapter.max_tokens_clamped")
    logger.warning(
        f"[OpenAICompat] 端点 400 拒收大 max_tokens（model={model!r}），"
        f"钳制到模型输出上限 {cap} 后重试一次"
    )
    return cap


def extract_base64_image(text: str) -> str:
    """从 LLM 回复文本中提取 data URI 图片"""
    m = _DATA_URI_RE.search(text)
    return m.group(0) if m else ""


def persist_data_uri(data_uri: str) -> str:
    """把 base64 data URI 通过 Storage 接口落盘，返回相对 URL"""
    m = _DATA_URI_RE.match(data_uri)
    if not m:
        raise AdapterError("无法解析图片 data URI")
    ext = m.group(1).lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in ("png", "jpg", "webp", "gif"):
        ext = "png"
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as e:
        raise AdapterError(f"图片 base64 解码失败: {e}")

    name = f"{gen_id('gen', wide=True)}.{ext}"
    storage = get_storage()
    url = storage.save(raw, name, f"image/{ext}")
    return url


_MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}
_MIME_TO_SUFFIX = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def persist_remote_image(url: str, max_bytes: int = 20 * 1024 * 1024) -> str:
    """把供应商返回的远程图片立即落盘到本地存储，返回本地 URL。

    部分图片中转站返回的是有时效的临时托管链接（如 aitohumanize.com），
    几小时后即失效，导致后续视频生成把死链发给下游 API 报 400。
    生成成功时立刻下载内联，之后统一使用本地素材。
    下载失败时保留原 URL（浏览器可能仍可访问），仅记录告警。
    """
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return url
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200 or not resp.content:
            logger.warning(
                f"[ImageAdapter] 远程图片下载失败(HTTP {resp.status_code})，保留原 URL: {url}"
            )
            return url
        raw = resp.content
        if len(raw) > max_bytes:
            logger.warning(
                f"[ImageAdapter] 远程图片 {len(raw) // 1024}KB 超过 {max_bytes // 1024}KB，保留原 URL: {url}"
            )
            return url
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            ext = _MIME_TO_SUFFIX.get(ctype, ".png")
        if ext == ".jpeg":
            ext = ".jpg"
        storage = get_storage()
        name = f"{gen_id('gen', wide=True)}{ext}"
        saved = storage.save(raw, name, ctype or f"image/{ext.lstrip('.')}")
        logger.info(f"[ImageAdapter] 远程图片已落盘: {url} -> {saved} ({len(raw)} bytes)")
        return saved
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ImageAdapter] 远程图片落盘失败，保留原 URL: {url} ({e})")
        return url


async def ref_to_data_uri(url: str) -> str:
    """把参考素材 URL（本地 /assets、http(s)、data:）转为 base64 data URI。

    多模态模型（如 Gemini）无法访问本服务/画布的本地地址，因此将参考图
    内联为 data URI 随请求发送，保证模型能准确接收到 @ 引用的素材。
    失败返回空串（调用方跳过该参考图）。
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("data:"):
        return url
    try:
        if url.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                raw = resp.content
                ctype = resp.headers.get("content-type", "").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    ext = Path(urlparse(url).path).suffix.lower()
                    ctype = _MIME_BY_SUFFIX.get(ext, "image/png")
        else:
            # 本地素材：/workspace/assets/xxx 或 /assets/xxx（防目录穿越）
            path = urlparse(url).path if "://" in url else url
            fname = path.split("/assets/")[-1].strip("/") if "/assets/" in path else path.strip("/")
            full = (ASSETS_DIR / fname).resolve()
            full.relative_to(ASSETS_DIR.resolve())
            if not full.exists():
                return ""
            raw = full.read_bytes()
            ctype = _MIME_BY_SUFFIX.get(full.suffix.lower(), "image/png")
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{ctype};base64,{b64}"
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ImageAdapter] 参考图转 data URI 失败: {e}")
        return ""


# ---------- 中继错误信封识别（用户裁决：选什么用什么，联不通直接报错） ----------
# 中继层（9router 等）会把上游拒收（403/10605 slow 队列等）包进 HTTP 200 流
# 当「模型内容」下发（如 "[qoder error 403: {...}]"）；不识别会被当稿子，
# 垃圾递模型/绿勾/正文渲染裸 JSON。识别命中即抛错（retryable=False，不重试）。
_RELAY_ERROR_PREFIX_RE = re.compile(r"^\s*\[[\w-]+\s+error\s+(\d{3})\s*:", re.IGNORECASE)
_RELAY_QUEUE_CODE_RE = re.compile(r'"code"\s*:\s*"?(\d{3})"?')


def detect_relay_error_envelope(text: str) -> Optional[int]:
    """文本是中继层拒收通知单返回 http_status，否则 None。

    只看短文本（通知单至多几百字），合法长稿零误判：
    ①「[xxx error 403: …」前缀形态；②「{"code":"403",…10605/queueType…}」裸信封形态。
    """
    if not text or len(text) > 4000:
        return None
    m = _RELAY_ERROR_PREFIX_RE.match(text)
    if m:
        return int(m.group(1))
    stripped = text.lstrip()
    if stripped.startswith("{") and "10605" in text and "queueType" in text:
        m2 = _RELAY_QUEUE_CODE_RE.search(text)
        return int(m2.group(1)) if m2 else 403
    return None


def _strip_messages_reasoning(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """剥离 assistant 历史消息携带的 reasoning_content（浅拷贝替换，
    不改调用方历史本体），供闸门关闭与 400 兜底共用。"""
    out = messages
    mutated = False
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("reasoning_content"):
            if not mutated:
                out = list(messages)
                mutated = True
            out[i] = {k: v for k, v in m.items() if k != "reasoning_content"}
    return out


# 400 兜底记忆键：assistant 消息内字段（与 payload 顶层字段键共集合存放）
MSG_REASONING_KEY = "messages.reasoning_content"

# ---------- 400 文案精确分类（dsh 对齐：code 分类，不解析模糊子串） ----------
#
# 2026-10-08 批（事故 9999「工具调用凭空蒸发」根因修复，用户裁决「按 dsh 方案做」）：
#
# 病灶链（全套取证见 CHANGELOG 同批条目）：
#   ① 供应商 400 文案「Messages with role 'tool' must be a response to a
#      preceding message with 'tool_calls'」是**配对错误**（我们发出去的历史
#      不合法），不是能力缺失；
#   ② 旧判定用 `"tool" in body` **子串**匹配 —— 该文案里同时含
#      `role 'tool'` 与 `'tool_calls'` ⇒ 恒为真 ⇒ **误判成「端点不支持
#      tool role」**；
#   ③ 误判触发粘性历史改写降级：把模型自己历史里的 assistant(tool_calls)
#      全换成 `⟦TOOL_CALLS: 工具名⟧` 文本占位，并在本实例内**永久沿用**；
#   ④ 模型每轮看到自己的历史全是该占位符，学会照抄 —— 真到要干活时只写
#      正文、不发工具调用 ⇒ **工具调用凭空蒸发**（假停 + 活干一半）。
#
# 反证（决定性）：同一端点上 123 个样本以 69–99 条消息、tool_calls>0 正常
# 应答 ⇒ 该端点**接受** tool role。全库 500 份抓包中含 "tool" 的 400 共 3 条，
# **全部**是配对错误，**零**条「真不支持 role」。
#
# dsh 对照（`@deepseek-ai/dsh-llm` 等 724 个包全量核查）：
#   - dsh **不存在**运行时格式降级，也**不存在**「记住降级」的集合；
#   - 原文「Unsupported explicit efforts reject before provider I/O;
#     **no clamping or aliasing is performed**」⇒ 能力问题**发出前**拒绝；
#   - 「Model-visible ⟺ logged ... requests are deep-frozen and
#     **never rewritten**」⇒ 历史**永不改写**；
#   - 供应商怪癖由**适配器**在序列化时承担（「adapters own the wire」）。
# ⇒ 修法同向：**删掉历史改写降级**，改为「发出前配对归一 + 400 精确分类」。

# 真·不支持 tool role（能力缺失）：只认明确的能力/角色声明语句
_TOOL_ROLE_UNSUPPORTED_RE = re.compile(
    # 「role tool is not supported」/「the tool role is unsupported」
    r"(?:role\s*['\"]?tool['\"]?|tool\s+role)\s*(?:is\s*)?"
    r"(?:not\s+support\w*|unsupported|not\s+recognized|unrecognized|not\s+known|unknown)"
    # 「unsupported role: tool」/「unknown role 'tool'」
    r"|(?:unsupported|unknown|invalid|unrecognized)\s+role\b[^.]{0,40}?\btool\b",
    re.I,
)

# 配对错误（我们的历史不合法）：明确指向「tool 必须回应前置 tool_calls」
_TOOL_PAIRING_ERROR_RE = re.compile(
    r"must\s+be\s+a\s+response\s+to\s+a\s+preceding\s+message"
    r"|preceding\s+message\s+with\s*['\"]?tool_calls"
    r"|messages?\s+with\s+role\s*['\"]?tool['\"]?\s+must",
    re.I,
)


# 未应答调用的占位回喂：措辞唯一源 = prompts/planner/feedback.md::TOOL_RESULT_SUSPENDED
# （与 core/session_log._suspended_tool_note 同源；Rule 6 禁硬编码 CJK prose）。
# adapters → utils 是合法方向（check_layer_imports R3 明确放行），故直接引外置源。
def _unanswered_tool_note() -> str:
    return (load_prompt_section("planner/feedback.md", "TOOL_RESULT_SUSPENDED")
            or "（该调用未执行完成，会话在此中断）")


def classify_tool_role_400(body: str) -> str:
    """tool 相关 400 精确分类：返回 "pairing" / "unsupported" / "other"。

    顺序要紧：配对错误优先判定 —— 其文案里也含 `role 'tool'` 与
    `tool_calls`，宽松匹配会把两者混淆（这正是旧实现 `"tool" in body`
    的病根）。两者互斥时的取舍依据：配对错误是**可自愈**的我们自身缺陷，
    能力缺失是**不可自愈**的端点属性，修复动作完全不同。
    """
    text = str(body or "")
    if _TOOL_PAIRING_ERROR_RE.search(text):
        return "pairing"
    if _TOOL_ROLE_UNSUPPORTED_RE.search(text):
        return "unsupported"
    return "other"


def normalize_tool_pairing(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """发出前 tool 消息配对归一（dsh 对齐：I/O 之前校验，**不改写持久历史**）。

    OpenAI 硬约束：每条 `role:"tool"` 必须紧跟在**声明了其 tool_call_id** 的
    `assistant(tool_calls)` 之后。历史里任何来源的断裂（存量导入轮、压缩
    检查点、就地改写、用户中断轮）都会让**整次请求**被供应商 400 拒收；
    而拒收文案极易被误读成「端点不支持 tool role」（见上方批注）。

    本函数在**发送副本**上就地修复，调用方历史本体不变（浅拷贝替换）：
      - 孤立 tool 结果（前置未声明该 id，含 id 为空的存量导入轮）→ 转
        `role:"user"`，**内容一字不丢**（内容早已落会话事件流，此处只是
        请求投影的合法化；对齐 dsh「durable 引用 → 路由专用请求版本」）；
      - assistant 声明了调用却没有结果 → 补占位 tool 结果（满足「每个
        tool_call 必有对应 tool 消息」，与 session_log 补位同口径）。

    幂等：已合法的消息序列原样返回（同一列表对象，零拷贝）。
    """
    if not messages:
        return messages
    out: List[Dict[str, Any]] = []
    mutated = False
    i = 0
    while i < len(messages):
        m = messages[i]
        if not isinstance(m, dict):
            out.append(m)
            i += 1
            continue
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            calls = [c for c in (m.get("tool_calls") or []) if isinstance(c, dict)]
            declared = [str(c.get("id") or "") for c in calls]
            # 收集紧随其后的 tool 结果块
            results: List[Dict[str, Any]] = []
            j = i + 1
            while j < len(messages) and isinstance(messages[j], dict) \
                    and messages[j].get("role") == "tool":
                results.append(messages[j])
                j += 1
            answered = {str(r.get("tool_call_id") or "") for r in results}
            out.append(m)
            # ① 该 assistant 声明但无结果的 → 补占位
            for cid in declared:
                if cid and cid not in answered:
                    out.append({"role": "tool", "tool_call_id": cid,
                                "content": _unanswered_tool_note()})
                    mutated = True
            # ② 结果落在声明集合内 → 原样保留；否则 → 转 user（内容不丢）
            for r in results:
                cid = str(r.get("tool_call_id") or "")
                if cid and cid in declared:
                    out.append(r)
                else:
                    new_r = {k: v for k, v in r.items() if k != "tool_call_id"}
                    new_r["role"] = "user"
                    out.append(new_r)
                    mutated = True
            i = j
            continue
        if role == "tool":
            # 走到这里 = 没有前置 assistant(tool_calls) 声明它 ⇒ 孤立
            new_m = {k: v for k, v in m.items() if k != "tool_call_id"}
            new_m["role"] = "user"
            out.append(new_m)
            mutated = True
            i += 1
            continue
        out.append(m)
        i += 1
    return out if mutated else messages


def _demote_tool_role_for_request(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """真·不支持 tool role 的端点：**本次请求**降级 user 伪装（不粘性）。

    与 2026-09-26 之前那版的关键区别：**不写 `_unsupported_fields`**。
    旧版「降级是粘性的」是本次事故的放大器——一次误判即让该实例此后
    每一轮请求都改写历史，模型持续照抄占位符。改为逐次决策后：
      - 配对 bug 已由 `normalize_tool_pairing` 在发出前消除 ⇒ 本分支
        在实跑中不再被触发（全库 500 份抓包零「真不支持」样本）；
      - 即便将来真遇到这类端点，也只影响**那一次**请求，且下一轮
        仍走标准 tool 通道（不污染模型对自己历史的认知）。

    assistant 侧：tool_calls 转文本占位（机械标记式，模型无从模仿）；
    tool 侧：转 user 并保留内容（一字不丢）。浅拷贝，不改调用方本体。
    """
    out = messages
    mutated = False
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        if m.get("role") == "assistant" and m.get("tool_calls"):
            if not mutated:
                out = list(messages)
                mutated = True
            calls = m.get("tool_calls") or []
            names = ", ".join(
                str((c.get("function") or {}).get("name") or "?")
                for c in calls if isinstance(c, dict))
            new_msg = {k: v for k, v in m.items() if k != "tool_calls"}
            new_msg["content"] = new_msg.get("content") or (
                f"\u27e6TOOL_CALLS: {names}\u27e7")
            out[i] = new_msg
        elif m.get("role") == "tool":
            if not mutated:
                out = list(messages)
                mutated = True
            out[i] = {"role": "user", "content": (
                "（系统）本轮工具执行结果：\n- " + str(m.get("content", "")))}
    return out


def _gate_reasoning_passthrough(
    messages: List[Dict[str, Any]], force_strip: bool = False
) -> List[Dict[str, Any]]:
    """思考回传闸门（五项修法批 4，default-off）：关 = 剥离 assistant 历史
    消息携带的 reasoning_content（浅拷贝替换，不改调用方历史本体），防残留
    字段外泄到拒收该字段的端点；开 = 原样下发（GLM 4.5+ 交错思考/工具循环
    官方要求把 assistant 思考内容回传以保持推理连续性）。
    force_strip = 400 兜底记忆命中（该端点曾点名拒收 reasoning_content），
    无论开关一律剥离（上下文与缓存优化计划批 A）。"""
    if not force_strip and settings.llm_reasoning_passthrough:
        return messages
    return _strip_messages_reasoning(messages)


def _prepare_endpoint_messages(
    messages: List[Dict[str, Any]], unsupported: set,
) -> List[Dict[str, Any]]:
    """请求侧消息变换统一入口：思考回传闸门 + 400 兜底记忆（reasoning 剥离）
    + **发出前 tool 配对归一**（2026-10-08 批）。

    tool role 降级的粘性记忆已退役（事故 9999 根因）：它由子串误判触发、
    且改写模型可见历史致其照抄占位符。配对问题改在**这里**（任何请求都先
    归一，dsh 同款「I/O 之前校验」），真能力缺失才在 400 分支逐次降级。
    """
    msgs = _gate_reasoning_passthrough(
        messages, force_strip=MSG_REASONING_KEY in unsupported)
    return normalize_tool_pairing(msgs)


class OpenAICompatChatAdapter(BaseChatAdapter):
    """OpenAI 兼容 Chat Adapter（支持流式 + function calling）

    连接池复用：实例持有长生命周期 httpx.AsyncClient，避免每次请求重建 TCP 连接。
    使用完毕后调用 await adapter.close 释放资源。
    """

    def __init__(self, base_url: str, api_key: str = "", model: str = "", provider_id: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider_id = provider_id
        self._client: Optional[httpx.AsyncClient] = None
        # 字段兼容探针记忆（同实例只探一次）：
        # 端点 400 拒收 reasoning_effort/response_format 后记入本集合，
        # 后续请求不再下发该字段（与 降级同惯例）。
        self._unsupported_fields: set = set()
        # max_tokens 钳制记忆（按模型）：400 点名拒收大 max_tokens 后记录
        # 该模型安全帽，后续请求下发前预钳（_preclamp_max_tokens），不重走 400
        self._max_tokens_caps: Dict[str, int] = {}

    def _get_client(self, timeout: int = 120) -> httpx.AsyncClient:
        """Lazy 创建/复用 httpx 客户端（连接池复用）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(timeout, connect=10.0),
                headers=self._headers(),
            )
        return self._client

    async def close(self) -> None:
        """释放 HTTP 连接池资源"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @property
    def supports_function_calling(self) -> bool:
        return True

    def _apply_thinking_level(self, payload: Dict[str, Any], level: Optional[str] = None) -> None:
        """按配置透传 thinking/reasoning 档位。

        注入优先级（模型编辑面板批 2026-09-08）：
        1. level=None（调用方未指定）→ env 全局 llm_thinking_level 回落（814H7 原语义）；
        2. 会话显式档位 low/medium/high → reasoning_effort 透传（executor/summary
           角色策略或主对话显式选择）；非法值不下发；
        3. level=""（UI「默认（原生）」档）→ 模型 meta（chat_models_meta 面板配置）
           注入：thinking_enabled=False 不发；配了 thinking_level 发 reasoning_effort；
           仅开开关发 enable_thinking=true；
        4. meta 未配置该模型 → env 全局回落；均无 → 兜底 enable_thinking=true
           （hybrid 模型如 deepseek 默认关思考，不主动开则永远无思考——
           tokenrhythm 实测 2026-09-08）。
        不支持的端点 400 时走 _strip_unsupported_on_400 剥离重试（探针记忆）。"""
        if level is None:
            lv = str(settings.llm_thinking_level or "").strip().lower()
            if lv in ("low", "medium", "high"):
                payload["reasoning_effort"] = lv
            return
        lv = str(level).strip().lower()
        if lv in ("low", "medium", "high"):
            payload["reasoning_effort"] = lv
            return
        if lv:
            return  # 非法档位不下发
        # level == ""（UI「默认（原生）」档）→ 模型 meta 思考配置
        meta = chat_model_meta(self.provider_id, self.model)
        if meta is not None:
            if meta.get("thinking_enabled") is False:
                return  # 面板显式关思考
            tl = str(meta.get("thinking_level") or "").strip().lower()
            if tl in ("low", "medium", "high"):
                payload["reasoning_effort"] = tl
            else:
                payload["enable_thinking"] = True
            return
        env_level = str(settings.llm_thinking_level or "").strip().lower()
        if env_level in ("low", "medium", "high"):
            payload["reasoning_effort"] = env_level
            return
        payload["enable_thinking"] = True

    def _apply_response_format(self, payload: Dict[str, Any],
                                response_format: Optional[Dict[str, Any]]) -> None:
        """：结构化输出（执行器 JSON 产出点下发 json_object）。
        探针已判定不支持的字段不再下发（兼容探针记忆）。"""
        if response_format and "response_format" not in self._unsupported_fields:
            payload["response_format"] = response_format

    def _strip_unsupported_on_400(self, payload: Dict[str, Any], body: str) -> bool:
        """兼容探针：400 拒收时按报文点名剥离可选字段（reasoning_effort/
        response_format），未点名则两者并剥；剥过即记忆（同实例不再试探）。
        assistant 消息内 reasoning_content 被点名拒收时剥离历史消息该字段
        并记忆（messages.reasoning_content，批 A 兜底：思考回传开着的端点
        迁移到拒收型端点时不至于持续 400）。
        返回是否剥离了任何字段（True 时调用方应重试一次）。"""
        # 消息内字段优先：报文点名 reasoning_content 时只剥消息字段，
        # 不落入顶层字段并剥（避免误剥 reasoning_effort）
        if "reasoning_content" in body and MSG_REASONING_KEY not in self._unsupported_fields:
            payload["messages"] = _strip_messages_reasoning(payload.get("messages") or [])
            self._unsupported_fields.add(MSG_REASONING_KEY)
            record_degradation("adapter.messages_reasoning_content_unsupported")
            logger.warning(
                "[OpenAICompat] 端点 400 拒收 assistant 消息 reasoning_content，"
                "剥离历史思考字段后重试一次（本实例后续请求不再携带）"
            )
            return True
        # 2026-10-08 批（事故 9999 根因修复，用户裁决「按 dsh 方案做」）：
        # tool 相关 400 **精确分类**后分流 —— 旧实现用 `"tool" in body`
        # 子串匹配，把「配对错误」（我们历史不合法）误判成「端点不支持
        # tool role」，进而触发**粘性历史改写降级**，让模型照抄占位符、
        # 工具调用凭空蒸发（完整取证见本模块 _TOOL_* 常量上方批注）。
        #   · pairing → 我们自身的可自愈缺陷：**就地修配对后重试一次**，
        #     绝不改写历史、绝不记住（下轮历史本就合法，无需记忆）；
        #   · unsupported → 真能力缺失：只在**本次请求副本**上降级重试，
        #     **不写入 `_unsupported_fields`**（不粘性）——配对 bug 修好后
        #     不再有任何东西能触发它，留作最后防线而非常态通道。
        if "tool" in body and any(
                isinstance(m, dict) and (m.get("role") == "tool" or m.get("tool_calls"))
                for m in (payload.get("messages") or [])):
            _kind400 = classify_tool_role_400(body)
            if _kind400 == "pairing":
                _fixed = normalize_tool_pairing(payload.get("messages") or [])
                if _fixed is not payload.get("messages"):
                    payload["messages"] = _fixed
                    record_degradation("adapter.tool_pairing_normalized")
                    logger.warning(
                        "[OpenAICompat] 400 判定为 tool 消息配对错误（非能力缺失）："
                        "发送副本配对归一后重试一次（历史本体不改写、不记忆）"
                    )
                    return True
            elif _kind400 == "unsupported":
                payload["messages"] = _demote_tool_role_for_request(
                    payload.get("messages") or [])
                record_degradation("adapter.tool_role_unsupported")
                logger.warning(
                    "[OpenAICompat] 端点 400 明示不支持 tool role："
                    "本次请求降级 user 伪装重试（**不记忆**，下轮仍按标准 tool 通道）"
                )
                return True
        fields = [k for k in ("response_format", "reasoning_effort", "enable_thinking") if k in payload]
        if not fields:
            return False
        named = [k for k in fields if k in body]
        to_strip = named or fields
        for k in to_strip:
            payload.pop(k, None)
            self._unsupported_fields.add(k)
        for k in to_strip:
            record_degradation(f"adapter.{k}_unsupported")
        logger.warning(f"[OpenAICompat] 端点 400 拒收可选字段 {to_strip}，剥离后重试一次")
        return True

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        thinking_level: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ChatResponse:
        if max_tokens is None:
            max_tokens = settings.llm_max_tokens
        max_tokens = _preclamp_max_tokens(max_tokens, self._max_tokens_caps, self.model)
        if temperature is None:
            temperature = settings.llm_temperature
        if timeout is None:
            timeout = settings.llm_timeout
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": _prepare_endpoint_messages(
                messages, self._unsupported_fields),
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 非流式必须显式声明：中介对缺省 stream 按流式路由，
            # 缺省会拿回 SSE 文本导致解析崩溃。
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        self._apply_thinking_level(payload, thinking_level)
        self._apply_response_format(payload, response_format)

        # 同轮请求标识（幂等语义）：一次 chat 调用生成一个 id，
        # 重试全程复用同一 payload + 同一标识（随 X-Request-Id 下发），
        # 供上游按标识去重，避免同轮请求被当多次新请求重复计费。
        request_id = new_request_id()
        _req_headers = {"X-Request-Id": request_id}
        try:
            client = self._get_client(timeout)
            # 分流入口：transient（429/5xx/超时/连接错误）指数退避
            # 重试（上限/退避走 config）；permanent 4xx 立即上抛结构化错误
            resp = await dispatch_chat_request(
                lambda: client.post(
                    "/chat/completions", json=payload, headers=_req_headers,
                ),
                context="chat",
            )
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                # 200 但回非 JSON（被误当流式路由）按契约转 AdapterError，
                # 不让裸解析错误漏出 adapter 层。
                raise AdapterError(
                    f"LLM 返回非 JSON 响应（可能被误当流式）：{e}；响应头={resp.text[:120]!r}",
                    retryable=False,
                    kind=KIND_UPSTREAM,
                ) from e
        except AdapterError as e:
            # 优雅降级：严格端点不认 reasoning_effort/
            # response_format 报 400 → 剥离字段重试一次（兼容探针；
            # permanent 400 中唯一允许的一次纠正式重提，非盲目重试）；
            # 400 点名拒收大 max_tokens → 按模型安全帽钳制（改值不剥离）重试一次
            if getattr(e, "http_status", None) == 400:
                stripped = self._strip_unsupported_on_400(payload, str(e))
                clamped_cap = _clamp_max_tokens_payload(payload, str(e), self.model)
                if clamped_cap is not None:
                    self._max_tokens_caps[self.model] = clamped_cap
                if stripped or clamped_cap is not None:
                    try:
                        resp = await client.post(
                            "/chat/completions", json=payload, headers=_req_headers,
                        )
                        if resp.status_code >= 400:
                            raise build_status_error(
                                resp.status_code, resp.text[:200], context="chat",
                            )
                        data = resp.json()
                    except json.JSONDecodeError as e2:
                        raise AdapterError(
                            f"LLM 返回非 JSON 响应（可能被误当流式）：{e2}",
                            retryable=False,
                            kind=KIND_UPSTREAM,
                        ) from e2
                    except httpx.HTTPError as e2:
                        raise build_exception_error(e2, context="chat") from e2
                else:
                    raise
            else:
                raise
        except httpx.HTTPError as e:
            # 重试耗尽的超时/连接错误在此转译：分类器给出 kind/retryable
            raise build_exception_error(e, context="chat") from e

        choices = data.get("choices", [])
        if not choices:
            raise AdapterError("LLM 返回了空 choices")
        message = choices[0].get("message", {})
        content = message.get("content", "") or ""
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") != "image_url"
            )
        # 中继拒收通知单识别（200 包错误）——命中即抛错，不当稿子返回；
        # 归类为 permanent/refusal（模型拒答同源处置：不重试不 nudge）
        _env_status = detect_relay_error_envelope(content)
        if _env_status is not None:
            raise AdapterError(
                f"LLM 中继拒收通知单（HTTP {_env_status}）: {content[:200]}",
                retryable=False, http_status=_env_status, kind=KIND_REFUSAL,
            )
        tool_calls = message.get("tool_calls", []) or []
        # 推理模型思考内容捕获（非流式）：随 ChatResponse 上抛，
        # 回传与否由 settings.llm_reasoning_passthrough 统一闸门控制
        _reasoning = str(message.get("reasoning_content") or "")
        # 透明度兑现：usage.total_tokens 入响应（轮次账单数据源，缺失保 0）
        _usage = data.get("usage") or {}
        _total_tokens = int(_usage.get("total_tokens") or 0) if isinstance(_usage, dict) else 0
        # P2-1 KV-cache 遥测：同口径提取 prompt/缓存命中 token（缺失保 0）
        _prompt_tokens, _cached_tokens = extract_prompt_cache_usage(_usage)
        return ChatResponse(
            content=content,
            finish_reason=choices[0].get("finish_reason", "") or "",
            tool_calls=tool_calls,
            raw=data,
            token_usage=_total_tokens,
            prompt_tokens=_prompt_tokens,
            cached_tokens=_cached_tokens,
            reasoning_content=_reasoning,
        )

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        thinking_level: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        if max_tokens is None:
            max_tokens = settings.llm_max_tokens
        max_tokens = _preclamp_max_tokens(max_tokens, self._max_tokens_caps, self.model)
        if temperature is None:
            temperature = settings.llm_temperature
        if timeout is None:
            timeout = settings.llm_stream_timeout
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": _prepare_endpoint_messages(
                messages, self._unsupported_fields),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        self._apply_thinking_level(payload, thinking_level)
        self._apply_response_format(payload, response_format)

        # 首块产出前遇瞬时故障（上游 5xx 繁忙 / 连接失败）指数退避重试，
        # 与非流式路径的 with_retry 对齐；已开始产出内容则不重试（避免内容重复）。
        max_connect_retries = 2
        for attempt in range(max_connect_retries + 1):
            yielded = False
            try:
                async for chunk in self._stream_once(payload, timeout):
                    yielded = True
                    yield chunk
                return
            except AdapterError as e:
                # 优雅降级：严格端点不认 reasoning_effort/
                # response_format 报 400 → 剥离字段重试（兼容探针；
                # AdapterError 报文携原始 body 前 200 字，可供点名判定）；
                # 400 点名拒收大 max_tokens → 按模型安全帽钳制（改值不剥离）重试一次
                if not yielded and (
                    getattr(e, "http_status", None) == 400
                    or str(e).startswith("LLM 返回 HTTP 400")
                ):
                    stripped = self._strip_unsupported_on_400(payload, str(e))
                    clamped_cap = _clamp_max_tokens_payload(payload, str(e), self.model)
                    if clamped_cap is not None:
                        self._max_tokens_caps[self.model] = clamped_cap
                    if stripped or clamped_cap is not None:
                        continue
                # 结构化判定：优先用 retryable 标记，无标记旧异常回落
                # 分类器结构化判定（替代脆弱的文案匹配）
                flag = getattr(e, "retryable", None)
                if flag is None:
                    flag = is_transient_error(e)
                if not flag or yielded or attempt >= max_connect_retries:
                    raise
                delay = 1.0 * (2 ** attempt)
                logger.warning(
                    f"[OpenAICompat] 流式瞬时故障：{str(e)[:120]}，"
                    f"第 {attempt + 1}/{max_connect_retries} 次重试，等待 {delay:.0f}s"
                )
                try:
                    from src.video_agent.utils.stream_notify import notify_stream

                    await notify_stream(
                        f"模型连接瞬时故障，正在重试（第 {attempt + 1}/{max_connect_retries} 次）…"
                    )
                except Exception as _e:
                    logger.debug("[openai_compat] 忽略异常: {}", _e)
                await asyncio.sleep(delay)

    async def _stream_once(
        self,
        payload: Dict[str, Any],
        timeout: int,
    ) -> AsyncGenerator[StreamChunk, None]:
        """单次流式请求（连接 + 逐行解析 SSE），异常转译为 AdapterError。"""
        # 原始 SSE 落盘观测（诊断开关；None = 关闭，调用侧空值短路）
        cap = _sse_capture_open(self.model, self.base_url, payload)
        last_finish = ""
        tc_n = 0
        err_txt = ""
        # 抓包盲区计数（9999 假停批）：非 data: 非空行（中转异常分帧嫌疑）
        # 与 JSON 解析失败行——两者都是「解析器静默跳过、此前抓包不可见」
        # 的唯一通道，footer 计数 >0 即提示人工回看 raw
        _skip_non_data = 0
        _skip_bad_json = 0
        try:
            client = self._get_client(timeout)
            async with client.stream(
                "POST", "/chat/completions", json=payload
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:200]
                    # 分类器统一判定：429/5xx = transient 才进重试循环
                    raise build_status_error(resp.status_code, body, context="chat-stream")

                ctype = resp.headers.get("content-type", "")
                if "text/event-stream" not in ctype:
                    # 供应商不支持流式，按普通 JSON 处理；
                    # 畸形体按契约转 AdapterError，不漏裸解析错误（与 chat 同契约）。
                    try:
                        _raw_body = (await resp.aread()).decode("utf-8", errors="replace")
                        if cap is not None:
                            cap.write_chunk(_raw_body)
                        data = json.loads(_raw_body)
                    except json.JSONDecodeError as e:
                        raise AdapterError(
                            f"LLM 返回非 JSON 响应（可能被误当流式）：{e}",
                            retryable=False,
                        ) from e
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "") or ""
                        _env_status = detect_relay_error_envelope(content)
                        if _env_status is not None:
                            raise AdapterError(
                                f"LLM 中继拒收通知单（HTTP {_env_status}）: {content[:200]}",
                                retryable=False, http_status=_env_status,
                            )
                        if content:
                            yield StreamChunk(type="text_delta", text=content)
                        fr = choices[0].get("finish_reason", "") or "stop"
                        _ju = data.get("usage") or {}
                        _ju_prompt, _ju_cached = extract_prompt_cache_usage(_ju)
                        yield StreamChunk(
                            type="done", finish_reason=fr,
                            usage_tokens=int(_ju.get("total_tokens") or 0) if isinstance(_ju, dict) else 0,
                            prompt_tokens=_ju_prompt, cached_tokens=_ju_cached)
                    return

                last_finish = ""
                # 透明度兑现：机会性收集流内 usage（include_usage 端点在末段
                # 下发 choices 为空的 usage chunk；未下发则保 0，不强求不变更请求体）
                _stream_tokens = 0
                # P2-1 KV-cache 遥测：同机会性收集 prompt/缓存命中 token
                _stream_prompt = 0
                _stream_cached = 0
                # 通知单头部累积器——中继把拒收缝进 200 流时，首段即识别抛错
                _env_head = ""
                _env_done = False
                # 流式 FC 累积器：OpenAI 协议中 tool_calls 的 arguments 是分片字符串，
                # 必须按 index 跨 chunk 拼接，流结束后统一解析（逐 chunk 解析必失败）
                tc_accumulator: Dict[int, Dict[str, str]] = {}
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        # 空行 = SSE 事件分隔符（协议噪声，不计）；
                        # 非空非 data 行 = 异常分帧（诊断信号，计数进 footer）
                        if line:
                            _skip_non_data += 1
                        continue
                    chunk = line[5:].strip()
                    if cap is not None and chunk:
                        cap.write_chunk(chunk)
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        _skip_bad_json += 1
                        continue
                    choices = data.get("choices", [])
                    # usage chunk 可能 choices 为空：先取 usage 再判空
                    _u = data.get("usage")
                    if isinstance(_u, dict) and _u.get("total_tokens"):
                        _stream_tokens = int(_u.get("total_tokens") or 0)
                    if isinstance(_u, dict):
                        _p, _c = extract_prompt_cache_usage(_u)
                        if _p or _c:
                            _stream_prompt, _stream_cached = _p, _c
                    if not choices:
                        continue
                    # 追踪 finish_reason（通常在最后一个 chunk 中携带）
                    fr = choices[0].get("finish_reason")
                    if fr:
                        last_finish = fr
                    delta = choices[0].get("delta", {}) or {}
                    # 推理模型（DeepSeek- / Gemini thinking 等）的 reasoning 增量：
                    # 各家字段名不同（reasoning_content / reasoning），有则透传，无则静默
                    reasoning_piece = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if reasoning_piece:
                        yield StreamChunk(type="reasoning_delta", text=reasoning_piece)
                    piece = delta.get("content") or ""
                    if piece:
                        if not _env_done:
                            _env_head += piece
                            _env_status = detect_relay_error_envelope(_env_head)
                            if _env_status is not None:
                                raise AdapterError(
                                    f"LLM 中继拒收通知单（HTTP {_env_status}）: {_env_head[:200]}",
                                    retryable=False, http_status=_env_status,
                                )
                            if len(_env_head) >= 512:
                                _env_done = True
                        yield StreamChunk(type="text_delta", text=piece)
                    # function calling 分片累积（index 标识第几个工具调用）
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            slot = tc_accumulator.setdefault(idx, {"id": "", "name": "", "arguments": "", "_notified": 0})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function", {}) or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                            # 8888 事故批（对齐 dsh tool-call-delta）：参数生成进度
                            # 流式提示——调用名首现即报、参数每满 2K 字符报一次，
                            # 消除「大参数工具调用生成期间的分钟级黑箱」（仅展示）
                            _args_len = len(slot["arguments"])
                            if (slot["name"] and slot["_notified"] == 0) or (
                                    _args_len - slot["_notified"] >= 2000):
                                slot["_notified"] = _args_len
                                yield StreamChunk(
                                    type="tool_call_delta",
                                    tool_name=slot["name"],
                                    tool_index=idx,
                                    tool_args_len=_args_len,
                                )
                # 流结束：对完整 arguments 统一解析后逐条下发 tool_call chunk
                # （8888 事故批：解析失败不再伪造 {} —— 先本地抢救，仍失败则
                # 原始串+拒因原样下发，由 runner 层结构化拒收并把真实原因回喂模型）
                for idx in sorted(tc_accumulator):
                    slot = tc_accumulator[idx]
                    raw_args = slot["arguments"]
                    args, parse_err = rescue_tool_arguments(raw_args)
                    if args is None:
                        logger.warning(f"[OpenAICompat] tool_call arguments 解析失败: {raw_args[:100]}")
                    yield StreamChunk(
                        type="tool_call",
                        tool_name=slot["name"],
                        tool_args=args if isinstance(args, dict) else {},
                        tool_call_id=slot["id"] or "",
                        tool_args_raw=raw_args if args is None else "",
                        tool_args_error=parse_err if args is None else "",
                    )
                # 流结束后 yield done chunk 携带 finish_reason（+ 机会性 usage）
                tc_n = len(tc_accumulator)
                yield StreamChunk(type="done", finish_reason=last_finish or "stop",
                                  usage_tokens=_stream_tokens,
                                  prompt_tokens=_stream_prompt,
                                  cached_tokens=_stream_cached)
        except AdapterError as e:
            err_txt = str(e)[:200]
            raise
        except httpx.TimeoutException as e:
            err_txt = f"timeout({timeout}s): {e}"
            raise AdapterError(
                f"LLM 流式请求超时（{timeout}s）", retryable=True, kind=KIND_TIMEOUT,
            )
        except httpx.HTTPError as e:
            err_txt = f"http: {e}"
            raise AdapterError(
                f"LLM 流式请求失败: {e}", retryable=True, kind=KIND_NETWORK,
            )
        finally:
            if cap is not None:
                cap.close(finish_reason=last_finish, tool_calls=tc_n, error=err_txt,
                          skipped_non_data=_skip_non_data, skipped_bad_json=_skip_bad_json)


class OpenAICompatImageAdapter(BaseImageAdapter):
    """OpenAI 兼容 Image Adapter（/images/generations + /chat/completions fallback）

    连接池复用：同 ChatAdapter，实例持有长生命周期 httpx.AsyncClient。
    """

    def __init__(self, base_url: str, api_key: str = "", model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client: Optional[httpx.AsyncClient] = None
        # max_tokens 钳制记忆（按模型，同 ChatAdapter 口径）
        self._max_tokens_caps: Dict[str, int] = {}

    def _get_client(self, timeout: int = 120) -> httpx.AsyncClient:
        """Lazy 创建/复用 httpx 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(timeout, connect=10.0),
                headers=self._headers(),
            )
        return self._client

    async def close(self) -> None:
        """释放 HTTP 连接池资源"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def generate_image(
        self, prompt: str, reference_image: Optional[str] = None, **kwargs
    ) -> ImageGenerationResponse:
        """AI 图片生成：先尝试 /images/generations，失败后 fallback 到 /chat/completions

        带参考图时（reference_images / reference_image）直接走 /chat/completions 多模态路径，
        因为 /images/generations 无法接收参考图。
        """
        size = kwargs.get("size", "1024x1024")
        aspect_ratio = kwargs.get("aspect_ratio", "")
        # 参考图列表（兼容单个 reference_image）
        reference_images: List[str] = list(kwargs.get("reference_images") or [])
        if reference_image and reference_image not in reference_images:
            reference_images.insert(0, reference_image)
        errors: List[str] = []

        # 带参考图：直接走多模态 chat 路径，保证模型接收到参考素材
        if reference_images:
            result = await self._try_chat_fallback(prompt, aspect_ratio, errors, reference_images)
            if result:
                return result
            raise AdapterError("参考图生成失败（模型可能不支持多模态生图）。" + "；".join(errors))

        # 方式 1: /images/generations
        result = await self._try_images_endpoint(prompt, size, errors)
        if result:
            return result

        # 方式 2: /chat/completions（Gemini 原生图片生成）
        result = await self._try_chat_fallback(prompt, aspect_ratio, errors)
        if result:
            return result

        raise AdapterError("图片生成失败（模型可能不支持生图，请换用图片模型）。" + "；".join(errors))

    async def _try_images_endpoint(self, prompt: str, size: str, errors: List[str]) -> Optional[ImageGenerationResponse]:
        """尝试 /images/generations 端点"""
        try:
            payload = {"model": self.model, "prompt": prompt, "n": 1, "size": size or "1024x1024"}
            client = self._get_client(settings.image_gen_timeout)
            resp = await client.post("/images/generations", json=payload)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    errors.append("/images/generations 返回非 JSON 响应（可能被误当流式）")
                    return None
                images_data = data.get("data", [])
                if images_data:
                    url = images_data[0].get("url", "")
                    if not url and images_data[0].get("b64_json"):
                        url = persist_data_uri(f"data:image/png;base64,{images_data[0]['b64_json']}")
                    elif url.lower().startswith(("http://", "https://")):
                        # 临时托管链立即落盘，避免过期后成为下游死链
                        url = await persist_remote_image(url)
                    if url:
                        return ImageGenerationResponse(
                            task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                        )
                errors.append("/images/generations 返回 200 但无图片数据")
            else:
                errors.append(f"/images/generations HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            raise AdapterError(
                "图片生成失败：API 服务未启动（连接被拒绝）。请检查服务是否运行，或切换到其他可用的图片 API。"
            ) from e
        except httpx.HTTPError as e:
            errors.append(f"/images/generations 请求失败: {e}")
        return None

    async def _try_chat_fallback(
        self, prompt: str, aspect_ratio: str, errors: List[str],
        reference_images: Optional[List[str]] = None,
    ) -> Optional[ImageGenerationResponse]:
        """Fallback: 通过 /chat/completions 生成图片（Gemini 原生图片生成，支持参考图）"""
        aspect_hint = f" Aspect ratio: {aspect_ratio}." if aspect_ratio and aspect_ratio != "1:1" else ""
        ref_hint = " The attached image(s) are provided as visual references; keep the result consistent with them." if reference_images else ""
        image_prompt = f"Generate an image: {prompt}.{aspect_hint}{ref_hint}"

        # 有参考图时构建多模态 content（文本 + 图片 data URI）
        content: Any = image_prompt
        if reference_images:
            parts: List[Dict[str, Any]] = [{"type": "text", "text": image_prompt}]
            for ref in reference_images:
                du = await ref_to_data_uri(ref)
                if du:
                    parts.append({"type": "image_url", "image_url": {"url": du}})
            if len(parts) > 1:
                content = parts

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": _preclamp_max_tokens(
                settings.llm_max_tokens, self._max_tokens_caps, self.model
            ),
        }
        try:
            client = self._get_client(settings.image_gen_timeout)
            resp = await client.post("/chat/completions", json=payload)
            # 400 点名拒收大 max_tokens → 钳制到模型安全帽重试一次（同 ChatAdapter）
            if resp.status_code == 400:
                clamped_cap = _clamp_max_tokens_payload(payload, resp.text, self.model)
                if clamped_cap is not None:
                    self._max_tokens_caps[self.model] = clamped_cap
                    resp = await client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            try:
                data = resp.json()
            except json.JSONDecodeError:
                errors.append("/chat/completions 生图回退返回非 JSON 响应（可能被误当流式）")
                return None

            choices = data.get("choices", [])
            content = choices[0].get("message", {}).get("content", "") if choices else ""
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:image/"):
                            url = persist_data_uri(url)
                        elif url.lower().startswith(("http://", "https://")):
                            url = await persist_remote_image(url)
                        if url:
                            return ImageGenerationResponse(
                                task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                            )
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))

            img_data = extract_base64_image(content)
            if img_data:
                url = persist_data_uri(img_data)
                return ImageGenerationResponse(
                    task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                )

            url_match = _HTTP_IMAGE_RE.search(content)
            if url_match:
                url = await persist_remote_image(url_match.group(0))
                return ImageGenerationResponse(
                    task_id=f"img-{int(time.time())}", status="completed", image_urls=[url]
                )

            errors.append("供应商没有返回任何图片")
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            raise AdapterError(
                "图片生成失败：API 服务未启动（连接被拒绝）。请检查服务是否运行，或切换到其他可用的图片 API。"
            ) from e
        except httpx.TimeoutException:
            raise AdapterError(f"生图请求超时（{settings.image_gen_timeout}s）。" + "；".join(errors))
        except httpx.HTTPStatusError as e:
            raise AdapterError(
                f"生图失败：HTTP {e.response.status_code}: {e.response.text[:200]}。" + "；".join(errors)
            )
        except httpx.HTTPError as e:
            errors.append(f"/chat/completions 请求失败: {e}")
        return None

    async def fetch_result(self, task_id: str) -> ImageGenerationResponse:
        """OpenAI 兼容接口是同步返回，不需要轮询"""
        return ImageGenerationResponse(task_id=task_id, status="completed", image_urls=[])
