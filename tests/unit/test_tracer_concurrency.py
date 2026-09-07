"""tracer 并发串线缺陷回归（#16）：contextvar 隔离后并行任务各写各的 trace。

事故背景：旧实现以实例属性 _current 保存「当前 trace」，SSE 断连后任务转
后台继续跑、用户同时开新会话时两条 trace 互相覆盖，agent_traces.jsonl
span 归属失真。改造为 contextvar 持有（先例 StateManager.create_task_bound），
本文件覆盖：
1. 两个独立上下文交替写 → span 归属各自正确、无串线
2. 两个 asyncio 任务真并行（模拟后台任务 + 新会话）→ 同上
3. 轮前机械动作缓冲（record_pre_turn）也按上下文隔离收养
4. 轮转保留份数收紧为 2 份（运行时残留策略）
"""
import asyncio
import contextvars
from dataclasses import replace

import pytest

from src.video_agent.core import tracer as tr_mod
from src.video_agent.core.tracer import AgentTracer


def _action_names(rec: dict) -> list:
    """trace dict 里全部 step 的 action 名（保序）"""
    return [a["name"] for s in rec.get("steps", []) for a in s.get("actions", [])]


def _gate_rules(rec: dict) -> list:
    return [g["rule_id"] for s in rec.get("steps", []) for g in s.get("gates", [])]


def test_interleaved_contexts_no_crosstalk(tmp_path, monkeypatch):
    """两个独立上下文交替执行 start/record/end/finish，span 归属零串线。

    模拟：后台任务（ctx_a）与新会话（ctx_b）交错推进，
    旧实例属性实现下 B 的 start_trace 会覆盖 A 的 _current 导致串线。
    """
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    tracer = AgentTracer()

    # 全新空上下文，模拟两个独立的 asyncio 任务上下文
    ctx_a = contextvars.Context()
    ctx_b = contextvars.Context()

    # 交替开始：各自 start_trace
    tid_a = ctx_a.run(tracer.start_trace, "后台任务续跑", "user-a")
    tid_b = ctx_b.run(tracer.start_trace, "新会话第一轮", "user-b")
    assert tid_a != tid_b

    # 交替写 span（穿插顺序模拟事件循环交错调度）
    ctx_a.run(tracer.start_step)
    ctx_b.run(tracer.start_step)
    ctx_a.run(tracer.record_action, "script_analyze", "剧本分析")
    ctx_b.run(tracer.record_action, "storyboard_key_elements", "拆关键元素")
    ctx_a.run(tracer.record_reasoning, "后台任务的思考")
    ctx_b.run(tracer.record_reasoning, "新会话的思考")
    ctx_a.run(tracer.record_gate, "rule-a", "exec", True)
    ctx_b.run(tracer.record_gate, "rule-b", "exec", True)
    ctx_a.run(tracer.record_subaction, "sub_a", "子步骤A")
    ctx_b.run(tracer.record_subaction, "sub_b", "子步骤B")
    ctx_a.run(tracer.record_action, "parent_a", "父条目承接子步骤A")
    ctx_b.run(tracer.record_action, "parent_b", "父条目承接子步骤B")
    ctx_a.run(tracer.record_llm_call)
    ctx_b.run(tracer.record_llm_call)
    ctx_b.run(tracer.record_llm_call)  # B 两次模型调用
    ctx_a.run(tracer.end_step, 1, 2, "fc_done")
    ctx_b.run(tracer.end_step, 1, 2, "fc_continue")

    # 第二轮再交错一次，加大串线暴露面
    ctx_b.run(tracer.start_step)
    ctx_b.run(tracer.record_action, "shots_split", "拆分镜")
    ctx_b.run(tracer.end_step, 2, 1, "fc_done")

    rec_a = ctx_a.run(tracer.finish_trace, 2)
    rec_b = ctx_b.run(tracer.finish_trace, 3)

    # 归属断言：各自的 span 只落在各自的 trace
    # （子步骤按设计挂在承接它的父条目之后）
    assert rec_a["trace_id"] == tid_a and rec_b["trace_id"] == tid_b
    assert rec_a["user_id"] == "user-a" and rec_b["user_id"] == "user-b"
    names_a = _action_names(rec_a)
    names_b = _action_names(rec_b)
    assert names_a == ["script_analyze", "parent_a", "sub_a"]
    assert names_b == ["storyboard_key_elements", "parent_b", "sub_b", "shots_split"]
    assert not set(names_a) & set(names_b), "两条 trace 的 span 不得交叉"
    assert _gate_rules(rec_a) == ["rule-a"]
    assert _gate_rules(rec_b) == ["rule-b"]
    assert rec_a["steps"][0]["reasoning"] == "后台任务的思考"
    assert rec_b["steps"][0]["reasoning"] == "新会话的思考"
    assert rec_a["llm_calls"] == 1 and rec_b["llm_calls"] == 2
    assert len(rec_a["steps"]) == 1 and len(rec_b["steps"]) == 2

    # finish 后各上下文 current 清空，互不影响
    assert ctx_a.run(tracer.finish_trace) == {}
    assert ctx_b.run(tracer.finish_trace) == {}

    # 落盘归属同样正确（JSONL 按 trace_id 分行）
    traces = tracer.get_recent_traces(10)
    ids = {t["trace_id"] for t in traces}
    assert {tid_a, tid_b} <= ids


@pytest.mark.asyncio
async def test_parallel_async_tasks_no_crosstalk(tmp_path, monkeypatch):
    """asyncio 并行：模拟「转后台的任务」与「新会话」同时跑 agent 循环。

    asyncio.create_task 创建时拷贝上下文，contextvar 改造后两个 worker
    各持一份追踪态；中途 await 交错调度不得造成 span 串线。
    """
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    tracer = AgentTracer()

    async def worker(tag: str, n_steps: int):
        tracer.start_trace(f"任务{tag}", user_id=f"uid-{tag}")
        for step in range(1, n_steps + 1):
            tracer.start_step()
            tracer.record_action(f"tool-{tag}-{step}", f"步骤{step}")
            tracer.record_reasoning(f"thinking-{tag}-{step}")
            await asyncio.sleep(0.01)  # 让出控制权制造交错
            tracer.record_llm_call()
            tracer.end_step(step, actions_applied=1, finish_reason="fc_continue")
        return tracer.finish_trace(total_actions=n_steps)

    rec_a, rec_b = await asyncio.gather(
        worker("A", 3), worker("B", 2),
    )

    assert rec_a["trace_id"] != rec_b["trace_id"]
    assert _action_names(rec_a) == ["tool-A-1", "tool-A-2", "tool-A-3"]
    assert _action_names(rec_b) == ["tool-B-1", "tool-B-2"]
    assert rec_a["steps"][2]["reasoning"] == "thinking-A-3"
    assert rec_b["steps"][1]["reasoning"] == "thinking-B-2"
    assert rec_a["llm_calls"] == 3 and rec_b["llm_calls"] == 2
    assert rec_a["user_id"] == "uid-A" and rec_b["user_id"] == "uid-B"


def test_pre_turn_actions_isolated_per_context(tmp_path, monkeypatch):
    """轮前机械动作缓冲同样按上下文收养：A 的轮前动作不会被 B 的
    start_trace 收养走（旧全局缓冲在并行下会把动作挂错会话）。
    归档路径与现网一致：start_trace 收养 → end_step 归档进 step。"""
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    tracer = AgentTracer()

    ctx_a = contextvars.Context()
    ctx_b = contextvars.Context()
    ctx_a.run(tracer.record_pre_turn, "write_document", "向导落盘A")

    tid_b = ctx_b.run(tracer.start_trace, "新会话")
    tid_a = ctx_a.run(tracer.start_trace, "后台任务")

    # A 收养的轮前动作在第一步归档；B 无轮前动作
    ctx_a.run(tracer.end_step, 1, 1, "stop")
    ctx_b.run(tracer.end_step, 1, 0, "stop")
    rec_a = ctx_a.run(tracer.finish_trace)
    rec_b = ctx_b.run(tracer.finish_trace)

    names_a = _action_names(rec_a)
    assert "write_document" in names_a, "轮前动作必须被同上下文 start_trace 收养"
    assert _action_names(rec_b) == [], "新会话不得收养别的上下文的轮前动作"
    assert tid_a != tid_b


def test_default_context_unaffected_after_parallel():
    """未 start_trace 的干净上下文保持无 trace：record_* 空转不抛错
    （兼容无 trace 场景调用）。用全新空上下文模拟干净的任务上下文，
    不受其他测试在默认上下文留下的活跃 trace 影响。"""

    def _assert_noop():
        tracer = AgentTracer()
        entry = tracer.record_action("orphan_tool", "无 trace 场景")
        assert entry["name"] == "orphan_tool"
        tracer.record_reasoning("ignored")
        tracer.record_gate("rule-x", "exec", True)  # 全局流仍记录
        tracer.record_llm_call()
        tracer.end_step(1)
        assert tracer.finish_trace() == {}

    contextvars.Context().run(_assert_noop)


def test_inherited_shared_state_severed_on_start_trace(tmp_path, monkeypatch):
    """create_task 拷贝上下文场景：子上下文继承了父上下文的追踪态对象，
    start_trace 必须新建对象绑定本上下文，与父对象彻底切割不串写。"""
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    tracer = AgentTracer()

    ctx_parent = contextvars.Context()
    ctx_parent.run(tracer.start_trace, "父会话")
    ctx_parent.run(tracer.start_step)
    ctx_parent.run(tracer.record_action, "parent_tool", "父会话工具")

    # 模拟 asyncio.create_task：子任务拷贝父上下文（含同一追踪态对象引用）
    ctx_child = ctx_parent.run(contextvars.copy_context)

    # 子任务开新 trace：新建对象，父对象不受影响
    ctx_child.run(tracer.start_trace, "转后台续跑")
    ctx_child.run(tracer.start_step)
    ctx_child.run(tracer.record_action, "child_tool", "后台工具")
    ctx_child.run(tracer.end_step, 1, 1, "fc_done")
    rec_child = ctx_child.run(tracer.finish_trace, 1)

    # 父上下文继续自己的 trace，未受子上下文影响
    ctx_parent.run(tracer.end_step, 1, 1, "fc_done")
    rec_parent = ctx_parent.run(tracer.finish_trace, 1)

    assert _action_names(rec_child) == ["child_tool"]
    assert _action_names(rec_parent) == ["parent_tool"]
    assert rec_child["trace_id"] != rec_parent["trace_id"]


def test_rotation_keep_default_tightened_to_two(monkeypatch):
    """运行时残留策略（#16）：轮转保留份数默认收紧为 2 份。
    （本地 .env 的 TRACE_ROTATION_KEEP 会经 load_dotenv 污染 Settings，
    测默认值须显式清除该环境变量后重建 settings）"""
    monkeypatch.delenv("TRACE_ROTATION_KEEP", raising=False)
    from src.video_agent.config import Settings

    fresh = Settings()
    assert fresh.trace_rotation_keep == 2


def test_rotation_discards_beyond_two_keeps(tmp_path, monkeypatch):
    """keep=2 生效：轮转后只保留主文件 + .1 + .2，.3 及更旧一律丢弃。"""
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tr_mod, "settings",
        replace(tr_mod.settings, trace_file_max_bytes=200, trace_rotation_keep=2),
    )
    base = tmp_path / "agent_traces.jsonl"
    base.write_text("x" * 300, encoding="utf-8")
    (tmp_path / "agent_traces.jsonl.1").write_text("old1", encoding="utf-8")
    (tmp_path / "agent_traces.jsonl.2").write_text("old2", encoding="utf-8")

    t = AgentTracer()
    t.start_trace("轮转收紧")
    t.start_step()
    t.end_step(1)
    t.finish_trace()

    assert base.exists() and (tmp_path / "agent_traces.jsonl.1").exists()
    assert (tmp_path / "agent_traces.jsonl.2").exists()
    assert not (tmp_path / "agent_traces.jsonl.3").exists(), \
        "保留份数收紧为 2：第 3 份必须丢弃"
