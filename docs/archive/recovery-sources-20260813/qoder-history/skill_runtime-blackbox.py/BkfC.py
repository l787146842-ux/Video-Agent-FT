"""内层模型黑匣子存档（888 事故）：异常发生时把「当时的完整指令 + 模型的完整
输出（含思考）」落盘备查。

背景：外层模型的思考随 trace 落盘，但执行器内层模型（写提示词/拆解）的答卷
解析完就扔，事故发生后无法定责（模型到底写没写 @、到底在纠结什么）。
本模块只落盘、不进上下文——不花一个上下文 token，只占一点硬盘。

触发时机：输出被截断 / 零产出 / 校验不过（由调用方判定后调 dump_case）。
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.utils.paths import LOGS_DIR

_BLACKBOX_DIR = LOGS_DIR / "blackbox"
_KEEP_MAX = 20          # 最多保留的档案数（超出删最旧）
_REASONING_MAX = 200000  # 思考内容单档截断上限（防异常巨量思考撑爆磁盘）


def dump_case(
    kind: str,
    reason: str,
    system: str,
    user: str,
    content: str,
    finish: str = "",
    reasoning: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """落盘一份黑匣子档案，返回档案路径（失败返回空串，绝不抛异常打断主流程）。"""
    try:
        _BLACKBOX_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        path = _BLACKBOX_DIR / f"{ts}-{kind}.json"
        record = {
            "kind": kind,
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "finish_reason": finish,
            "system_prompt": system or "",
            "user_prompt": user or "",
            "model_output": content or "",
            "output_chars": len(content or ""),
            "extra": extra or {},
        }
        reasoning_text = "".join(reasoning or [])
        if reasoning_text:
            record["reasoning"] = reasoning_text[:_REASONING_MAX]
            record["reasoning_chars"] = len(reasoning_text)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8",
        )
        _rotate()
        logger.info(f"[Blackbox] 异常档案已落盘：{path.name}（{reason}）")
        return str(path)
    except Exception as e:  # 黑匣子故障不得影响主流程
        logger.warning(f"[Blackbox] 档案落盘失败（不影响主流程）: {e}")
        return ""


def _rotate() -> None:
    files = sorted(_BLACKBOX_DIR.glob("*.json"))
    for f in files[:-_KEEP_MAX]:
        try:
            f.unlink()
        except Exception:
            pass
