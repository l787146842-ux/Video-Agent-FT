"""P3-16：json↔sqlite 状态仓库等价性与迁移路径（默认翻转的承重守护）。

覆盖三件事：
1. 接口等价：同一操作序列在 StateRepository 与 SqliteStateRepository 上
   产出相同读回结果（参数化双后端同题同断言）；
2. 迁移路径：json 文件 → sqlite 首启自动迁移无损；
3. 双写回退期无损：sqlite 主写 + JSON 侧镜像/兼容文件双写，
   回退 json 后端（含混用工作区）经 StateManager 全周期无损续跑。
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

    def test_compat_roundtrip(self, repo):
        repo.save_compat(_STATE)
        assert repo.load_compat() == _STATE


class TestMigrationAndDualWrite:
    def test_json_to_sqlite_migration_lossless(self, tmp_path):
        """json 侧既有文件 → sqlite 首启自动迁移无损"""
        jrepo = StateRepository(tmp_path)
        jrepo.ensure_dirs()
        jrepo.save_project(_PROJECT_ID, _STATE)
        jrepo.write_index(_INDEX)

        srepo = SqliteStateRepository(tmp_path)
        assert srepo.load_project(_PROJECT_ID) == _STATE
        assert srepo.read_index() == _INDEX

    def test_sqlite_dual_write_readable_by_json_repo(self, tmp_path):
        """sqlite 主写 + 双写 → json 仓库直接读回（镜像与兼容文件两路皆无损）"""
        srepo = SqliteStateRepository(tmp_path)
        srepo.save_project(_PROJECT_ID, _STATE_V2)
        srepo.write_index(_INDEX)
        srepo.save_compat(_STATE_V2)

        jrepo = StateRepository(tmp_path)
        assert jrepo.load_project(_PROJECT_ID) == _STATE_V2
        assert jrepo.read_index() == _INDEX
        assert jrepo.load_compat() == _STATE_V2

    def test_sqlite_delete_mirrors_to_json_side(self, tmp_path):
        """sqlite 删除 → 镜像文件同删（回退 json 后不得见已删项目残留）"""
        srepo = SqliteStateRepository(tmp_path)
        srepo.save_project(_PROJECT_ID, _STATE)
        srepo.delete_project_dir(_PROJECT_ID)
        assert StateRepository(tmp_path).load_project(_PROJECT_ID) is None

    def test_full_cycle_json_sqlite_json_via_state_manager(
        self, tmp_path, set_global_setting,
    ):
        """全周期无损：json 写 → sqlite 迁移主写+双写 → 回退 json 续跑。

        混用工作区（json 阶段已留 state.json/index.json）下回退不得读到
        陈旧文件——sqlite 侧镜像必须把 JSON 侧同步到最新。
        """
        from src.video_agent.state.manager import StateManager

        # 阶段一：json 后端写入（模拟翻转前的存量工作区）
        set_global_setting("state_backend", "json")
        m1 = StateManager(str(tmp_path))
        pid = m1.active_project_id
        m1.state_dict["project_name"] = "周期验证-json 段"
        m1.save()

        # 阶段二：翻转到 sqlite（首启自动迁移）并更新
        set_global_setting("state_backend", "sqlite")
        m2 = StateManager(str(tmp_path))
        assert m2.state_dict.get("project_name") == "周期验证-json 段"
        m2.state_dict["project_name"] = "周期验证-sqlite 段"
        m2.save()

        # 阶段三：一键回退 json —— 必须读到 sqlite 段的最新状态（无损）
        set_global_setting("state_backend", "json")
        m3 = StateManager(str(tmp_path))
        assert m3.active_project_id == pid
        assert m3.state_dict.get("project_name") == "周期验证-sqlite 段"
