"""Agent trace 分级留存策略模块。

独立于 core/tracer.py 的留存增强层——tracer 负责写入与基础轮转，
本模块负责「分级压缩」：按记录年龄分 hot/warm/cold 三级，
warm 级剥离重型字段（reasoning 全文、args 预览）只保留摘要，
cold 级由既有轮转丢弃。

调用时机：tracer._rotate_if_needed() 轮转后调用 compact_traces()，
或外部定时任务调用（如 startup hook / cron）。

设计约束：
- 不依赖 config.py Settings（避免与 Chloe 独占文件耦合）；
  参数以函数入参传入，调用方可从 settings getattr 取或硬编码。
- 只做读-改-写（原子），不引入新依赖。
- JSONL 格式兼容：压缩后仍为合法 JSONL，前端 /api/agent/traces 可读。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# 读-改-写串行锁（模块级）：compact_traces 对同一文件先读全文再原子重写，
# 并发调用会互盖。前提：与追加方（tracer._persist_record）约定单点串行——
# 压缩仅在「轮转时（同步于追写线程）」与「startup 单点」两处触发，本锁
# 再护同进程内可能的重入/多调用串行；跨进程并发写不在本锁职责内
# （生产为单服务进程写入，测试/验收进程置 trace_retention_enabled=false 不改写）。
_COMPACT_LOCK = threading.Lock()


# ===== 分级策略参数（默认值；调用方可覆盖） =====

# hot 级保留时长（秒）：此窗口内的 trace 保留全量字段
DEFAULT_HOT_WINDOW_S = 3600 * 24  # 24 小时

# warm 级保留时长（秒）：超过 hot 但未超 warm 的记录压缩为摘要
DEFAULT_WARM_WINDOW_S = 3600 * 24 * 7  # 7 天

# warm 级保留的重型字段最大长度（压缩后 reasoning 截断到此长度）
DEFAULT_WARM_REASONING_MAX = 120


def _strip_to_warm(record: Dict[str, Any], reasoning_max: int) -> Dict[str, Any]:
    """将 hot 级记录压缩为 warm 级：剥离重型字段，保留审计骨架。

    保留字段：trace_id, timestamp, user_message_preview, total_ms,
              total_actions, steps[].{step, timing_ms, token_usage,
              actions_applied, finish_reason, actions[].{name, summary, elapsed_ms, ok}}
    剥离字段：steps[].reasoning（截断为摘要）、steps[].actions[].args（移除）、
              steps[].gates[].message（截断）
    """
    out: Dict[str, Any] = {
        "trace_id": record.get("trace_id"),
        "timestamp": record.get("timestamp"),
        "user_message_preview": record.get("user_message_preview"),
        "total_ms": record.get("total_ms"),
        "total_actions": record.get("total_actions"),
        "_tier": "warm",  # 标记已压缩
    }
    steps_out: List[Dict[str, Any]] = []
    for step in record.get("steps") or []:
        if not isinstance(step, dict):
            continue
        s: Dict[str, Any] = {
            "step": step.get("step"),
            "timing_ms": step.get("timing_ms"),
            "token_usage": step.get("token_usage"),
            "actions_applied": step.get("actions_applied"),
            "finish_reason": step.get("finish_reason"),
        }
        # reasoning 截断为摘要
        reasoning = step.get("reasoning") or ""
        if reasoning:
            s["reasoning"] = reasoning[:reasoning_max] + ("…" if len(reasoning) > reasoning_max else "")
        # actions 保留骨架，移除 args
        actions_out: List[Dict[str, Any]] = []
        for act in step.get("actions") or []:
            if not isinstance(act, dict):
                continue
            a: Dict[str, Any] = {
                "name": act.get("name"),
                "summary": act.get("summary"),
                "elapsed_ms": act.get("elapsed_ms"),
                "ok": act.get("ok"),
            }
            if act.get("stage"):
                a["stage"] = act["stage"]
            if act.get("result_summary"):
                a["result_summary"] = act["result_summary"][:80]
            actions_out.append(a)
        if actions_out:
            s["actions"] = actions_out
        # gates 保留 rule_id/layer/ok，移除 message 全文
        gates_out: List[Dict[str, Any]] = []
        for g in step.get("gates") or []:
            if not isinstance(g, dict):
                continue
            gates_out.append({
                "rule_id": g.get("rule_id"),
                "layer": g.get("layer"),
                "ok": g.get("ok"),
                "overridden": g.get("overridden", False),
            })
        if gates_out:
            s["gates"] = gates_out
        steps_out.append(s)
    if steps_out:
        out["steps"] = steps_out
    return out


def compact_traces(
    persist_path: Path,
    *,
    hot_window_s: float = DEFAULT_HOT_WINDOW_S,
    warm_window_s: float = DEFAULT_WARM_WINDOW_S,
    reasoning_max: int = DEFAULT_WARM_REASONING_MAX,
) -> Dict[str, int]:
    """对 JSONL trace 文件执行分级压缩（原地重写）。

    返回统计：{"total": N, "hot": N, "warm": N, "cold_dropped": N, "corrupt": N}

    - hot（< hot_window_s）：保留全量
    - warm（hot_window_s ~ warm_window_s）：压缩为摘要
    - cold（> warm_window_s）：丢弃

    已经是 warm 级的记录（带 _tier=warm 标记）不重复处理。
    文件不存在或为空时静默返回。

    保守销毁边界（评审返修 Critical-2）：无/非法 timestamp（ts≤ 0）无法判龄，
    保守保留计 hot，绝不当 cold 销毁；损坏行（JSON 解析失败/非 dict）原样保留、
    单独 corrupt 计数（不与 cold 共用销毁分支，避免不可解析的数据被默默丢弃）。
    读-改-写经模块级 _COMPACT_LOCK 串行；首次发生实质压缩/丢弃前，原文件另存
    `.pre-compact` 备份（已存在不覆盖，保留最原始未压缩态）。
    """
    stats = {"total": 0, "hot": 0, "warm": 0, "cold_dropped": 0, "corrupt": 0}
    if not persist_path.exists():
        return stats

    with _COMPACT_LOCK:
        try:
            raw = persist_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[TraceRetention] 读取失败: {e}")
            return stats

        now = time.time()
        kept: List[str] = []

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            stats["total"] += 1
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                # 损坏行：保守原样保留（不与 cold 共用销毁分支），单独 corrupt 计数
                stats["corrupt"] += 1
                kept.append(line)
                continue
            if not isinstance(record, dict):
                # 非对象 JSON（数字/数组等）：同损坏行口径保守保留
                stats["corrupt"] += 1
                kept.append(line)
                continue

            try:
                ts = float(record.get("timestamp") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts <= 0:
                # 无/非法 timestamp：无法判龄，保守保留计 hot（绝不当 cold 销毁）
                kept.append(line)
                stats["hot"] += 1
                continue

            age = now - ts
            if age > warm_window_s:
                # cold：丢弃
                stats["cold_dropped"] += 1
                continue
            elif age > hot_window_s:
                # warm：压缩（已压缩的跳过）
                if record.get("_tier") == "warm":
                    kept.append(line)
                else:
                    compacted = _strip_to_warm(record, reasoning_max)
                    kept.append(json.dumps(compacted, ensure_ascii=False))
                stats["warm"] += 1
            else:
                # hot：全量保留
                kept.append(line)
                stats["hot"] += 1

        # 首次实质压缩/丢弃前，原文件另存 .pre-compact 备份（仅首次，已存在不覆盖）
        if stats["warm"] > 0 or stats["cold_dropped"] > 0:
            try:
                backup = persist_path.parent / (persist_path.name + ".pre-compact")
                if not backup.exists():
                    backup.write_text(raw, encoding="utf-8")
            except Exception as e:
                logger.warning(f"[TraceRetention] .pre-compact 备份失败（继续压缩）: {e}")

        # 原子重写（先写临时文件再 rename，防断电损坏）
        try:
            tmp = persist_path.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            tmp.replace(persist_path)
        except Exception as e:
            logger.warning(f"[TraceRetention] 重写失败: {e}")

    if stats["cold_dropped"] > 0 or stats["warm"] > 0:
        logger.info(
            f"[TraceRetention] 分级压缩完成: {stats['total']} 条 → "
            f"hot {stats['hot']} / warm {stats['warm']} / dropped {stats['cold_dropped']}"
            f" / corrupt {stats['corrupt']}"
        )
    return stats


def get_retention_config(
    settings_obj: Optional[Any] = None,
) -> Dict[str, Any]:
    """从 settings 对象提取留存配置（getattr 防御性读取，缺省走默认值）。

    调用方传入 settings 实例即可；不直接 import config.py（避免耦合）。
    """
    cfg: Dict[str, Any] = {
        "hot_window_s": DEFAULT_HOT_WINDOW_S,
        "warm_window_s": DEFAULT_WARM_WINDOW_S,
        "reasoning_max": DEFAULT_WARM_REASONING_MAX,
    }
    if settings_obj is not None:
        cfg["hot_window_s"] = getattr(settings_obj, "trace_hot_window_s", DEFAULT_HOT_WINDOW_S)
        cfg["warm_window_s"] = getattr(settings_obj, "trace_warm_window_s", DEFAULT_WARM_WINDOW_S)
        cfg["reasoning_max"] = getattr(settings_obj, "trace_warm_reasoning_max", DEFAULT_WARM_REASONING_MAX)
    return cfg
