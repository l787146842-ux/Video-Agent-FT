"""SqliteStateRepository 单元测试：接口与 JSON 仓库对齐 + 自动迁移 + 镜像退役（任务 #24）"""
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
