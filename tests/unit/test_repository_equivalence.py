"""P3-16：json↔sqlite 状态仓库等价性与迁移路径（默认翻转的承重守护）。

覆盖三件事：
1. 接口等价：同一操作序列在 StateRepository 与 SqliteStateRepository 上
   产出相同读回结果（参数化双后端同题同断言；save_compat 语义已分裂：
   json 后端为自身兼容文件写入，sqlite 后端镜像退役为空实现，故不参数化）；
2. 迁移路径：json 文件 → sqlite 首启自动迁移无损；
3. 镜像退役（任务 #24）：sqlite 主写不再产出 JSON 镜像，
   回退 json 后端不再无损（新契约守护）。
"""
import pytest

from src.video_agent.exceptions import StateError
from src.video_agent.state.repository import StateRepository
from src.video_agent.state.repository_sqlite import SqliteStateRepository

_PROJECT_ID = "proj-eq1"
_STATE = {
    "project_id": _PROJECT_ID,
    "project_name": "等价性测试",
    "analysis": {"summary": "一句话总结", "key_points": ["要点A", "要点B"]},
    "keyElements": [
        {"id": "g1", "title": "角色", "drafts": [{"id": "d1", "prompt": "测试提示词"}]},
    ],
    "nested": {"deep": [1, 2, {"x": "中文与符号 αβγ ——"}]},
}
_STATE_V2 = {**_STATE, "project_name": "等价性测试-更新"}
_INDEX = {
    "active_project_id": _PROJECT_ID,
    "projects": [{"id": _PROJECT_ID, "name": "等价性测试", "board_version": 3}],
}


@pytest.fixture(params=["json", "sqlite"])
def repo(request, tmp_path):
    """双后端同题：接口等价断言对两后端各跑一遍"""
    r = StateRepository(tmp_path) if request.param == "json" else SqliteStateRepository(tmp_path)
    r.ensure_dirs()
    return r


class TestInterfaceEquivalence:
    def test_project_roundtrip(self, repo):
        repo.save_project(_PROJECT_ID, _STATE)
        assert repo.load_project(_PROJECT_ID) == _STATE

    def test_overwrite_last_write_wins(self, repo):
        repo.save_project(_PROJECT_ID, _STATE)
        repo.save_project(_PROJECT_ID, _STATE_V2)
        assert repo.load_project(_PROJECT_ID) == _STATE_V2

    def test_load_missing_returns_none(self, repo):
        assert repo.load_project("no-such") is None

    def test_index_roundtrip(self, repo):
        repo.write_index(_INDEX)
        assert repo.read_index() == _INDEX

    def test_empty_index_default(self, repo):
        assert repo.read_index() == {"active_project_id": "", "projects": []}

    def test_delete_then_load_none(self, repo):
        repo.save_project(_PROJECT_ID, _STATE)
        repo.delete_project_dir(_PROJECT_ID)
        assert repo.load_project(_PROJECT_ID) is None

    def test_path_traversal_rejected(self, repo):
        with pytest.raises(StateError):
            repo.save_project("../escape", {"x": 1})
        with pytest.raises(StateError):
            repo.load_project("../escape")


class TestCompatDivergence:
    """save_compat 语义分裂守护：json 后端自身兼容文件照写，
    sqlite 后端镜像退役为空实现（任务 #24）。"""

    def test_json_repo_compat_roundtrip(self, tmp_path):
        jrepo = StateRepository(tmp_path)
        jrepo.save_compat(_STATE)
        assert jrepo.load_compat() == _STATE

    def test_sqlite_repo_compat_save_is_noop(self, tmp_path):
        srepo = SqliteStateRepository(tmp_path)
        srepo.save_compat(_STATE)
        assert srepo.load_compat() is None
        assert not (tmp_path / "studio_state.json").exists()


class TestMigrationAndMirrorRetirement:
    def test_json_to_sqlite_migration_lossless(self, tmp_path):
        """json 侧既有文件 → sqlite 首启自动迁移无损（一次性导入兜底保留）"""
        jrepo = StateRepository(tmp_path)
        jrepo.ensure_dirs()
        jrepo.save_project(_PROJECT_ID, _STATE)
        jrepo.write_index(_INDEX)

        srepo = SqliteStateRepository(tmp_path)
        assert srepo.load_project(_PROJECT_ID) == _STATE
        assert srepo.read_index() == _INDEX

    def test_sqlite_write_produces_no_mirror(self, tmp_path):
        """镜像退役：sqlite 写入后 JSON 侧零产出（含兼容文件）"""
        srepo = SqliteStateRepository(tmp_path)
        srepo.save_project(_PROJECT_ID, _STATE_V2)
        srepo.write_index(_INDEX)
        srepo.save_compat(_STATE_V2)
        assert not (tmp_path / "projects" / _PROJECT_ID / "state.json").exists()
        assert not (tmp_path / "projects" / "index.json").exists()
        assert not (tmp_path / "studio_state.json").exists()

    def test_json_then_sqlite_via_state_manager(
        self, tmp_path, set_global_setting,
    ):
        """json 存量工作区 → 翻转 sqlite 首启自动导入无损（新契约：
        导入后 SQLite 为唯一事实源，不再镜像回写 JSON 侧）。

        旧版「阶段三回退 json 无损续跑」断言随镜像退役移除（任务 #24）。
        """
        from src.video_agent.state.manager import StateManager

        # 阶段一：json 后端写入（模拟翻转前的存量工作区）
        set_global_setting("state_backend", "json")
        m1 = StateManager(str(tmp_path))
        pid = m1.active_project_id
        m1.state_dict["project_name"] = "周期验证-json 段"
        m1.save()

        # 阶段二：翻转到 sqlite（首启自动导入）——数据无损读回
        set_global_setting("state_backend", "sqlite")
        m2 = StateManager(str(tmp_path))
        assert m2.active_project_id == pid
        assert m2.state_dict.get("project_name") == "周期验证-json 段"
        m2.state_dict["project_name"] = "周期验证-sqlite 段"
        m2.save()

        # sqlite 段写入不再更新 JSON 镜像（镜像文件停留在导入前的旧值）
        import json as _json
        mirror = tmp_path / "projects" / pid / "state.json"
        if mirror.exists():
            assert _json.loads(mirror.read_text(encoding="utf-8")).get(
                "project_name") == "周期验证-json 段"
        # 重启 sqlite 实例读到最新值（唯一事实源）
        m3 = StateManager(str(tmp_path))
        assert m3.state_dict.get("project_name") == "周期验证-sqlite 段"
