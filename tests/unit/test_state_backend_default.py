"""P3-16：STATE 后端默认翻转守护——生产默认 sqlite，env 一键回退 json。

翻转守护语义：
- 无 env 覆盖时 Settings().state_backend == "sqlite"（劣化即红：任何人
  把默认翻回 json 而不经 env 声明，本测试直接失败）；
- STATE_BACKEND=json env 覆盖入口在场（一键回退）；
- StateManager._build_repo 路由：sqlite → SqliteStateRepository，
  json / 未知值 → StateRepository（json 回落）。
"""


def test_default_backend_is_sqlite(monkeypatch):
    """无 env 覆盖 → 默认 sqlite（翻转守护锁源）"""
    monkeypatch.delenv("STATE_BACKEND", raising=False)
    from src.video_agent.config import Settings

    assert Settings().state_backend == "sqlite"


def test_env_override_json_rollback(monkeypatch):
    """STATE_BACKEND=json → 一键回退入口在场"""
    monkeypatch.setenv("STATE_BACKEND", "json")
    from src.video_agent.config import Settings

    assert Settings().state_backend == "json"


def test_build_repo_routing(tmp_path, set_global_setting):
    """_build_repo 路由：sqlite 默认 / json 回落 / 未知值回落 json"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.state.repository import StateRepository
    from src.video_agent.state.repository_sqlite import SqliteStateRepository

    set_global_setting("state_backend", "sqlite")
    assert isinstance(StateManager._build_repo(tmp_path / "a"), SqliteStateRepository)

    set_global_setting("state_backend", "json")
    assert isinstance(StateManager._build_repo(tmp_path / "b"), StateRepository)

    set_global_setting("state_backend", "bogus")
    assert isinstance(StateManager._build_repo(tmp_path / "c"), StateRepository)
