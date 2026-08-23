# -*- coding: utf-8 -*-
"""任务表写入侧容量保护（任务 #9 E-3）。

背景：data/generation_tasks.json 与 data/agent_tasks.json 已收敛为
workspace/state.sqlite3 kv 表载荷（任务 #24），旧文件停写。本组用例钉死
kv 载荷在启动恢复路径上的 TTL/上限收敛：

- AgentTaskManager：启动恢复后按 TTL（3600s）与上限（50）清理并回写 kv；
  超上限时保留最新条目（收敛至上限，不过度清理）、运行中不清理；
- GenerationTaskManager：生成日志恢复路径同样收敛至写入侧上限（200）。
"""
import time

from src.video_agent.web.task_store import TaskStore


def _mk_store(tmp_path):
    return TaskStore(tmp_path / "state.sqlite3")


class TestAgentTaskStartupPurge:
    def test_expired_and_over_cap_tasks_purged_on_startup(self, tmp_path):
        from src.video_agent.web.agent_task_manager import AgentTaskManager, _TASK_MAX

        now = time.time()
        tasks = []
        # 3 条已过期（超过 TTL 且非运行中）：启动即清
        for i in range(3):
            tasks.append({"task_id": f"old-{i}", "project_id": "p",
                          "status": "done", "created_at": now - 7200 + i})
        # 60 条 TTL 内的已完成任务：超过上限 50，按 created_at 淘汰最旧
        for i in range(60):
            tasks.append({"task_id": f"new-{i}", "project_id": "p",
                          "status": "done", "created_at": now - 60 + i * 0.01})
        store = _mk_store(tmp_path)
        store.save("agent_tasks", {"tasks": tasks})

        mgr = AgentTaskManager(store=store, legacy_file=tmp_path / "none.json")
        ids = set(mgr._tasks)
        assert not any(i.startswith("old-") for i in ids), "过期任务启动即清"
        assert len(ids) == _TASK_MAX, "总数收敛至上限（不过度清理）"
        # 保留最新：最旧的 10 条 new-0..new-9 被淘汰
        assert "new-9" not in ids and "new-59" in ids
        # kv 载荷同步收敛（写入侧保护）
        persisted = store.load("agent_tasks")["tasks"]
        assert len(persisted) == _TASK_MAX

    def test_running_records_not_purged_by_cap(self, tmp_path):
        from src.video_agent.web.agent_task_manager import AgentTaskManager

        now = time.time()
        store = _mk_store(tmp_path)
        mgr = AgentTaskManager(store=store, legacy_file=tmp_path / "none.json")
        # 60 条超限：55 条运行中 + 5 条已完成
        for i in range(60):
            mgr._tasks[f"t-{i}"] = {
                "task_id": f"t-{i}", "project_id": "p",
                "status": "running" if i < 55 else "done",
                "created_at": now + i,
            }
        mgr._purge_stale()
        # 运行中一条不清；已完成全部淘汰后总数仍可能高于上限（运行中不可删）
        assert all(f"t-{i}" in mgr._tasks for i in range(55))
        assert len(mgr._tasks) == 55


class TestGenerationLogLoadCap:
    def test_gen_logs_capped_on_recovery(self, tmp_path):
        from src.video_agent.web.task_manager import GenerationTaskManager, _GEN_LOG_MAX

        logs = [{"id": f"gl-{i}", "media_type": "image", "status": "succeeded"}
                for i in range(_GEN_LOG_MAX + 100)]
        store = _mk_store(tmp_path)
        store.save("generation_tasks", {"tasks": [], "logs": logs})

        mgr = GenerationTaskManager(store=store, legacy_file=tmp_path / "none.json")
        assert len(mgr._gen_logs) == _GEN_LOG_MAX
        # 收敛后的载荷回写 kv（下一次落盘即收敛）
        mgr._persist()
        assert len(store.load("generation_tasks")["logs"]) == _GEN_LOG_MAX
