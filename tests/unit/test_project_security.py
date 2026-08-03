"""P0-7 回归：project_id 路径遍历防护"""
import pytest

from src.video_agent.exceptions import StateError
from src.video_agent.state.repository import StateRepository


@pytest.fixture
def repo(tmp_path):
    return StateRepository(tmp_path)


@pytest.fixture
def outside_marker(tmp_path):
    """workspace 外的哨兵目录：若路径遍历成功将被删除"""
    marker = tmp_path.parent / f"evil_marker_{tmp_path.name}"
    marker.mkdir(exist_ok=True)
    (marker / "do_not_delete.txt").write_text("x", encoding="utf-8")
    yield marker
    # 清理
    import shutil
    shutil.rmtree(marker, ignore_errors=True)


class TestProjectIdWhitelist:
    """非法 project_id 必须被白名单正则拦截，且不触碰文件系统"""

    @pytest.mark.parametrize("bad_id", [
        "../../etc",
        "../outside",
        "foo/bar",
        "foo\\bar",
        "..",
        "a b",
        "proj*",
        "",
    ])
    def test_delete_rejects_traversal(self, repo, bad_id):
        with pytest.raises(StateError):
            repo.delete_project_dir(bad_id)

    @pytest.mark.parametrize("bad_id", ["../../x", "../x", "a/b", "a\\b"])
    def test_load_rejects_traversal(self, repo, bad_id):
        with pytest.raises(StateError):
            repo.load_project(bad_id)

    @pytest.mark.parametrize("bad_id", ["../../x", "a/b"])
    def test_save_rejects_traversal(self, repo, bad_id):
        with pytest.raises(StateError):
            repo.save_project(bad_id, {})

    def test_traversal_does_not_touch_filesystem(self, repo, outside_marker, tmp_path):
        """即使构造指向 workspace 外的 id，目标目录也必须完好"""
        rel = f"../evil_marker_{tmp_path.name}"
        with pytest.raises(StateError):
            repo.delete_project_dir(rel)
        assert (outside_marker / "do_not_delete.txt").exists()

    def test_valid_project_id_accepted(self, repo):
        """合法 id（gen_id 格式）正常工作"""
        repo.save_project("proj_1736000000", {"ok": True})
        loaded = repo.load_project("proj_1736000000")
        assert loaded == {"ok": True}
        repo.delete_project_dir("proj_1736000000")
        assert repo.load_project("proj_1736000000") is None
