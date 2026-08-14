"""Agent trace JSONL 持久化（W22）与体积轮转（3.1）。"""
from dataclasses import replace

from src.video_agent.core import tracer as tr_mod
from src.video_agent.core.tracer import AgentTracer


def test_trace_persisted_and_reloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    t1 = AgentTracer()
    t1.start_trace("用户消息")
    t1.start_step()
    t1.record_action("read_draft", "读取草稿", 10.0, True)
    t1.end_step(1, actions_applied=1, finish_reason="stop")
    rec = t1.finish_trace(total_actions=1)
    assert rec["trace_id"]

    # 模拟重启：新实例从 JSONL 恢复
    t2 = AgentTracer()
    traces = t2.get_recent_traces(10)
    assert any(x["trace_id"] == rec["trace_id"] for x in traces)
    loaded = next(x for x in traces if x["trace_id"] == rec["trace_id"])
    assert loaded["total_actions"] == 1
    assert loaded["steps"][0]["actions"][0]["name"] == "read_draft"


def test_trace_dedupe_on_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    t1 = AgentTracer()
    t1.start_trace("去重测试")
    t1.start_step()
    t1.end_step(1)
    rec = t1.finish_trace()

    # 手工追加重复行，模拟损坏/重复写入
    with open(tmp_path / "agent_traces.jsonl", "a", encoding="utf-8") as f:
        import json
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    t2 = AgentTracer()
    traces = t2.get_recent_traces(10)
    assert sum(1 for x in traces if x["trace_id"] == rec["trace_id"]) == 1


def _finish_one(t: AgentTracer, msg: str = "轮转测试") -> None:
    t.start_trace(msg)
    t.start_step()
    t.end_step(1)
    t.finish_trace()


def test_trace_file_rotation_on_size_limit(tmp_path, monkeypatch):
    """超限滚动：.1/.2 依次后移，超过保留份数的最旧一份丢弃"""
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tr_mod, "settings",
        replace(tr_mod.settings, trace_file_max_bytes=200, trace_rotation_keep=2),
    )
    base = tmp_path / "agent_traces.jsonl"
    base.write_text("x" * 300, encoding="utf-8")  # 超限的存量文件
    (tmp_path / "agent_traces.jsonl.1").write_text("old1", encoding="utf-8")
    (tmp_path / "agent_traces.jsonl.2").write_text("old2", encoding="utf-8")

    t = AgentTracer()
    _finish_one(t)

    # 轮转后：旧主文件 → .1，旧 .1 → .2，旧 .2（最旧）被丢弃；新主文件只含新记录
    # （阈值 400：814E6 记录新增 user_id 字段后单条约 303 字节）
    assert base.exists() and base.stat().st_size < 400
    assert (tmp_path / "agent_traces.jsonl.1").read_text(encoding="utf-8").startswith("x")
    assert (tmp_path / "agent_traces.jsonl.2").read_text(encoding="utf-8") == "old1"
    assert not (tmp_path / "agent_traces.jsonl.3").exists()


def test_trace_no_rotation_below_limit(tmp_path, monkeypatch):
    """未超限不轮转：追加写入不产生 .1"""
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tr_mod, "settings",
        replace(tr_mod.settings, trace_file_max_bytes=10 * 1024 * 1024),
    )
    t = AgentTracer()
    _finish_one(t)
    _finish_one(t)
    assert (tmp_path / "agent_traces.jsonl").exists()
    assert not (tmp_path / "agent_traces.jsonl.1").exists()
