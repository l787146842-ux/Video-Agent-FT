"""SqliteStateRepository 单元测试：接口与 JSON 仓库对齐 + 自动迁移 + 镜像退役（任务 #24）
+ JSON 回落冷备语义钉死（任务 #10：非热双写，损坏隔离后冷恢复一次）"""
import json

import pytest

from src.video_agent.exceptions import StateError
from src.video_agent.state.repository_sqlite import SqliteStateRepository


@pytest.fixture
def repo(tmp_path):
    return SqliteStateRepository(tmp_path)


class TestSqliteRepository:
    def test_save_and_load_roundtrip(self, repo):
        state = {"project_id": "proj-1", "project_name": "测试", "keyElements": [{"id": "g1"}]}
        repo.save_project("proj-1", state)
        loaded = repo.load_project("proj-1")
        assert loaded == state

    def test_load_missing_returns_none(self, repo):
        assert repo.load_project("no-such") is None

    def test_index_roundtrip(self, repo):
        idx = {"active_project_id": "proj-1", "projects": [{"id": "proj-1", "name": "测试"}]}
        repo.write_index(idx)
        assert repo.read_index() == idx

    def test_empty_index_default(self, repo):
        assert repo.read_index() == {"active_project_id": "", "projects": []}

    def test_delete_project(self, repo):
        repo.save_project("proj-1", {"project_id": "proj-1"})
        repo.delete_project_dir("proj-1")
        assert repo.load_project("proj-1") is None

    def test_invalid_project_id_rejected(self, repo):
        with pytest.raises(StateError):
            repo.save_project("../escape", {"x": 1})
        with pytest.raises(StateError):
            repo.load_project("a/b")

    def test_compat_save_retired_no_file_written(self, repo, tmp_path):
        """镜像退役（任务 #24）：save_compat 停写 studio_state.json，
        load_compat 仍可读取旧文件（一次性迁入入口）"""
        state = {"project_id": "proj-1"}
        repo.save_compat(state)
        assert not (tmp_path / "studio_state.json").exists()
        # 旧文件在场时只读入口仍生效（启动迁移路径）
        (tmp_path / "studio_state.json").write_text(json.dumps(state), encoding="utf-8")
        assert repo.load_compat() == state

    def test_no_json_mirror_written(self, repo, tmp_path):
        """镜像退役（任务 #24）：save_project/write_index 只写 SQLite，
        不再产出 projects/<id>/state.json 与 projects/index.json"""
        repo.save_project("proj-1", {"project_id": "proj-1"})
        repo.write_index({"active_project_id": "proj-1", "projects": [{"id": "proj-1"}]})
        assert not (tmp_path / "projects" / "proj-1" / "state.json").exists()
        assert not (tmp_path / "projects" / "index.json").exists()
        # 数据仍从 SQLite 读回（唯一事实源）
        assert repo.load_project("proj-1") == {"project_id": "proj-1"}

    def test_delete_cleans_legacy_mirror_dir(self, repo, tmp_path):
        """删除项目时顺带清理镜像回退期遗留的旧项目目录"""
        legacy_dir = tmp_path / "projects" / "proj-old"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "state.json").write_text("{}", encoding="utf-8")
        repo.save_project("proj-old", {"project_id": "proj-old"})
        repo.delete_project_dir("proj-old")
        assert not legacy_dir.exists()


class TestAutoMigration:
    def test_migrates_from_json_on_first_use(self, tmp_path):
        # 预置 JSON 项目结构
        projects = tmp_path / "projects"
        pdir = projects / "proj-a"
        pdir.mkdir(parents=True)
        state = {"project_id": "proj-a", "project_name": "迁移测试"}
        (pdir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        index = {"active_project_id": "proj-a", "projects": [{"id": "proj-a", "name": "迁移测试"}]}
        (projects / "index.json").write_text(json.dumps(index), encoding="utf-8")

        repo = SqliteStateRepository(tmp_path)
        assert repo.load_project("proj-a") == state
        assert repo.read_index() == index

    def test_no_overwrite_when_db_has_data(self, tmp_path):
        # 先建库写入数据
        repo1 = SqliteStateRepository(tmp_path)
        repo1.save_project("proj-new", {"project_id": "proj-new"})
        # 再放一个 JSON 项目（不应被迁移覆盖）
        pdir = tmp_path / "projects" / "proj-old"
        pdir.mkdir(parents=True)
        (pdir / "state.json").write_text(json.dumps({"project_id": "proj-old"}), encoding="utf-8")
        (tmp_path / "projects" / "index.json").write_text(
            json.dumps({"active_project_id": "proj-old", "projects": [{"id": "proj-old"}]}),
            encoding="utf-8",
        )
        repo2 = SqliteStateRepository(tmp_path)
        assert repo2.load_project("proj-new") is not None
        assert repo2.load_project("proj-old") is None  # 未迁移（DB 非空）


class TestColdBackupRecovery:
    """冷备语义钉死（任务 #10）：SQLite 为主、JSON 为冷备，
    非持续热双写；损坏/缺失时经同一条冷恢复路径尽力恢复一次。"""

    def test_corrupt_db_quarantined_and_rebuilt(self, tmp_path):
        """SQLite 损坏 → 隔离（改名保留现场，不删除）+ 重建可用空库，不崩溃"""
        (tmp_path / "state.sqlite3").write_bytes(
            b"this is definitely not a sqlite database")
        repo = SqliteStateRepository(tmp_path)
        # 重建后的空库可用（读写正常）
        repo.save_project("proj-1", {"project_id": "proj-1"})
        assert repo.load_project("proj-1") == {"project_id": "proj-1"}
        # 损坏文件被隔离为带时间戳的改名副本（现场保留）
        quarantined = list(tmp_path.glob("state.sqlite3.corrupt-*"))
        assert quarantined, "损坏文件应被改名隔离而非删除"
        # 新库文件已重建
        assert (tmp_path / "state.sqlite3").exists()

    def test_corrupt_db_cold_restores_from_json(self, tmp_path):
        """损坏隔离后 DB 为空 → 触发 JSON 冷备一次性恢复（best-effort）"""
        projects = tmp_path / "projects"
        pdir = projects / "proj-cold"
        pdir.mkdir(parents=True)
        state = {"project_id": "proj-cold", "project_name": "冷备项目"}
        (pdir / "state.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
        index = {"active_project_id": "proj-cold",
                 "projects": [{"id": "proj-cold", "name": "冷备项目"}]}
        (projects / "index.json").write_text(
            json.dumps(index, ensure_ascii=False), encoding="utf-8")
        # 损坏的 DB 在场（模拟运行中损坏后重启）
        (tmp_path / "state.sqlite3").write_bytes(b"\x00garbage\x01")
        repo = SqliteStateRepository(tmp_path)
        # 冷备恢复生效：JSON 工作区的项目被一次性导回
        assert repo.load_project("proj-cold") == state
        assert repo.read_index() == index

    def test_no_hot_dual_write_during_normal_lifecycle(self, tmp_path):
        """正常生命周期非热双写：多次写入后仍无任何 JSON 镜像产出，
        JSON 既不写也不读（冷备身份）"""
        repo = SqliteStateRepository(tmp_path)
        for i in range(3):
            repo.save_project("proj-hot", {"project_id": "proj-hot", "v": i})
            repo.write_index({"active_project_id": "proj-hot",
                              "projects": [{"id": "proj-hot"}]})
            repo.save_compat({"project_id": "proj-hot", "v": i})
        assert not (tmp_path / "projects" / "proj-hot" / "state.json").exists()
        assert not (tmp_path / "projects" / "index.json").exists()
        assert not (tmp_path / "studio_state.json").exists()
        # 数据唯一来源仍是 SQLite
        assert repo.load_project("proj-hot")["v"] == 2
