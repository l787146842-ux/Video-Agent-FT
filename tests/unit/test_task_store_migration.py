"""任务 #24 存储层单一事实源收敛：迁移与单源读写守护。

覆盖：
1. TaskStore（workspace/state.sqlite3 kv 表）事务性 KV 读写；
2. agent_tasks.json / generation_tasks.json 旧文件一次性导入兜底，
   导入后停写（旧文件内容冻结，后续落盘只进 sqlite）；
3. StateManager sqlite 后端全链路单源：保存后零 JSON 镜像产出
   （projects/*/state.json、index.json、studio_state.json 均不新增）。
"""
import json
import time

from src.video_agent.web.task_store import TaskStore


class TestTaskStore:
    def test_roundtrip_and_exists(self, tmp_path):
        store = TaskStore(tmp_path / "state.sqlite3")
        assert store.load("k") is None
        assert not store.exists("k")
        store.save("k", {"tasks": [{"task_id": "t1"}], "logs": []})
        assert store.exists("k")
        assert store.load("k") == {"tasks": [{"task_id": "t1"}], "logs": []}

    def test_overwrite_is_atomic_replace(self, tmp_path):
        store = TaskStore(tmp_path / "state.sqlite3")
        store.save("k", {"v": 1})
        store.save("k", {"v": 2})
        assert store.load("k") == {"v": 2}

    def test_corrupt_payload_returns_none(self, tmp_path):
        import sqlite3

        db = tmp_path / "state.sqlite3"
        store = TaskStore(db)
        conn = sqlite3.connect(db)
        conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('bad', '{not-json')")
        conn.commit()
        conn.close()
        assert store.load("bad") is None


class TestAgentTasksMigration:
    def test_legacy_file_imported_once_then_write_stopped(self, tmp_path):
        from src.video_agent.web.agent_task_manager import AgentTaskManager

        legacy = tmp_path / "agent_tasks.json"
        legacy.write_text(json.dumps({"tasks": [
            {"task_id": "agt-1", "project_id": "p1", "status": "running", "created_at": 1.0},
            {"task_id": "agt-2", "project_id": "p1", "status": "done", "created_at": 2.0},
        ]}), encoding="utf-8")
        store = TaskStore(tmp_path / "state.sqlite3")

        mgr = AgentTaskManager(store=store, legacy_file=legacy)
        # 恢复语义不变：running → interrupted（重启无 worker）
        assert mgr.get("agt-1")["status"] == "interrupted"
        assert mgr.get("agt-2")["status"] == "done"
        # 旧文件导入后停写：内容冻结，后续落盘只进 sqlite
        before = legacy.read_text(encoding="utf-8")
        mgr._persist()
        assert legacy.read_text(encoding="utf-8") == before
        assert any(t["task_id"] == "agt-1" for t in store.load("agent_tasks")["tasks"])

    def test_import_is_idempotent(self, tmp_path):
        from src.video_agent.web.agent_task_manager import AgentTaskManager

        legacy = tmp_path / "agent_tasks.json"
        legacy.write_text(json.dumps({"tasks": [
            {"task_id": "agt-1", "project_id": "p1", "status": "done", "created_at": 1.0},
        ]}), encoding="utf-8")
        store = TaskStore(tmp_path / "state.sqlite3")

        AgentTaskManager(store=store, legacy_file=legacy)
        # sqlite 已有数据：旧文件即便变化也不再导入（key 在场即跳过）
        legacy.write_text(json.dumps({"tasks": [
            {"task_id": "agt-x", "project_id": "p1", "status": "done", "created_at": 9.0},
        ]}), encoding="utf-8")
        AgentTaskManager(store=store, legacy_file=legacy)
        ids = {t["task_id"] for t in store.load("agent_tasks")["tasks"]}
        assert "agt-x" not in ids


class TestGenerationTasksMigration:
    def test_legacy_file_imported_and_processing_marked_failed(self, tmp_path):
        from src.video_agent.web.task_manager import GenerationTaskManager

        legacy = tmp_path / "generation_tasks.json"
        now = time.time()
        legacy.write_text(json.dumps({
            "tasks": [
                {"task_id": "gen-1", "status": "processing", "created_at": now},
                {"task_id": "gen-2", "status": "succeeded", "created_at": now},
            ],
            "logs": [{"id": "gl-1", "media_type": "image", "status": "succeeded"}],
        }), encoding="utf-8")
        store = TaskStore(tmp_path / "state.sqlite3")

        mgr = GenerationTaskManager(store=store, legacy_file=legacy)
        # 恢复语义不变：processing → failed（服务重启中断）
        assert mgr.get_task("gen-1")["status"] == "failed"
        assert mgr.get_task("gen-2")["status"] == "succeeded"
        assert mgr.get_gen_logs()[0]["id"] == "gl-1"
        # 落盘只进 sqlite，旧文件停写
        before = legacy.read_text(encoding="utf-8")
        mgr._persist()
        assert legacy.read_text(encoding="utf-8") == before
        payload = store.load("generation_tasks")
        assert any(t["task_id"] == "gen-2" for t in payload["tasks"])


class TestStateManagerSqliteSingleSource:
    def test_save_produces_no_json_artifacts(self, tmp_path, set_global_setting):
        """sqlite 后端全链路：新建/保存项目后 workspace 零 JSON 镜像产出"""
        from src.video_agent.state.manager import StateManager

        set_global_setting("state_backend", "sqlite")
        StateManager.reset_instance()
        svc = StateManager(str(tmp_path))
        pid = svc.active_project_id
        svc.state_dict["project_name"] = "单源验证"
        svc.save()
        # 再建一个项目（走 ProjectManager 全路径）
        svc.create_project("第二项目")
        svc.save()

        assert not (tmp_path / "studio_state.json").exists()
        assert not (tmp_path / "projects" / "index.json").exists()
        assert not any((tmp_path / "projects").glob("*/state.json"))
        # 数据从 sqlite 读回（唯一事实源）
        assert svc._repo.load_project(pid)["project_name"] == "单源验证"

    def test_legacy_studio_state_imported_once(self, tmp_path, set_global_setting):
        """旧 studio_state.json → sqlite 后端首启经 load_compat 一次性迁入"""
        from src.video_agent.state.manager import StateManager

        legacy = {"project_id": "legacy-1", "project_name": "旧项目",
                  "keyElements": [], "shots": [], "audioItems": [],
                  "assets": [], "chatMessages": []}
        (tmp_path / "studio_state.json").write_text(json.dumps(legacy), encoding="utf-8")

        set_global_setting("state_backend", "sqlite")
        StateManager.reset_instance()
        svc = StateManager(str(tmp_path))
        assert svc.active_project_id == "legacy-1"
        assert svc._repo.load_project("legacy-1")["project_name"] == "旧项目"
        # 迁入后 save_compat 为空实现：studio_state.json 内容不被刷新
        svc.save()
        on_disk = json.loads((tmp_path / "studio_state.json").read_text(encoding="utf-8"))
        assert on_disk == legacy
