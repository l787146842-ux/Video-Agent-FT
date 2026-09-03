"""评审返修批 canary：Critical-2 trace 三级留存永久空转。

根因（tracer.py _rotate_if_needed）：先把主文件 rename 成 .jsonl.1，随后对
self._persist_path（已被改名、不存在）调 compact_traces → 立即 return 全零，
三级留存 100% 不生效。修复：压缩目标改轮转产物 .jsonl.N（循环 n in 1..keep，
存在才压）；主文件老化记录另由 lifespan startup 单点补压（compact_persisted）。

同批 trace_retention.py 修复：
- 无/非法 timestamp（ts<=0）保守保留计 hot，绝不当 cold 销毁；
- 损坏行（JSON 解析失败/非 dict）原样保留、单独 corrupt 计数（不与 cold 共用销毁分支）；
- 读-改-写经模块级 _COMPACT_LOCK 串行；
- 首次实质压缩/丢弃前原文件另存 .pre-compact 备份。

canary 断言（规格原文）：timestamp=now-10d 的记录轮转后须被判 cold_dropped
（10d > 7d warm 窗口）或 _tier=warm；本文件同时钉死 now-3d → warm。
"""
import json
import time
from dataclasses import replace

from src.video_agent.utils.trace_retention import compact_traces


def _rec(trace_id: str, ts: float, reasoning: str = "思" * 200) -> dict:
    """构造一条贴近真实形态的 trace 记录（含重型字段 reasoning / actions[].args）。"""
    return {
        "trace_id": trace_id,
        "timestamp": ts,
        "user_message_preview": "用户消息",
        "total_ms": 100,
        "total_actions": 1,
        "steps": [{
            "step": 1, "timing_ms": 100,
            "token_usage": {"prompt": 10, "completion": 5},
            "actions_applied": 1, "finish_reason": "stop",
            "reasoning": reasoning,
            "actions": [{
                "name": "read_draft", "summary": "读取", "elapsed_ms": 10,
                "ok": True, "args": {"draft_id": "d-1"},
            }],
        }],
    }


def _lines(p) -> list:
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ===================== canary：cold / warm 分级判定 =====================

def test_canary_cold_record_dropped_after_compact(tmp_path):
    """canary：timestamp=now-10d（> 7d warm 窗口）经 compact_traces 判 cold_dropped。"""
    p = tmp_path / "agent_traces.jsonl.1"
    old_ts = time.time() - 10 * 86400  # 10 天前
    p.write_text(json.dumps(_rec("t-cold", old_ts), ensure_ascii=False) + "\n",
                 encoding="utf-8")

    stats = compact_traces(p)
    assert stats["total"] == 1
    assert stats["cold_dropped"] == 1, f"10d 记录未判 cold（留存空转）: {stats}"
    assert _lines(p) == [], "cold 记录未从文件丢弃"
    # 首次实质丢弃前另存 .pre-compact 备份（保留最原始未压缩态）
    backup = tmp_path / "agent_traces.jsonl.1.pre-compact"
    assert backup.exists()
    assert "t-cold" in backup.read_text(encoding="utf-8")


def test_canary_warm_record_tiered_after_compact(tmp_path):
    """canary：timestamp=now-3d（24h < 3d < 7d）经 compact_traces 判 warm（_tier=warm）。"""
    p = tmp_path / "agent_traces.jsonl.1"
    warm_ts = time.time() - 3 * 86400  # 3 天前
    p.write_text(json.dumps(_rec("t-warm", warm_ts), ensure_ascii=False) + "\n",
                 encoding="utf-8")

    stats = compact_traces(p)
    assert stats["total"] == 1
    assert stats["warm"] == 1, f"3d 记录未判 warm: {stats}"
    assert stats["cold_dropped"] == 0
    lines = _lines(p)
    assert len(lines) == 1
    compacted = json.loads(lines[0])
    assert compacted["_tier"] == "warm"
    assert compacted["trace_id"] == "t-warm"
    # reasoning 截断到 warm 窗口（默认 120 字符 + 省略号）
    assert len(compacted["steps"][0]["reasoning"]) == 121
    assert compacted["steps"][0]["reasoning"].endswith("…")
    # 重型字段 args 被剥离
    assert "args" not in compacted["steps"][0]["actions"][0]
    # .pre-compact 备份保留原始（含完整 reasoning）
    backup = tmp_path / "agent_traces.jsonl.1.pre-compact"
    assert backup.exists() and "思" * 200 in backup.read_text(encoding="utf-8")


def test_hot_record_preserved_verbatim(tmp_path):
    """hot（< 24h）保留全量：不压缩、不丢弃、无 .pre-compact（未发生实质压缩）。"""
    p = tmp_path / "agent_traces.jsonl.1"
    fresh = _rec("t-hot", time.time() - 60)  # 1 分钟前
    raw = json.dumps(fresh, ensure_ascii=False)
    p.write_text(raw + "\n", encoding="utf-8")

    stats = compact_traces(p)
    assert stats["hot"] == 1 and stats["warm"] == 0 and stats["cold_dropped"] == 0
    assert _lines(p) == [raw]  # 原样保留（未重写为压缩形态）
    assert not (tmp_path / "agent_traces.jsonl.1.pre-compact").exists()


# ===================== 保守销毁边界（评审返修 ①） =====================

def test_no_timestamp_preserved_as_hot_not_cold(tmp_path):
    """无 timestamp（ts<=0）无法判龄 → 保守保留计 hot，绝不当 cold 销毁。"""
    p = tmp_path / "agent_traces.jsonl.1"
    rec = _rec("t-nots", 0)
    rec.pop("timestamp")  # 完全无 timestamp 字段
    p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")

    stats = compact_traces(p)
    assert stats["hot"] == 1
    assert stats["cold_dropped"] == 0, "无 timestamp 被误当 cold 销毁"
    lines = _lines(p)
    assert len(lines) == 1 and "t-nots" in lines[0]


def test_zero_timestamp_preserved_as_hot(tmp_path):
    """timestamp=0（非法/缺省）同样保守保留计 hot。"""
    p = tmp_path / "agent_traces.jsonl.1"
    p.write_text(json.dumps(_rec("t-zero", 0), ensure_ascii=False) + "\n",
                 encoding="utf-8")
    stats = compact_traces(p)
    assert stats["hot"] == 1 and stats["cold_dropped"] == 0


def test_corrupt_line_preserved_and_counted(tmp_path):
    """损坏行（JSON 解析失败）原样保留 + 单独 corrupt 计数（不与 cold 共用销毁分支）。"""
    p = tmp_path / "agent_traces.jsonl.1"
    p.write_text(
        "这不是合法JSON\n"
        + json.dumps(_rec("t-ok", time.time()), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    stats = compact_traces(p)
    assert stats["corrupt"] == 1
    assert stats["cold_dropped"] == 0
    lines = _lines(p)
    # 损坏行原样保留（未被默默丢弃），合法 hot 行也在
    assert any("这不是合法JSON" in ln for ln in lines)
    assert any("t-ok" in ln for ln in lines)


def test_non_dict_json_counted_corrupt(tmp_path):
    """非对象 JSON（数组/数字）同损坏行口径保守保留 + corrupt 计数。"""
    p = tmp_path / "agent_traces.jsonl.1"
    p.write_text("[1, 2, 3]\n42\n", encoding="utf-8")
    stats = compact_traces(p)
    assert stats["corrupt"] == 2
    assert stats["cold_dropped"] == 0
    assert len(_lines(p)) == 2


# ===================== 根因回归：轮转压缩目标 = .jsonl.N（非消失的主文件） =====================

def test_rotation_compacts_rotated_product_not_vanished_main(tmp_path, monkeypatch):
    """根因回归：轮转后压缩目标 = 轮转产物 .jsonl.N，而非已 rename 消失的主文件。

    原实现 rename 主文件→.1 后对 self._persist_path（已不存在）调 compact_traces
    → 立即 return 全零，三级留存空转。修复后 .1 里的老化记录被实际压缩（cold 丢弃）。"""
    from src.video_agent.core import tracer as tr_mod
    from src.video_agent.core.tracer import AgentTracer

    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tr_mod, "settings",
        replace(
            tr_mod.settings,
            trace_file_max_bytes=100,        # 强制轮转
            trace_rotation_keep=2,
            trace_retention_enabled=True,    # 开启分级留存（默认关）
            log_file_enabled=True,
        ),
    )
    base = tmp_path / "agent_traces.jsonl"
    old = _rec("t-old", time.time() - 10 * 86400)
    old["padding"] = "x" * 200  # 撑过 max_bytes 触发轮转
    base.write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")

    t = AgentTracer()
    t.start_trace("新消息")
    t.start_step()
    t.end_step(1)
    t.finish_trace()  # 触发 _persist_record → _rotate_if_needed → 压缩 .jsonl.N

    # 轮转：旧主文件 → .jsonl.1，随后 .1 被压缩（10d 记录 cold_dropped）
    rotated = tmp_path / "agent_traces.jsonl.1"
    assert rotated.exists()
    assert "t-old" not in rotated.read_text(encoding="utf-8"), \
        "轮转产物未被压缩（三级留存仍空转——根因未修）"
    # .pre-compact 备份保留原始老化记录
    backup = tmp_path / "agent_traces.jsonl.1.pre-compact"
    assert backup.exists() and "t-old" in backup.read_text(encoding="utf-8")
    # 新记录写入全新主文件（不含老化记录）
    assert base.exists() and "t-old" not in base.read_text(encoding="utf-8")


def test_rotation_skips_compact_when_retention_disabled(tmp_path, monkeypatch):
    """守卫：trace_retention_enabled=False（默认）时轮转不改写 .jsonl.N（测试/验收
    子进程与 log_file_enabled 同守卫，避免多进程争用磁盘 trace）。"""
    from src.video_agent.core import tracer as tr_mod
    from src.video_agent.core.tracer import AgentTracer

    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tr_mod, "settings",
        replace(
            tr_mod.settings,
            trace_file_max_bytes=100,
            trace_rotation_keep=2,
            trace_retention_enabled=False,   # 默认关
            log_file_enabled=True,
        ),
    )
    base = tmp_path / "agent_traces.jsonl"
    old = _rec("t-keep", time.time() - 10 * 86400)
    old["padding"] = "x" * 200
    base.write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")

    t = AgentTracer()
    t.start_trace("新消息")
    t.start_step()
    t.end_step(1)
    t.finish_trace()

    rotated = tmp_path / "agent_traces.jsonl.1"
    assert rotated.exists()
    # 未开启留存：轮转产物原样保留（老化记录不被压缩/丢弃）
    assert "t-keep" in rotated.read_text(encoding="utf-8")
    assert not (tmp_path / "agent_traces.jsonl.1.pre-compact").exists()


def test_compact_persisted_targets_main_file(tmp_path, monkeypatch):
    """lifespan startup 单点：compact_persisted 对主文件补压（轮转只压 .jsonl.N，
    主文件里长期不轮转的老化记录由本方法在启动时收敛一次）。"""
    from src.video_agent.core import tracer as tr_mod
    from src.video_agent.core.tracer import AgentTracer

    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tr_mod, "settings",
        replace(
            tr_mod.settings,
            trace_retention_enabled=True,
            log_file_enabled=True,
        ),
    )
    base = tmp_path / "agent_traces.jsonl"
    base.write_text(
        json.dumps(_rec("t-main-cold", time.time() - 10 * 86400), ensure_ascii=False) + "\n"
        + json.dumps(_rec("t-main-hot", time.time() - 60), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    t = AgentTracer()
    t.compact_persisted()  # startup 单点补压主文件

    lines = _lines(base)
    # 10d 老化记录被 cold 丢弃，1 分钟前 hot 记录保留
    assert all("t-main-cold" not in ln for ln in lines)
    assert any("t-main-hot" in ln for ln in lines)
    assert (tmp_path / "agent_traces.jsonl.pre-compact").exists()
