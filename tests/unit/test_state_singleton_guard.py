# -*- coding: utf-8 -*-
"""事故 1111 回归钉：StateManager 默认工作区授权闸（禁止静默写生产库）。

事故现场（2026-10-09，工作台「1111」`proj-1791464775-7e017914`）：
上一会话的验证脚本 `.tmp_probe/verify_card_first.py` 用
`svc = StateManager.get_instance()` 拿到**生产单例**，随后
`svc.state_dict["shots"] = []` + 覆写 `keyElements` 把测试夹具
（`卡A 三视图` / `卡B 四视图` / `Element_场景` / `imgUrl=http://fake/x.png`）
整板写进真实项目 —— 10 个元素组、7 个分镜（84s）被覆盖成 2 组 0 镜。

根因：`get_instance()` 在无任务绑定时**静默**回落 `DEFAULT_WORKSPACE_DIR`。
既有防护 `tests/conftest.py::_state_singleton_isolation` 只覆盖 pytest 进程，
`python .tmp_probe/xxx.py` 直接跑即绕过。

修法（P2 约束下沉，非 prose）：进程身份是客观事实、可机械判定 ⇒
默认工作区改为**显式授权**（`init_default()`，唯一合法调用点 = 服务启动），
未授权且无绑定时 `get_instance()` / `create_task_bound()` **fail-loud 抛错**。

本文件钉死 5 条不变量：
  ① 未授权 + 无绑定 → get_instance() 抛 StateError（不再静默用生产目录）
  ② 未授权时误用**对生产目录零写入**（拿不到实例 = 写不进去，非「写了再报错」）
  ③ init_default() 后返回同一单例，且生产库路径与授权位一致
  ④ reset_instance() 同时清除授权位（防长驻授权使误用重新静默）
  ⑤ create_task_bound 缺省工作区同样受闸（G4 同类路径全覆盖）
"""
import pytest

from src.video_agent.exceptions import StateError
from src.video_agent.state.manager import StateManager


@pytest.fixture(autouse=True)
def _clean_singleton():
    """每条用例前后清干净单例与授权位（本文件专测这两者的状态机）。"""
    StateManager.reset_instance()
    yield
    StateManager.reset_instance()


# ---------- ① 未授权 → fail-loud ----------

def test_1111_get_instance_without_authorization_raises():
    """无绑定、无授权时 get_instance() 必须抛错，不得静默回落生产 workspace。

    旧实现此调用会返回一个指向 `workspace/` 的实例 —— 事故 1111 的入口。
    """
    with pytest.raises(StateError) as ei:
        StateManager.get_instance()
    msg = str(ei.value)
    assert "init_default" in msg, "错误消息须指明合法入口（可发现性）"
    assert "1111" in msg, "错误消息须带事故编号（留痕可追溯）"


# ---------- ② 误用对生产目录零写入 ----------

def test_1111_misuse_writes_nothing_to_default_workspace(tmp_path, monkeypatch):
    """把 DEFAULT_WORKSPACE_DIR 指向哨兵目录：未授权误用后该目录零字节变化。

    钉的是「拿不到实例 ⇒ 根本写不进去」，而非「写进去再报错」——
    后者仍会污染数据，不满足事故诉求。
    """
    sentinel = tmp_path / "prod_workspace_sentinel"
    sentinel.mkdir()
    before = {p.name: p.stat().st_size for p in sentinel.rglob("*")}

    import src.video_agent.state.manager as mgr
    monkeypatch.setattr(mgr, "DEFAULT_WORKSPACE_DIR", sentinel)

    with pytest.raises(StateError):
        StateManager.get_instance()

    after = {p.name: p.stat().st_size for p in sentinel.rglob("*")}
    assert after == before, f"误用不得触碰生产目录，实际变化: {before} -> {after}"
    assert not list(sentinel.glob("state.sqlite3")), "生产库不得被创建"


# ---------- ③ 显式授权后可用 ----------

def test_1111_init_default_authorizes_and_is_idempotent(tmp_path, monkeypatch):
    """init_default() 授权后返回单例；重复调用返回同一实例（服务重启可重入）。"""
    ws = tmp_path / "svc_ws"
    import src.video_agent.state.manager as mgr
    monkeypatch.setattr(mgr, "DEFAULT_WORKSPACE_DIR", ws)

    first = StateManager.init_default()
    assert first is StateManager.get_instance(), "授权后 get_instance 命中该单例"
    assert StateManager.init_default() is first, "重复声明返回同一实例（不重建）"
    assert first._workspace_dir == ws, "实例落在声明的工作区"


# ---------- ④ reset 同时清授权 ----------

def test_1111_reset_instance_clears_authorization(tmp_path, monkeypatch):
    """reset_instance() 必须一并清授权位，防一次授权长驻导致后续误用静默。"""
    ws = tmp_path / "svc_ws2"
    import src.video_agent.state.manager as mgr
    monkeypatch.setattr(mgr, "DEFAULT_WORKSPACE_DIR", ws)

    StateManager.init_default()
    assert StateManager.get_instance() is not None

    StateManager.reset_instance()
    with pytest.raises(StateError):
        StateManager.get_instance(), "reset 后必须重新授权（授权位已清）"


# ---------- ⑤ create_task_bound 同类路径同闸（G4） ----------

def test_1111_create_task_bound_without_workspace_requires_authorization():
    """缺省 workspace_dir 的 create_task_bound 同样受闸（G4：同类路径全覆盖）。

    旧签名默认值 = str(DEFAULT_WORKSPACE_DIR) ⇒ 脚本调本入口也能拿到生产库实例。
    """
    with pytest.raises(StateError) as ei:
        StateManager.create_task_bound("proj-x")
    assert "1111" in str(ei.value)


def test_1111_create_task_bound_explicit_workspace_still_works(tmp_path):
    """显式传目录的既有语义不回归（测试/脚本的唯一合法姿势）。"""
    ws = str(tmp_path / "ws")
    svc = StateManager(ws)
    pid = svc.active_project_id
    bound, token = StateManager.create_task_bound(pid, ws)
    try:
        assert bound is not svc
        assert StateManager.get_instance() is bound, "绑定内 get_instance 命中任务实例"
        assert bound.active_project_id == pid
    finally:
        StateManager.release_task_bound(token)
