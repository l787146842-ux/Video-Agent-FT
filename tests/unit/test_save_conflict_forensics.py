# -*- coding: utf-8 -*-
"""8888 委派失踪批 · 批 B：落盘冲突可取证（状态层，P1）。

事故里两次版号递增（34→35→36）在 INFO 级日志零痕迹——save() 成功路径原本
只有 DEBUG、冲突分支不报写入方身份，事后无法指名对手方实例。

钉死契约：
1. 全局单例默认标签 "global"；create_task_bound 后为 "task:<project_id>"；
2. save() 成功路径升为 INFO，内容含项目 id / 版号 / 实例标签；
3. save() 版本闸拒绝的 WARNING 追加「本实例=<tag>」。
不改返回值契约、不新增门禁。
"""
import pytest
from loguru import logger

from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    instance.save()
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def log_sink():
    """收集 loguru INFO 及以上消息文本。"""
    lines = []

    def _sink(message):
        lines.append(message.record["message"])

    hid = logger.add(_sink, level="INFO")
    yield lines
    logger.remove(hid)


# ---------- ① 实例标签 ----------

def test_global_instance_tag_default(svc):
    assert svc._instance_tag == "global"


def test_task_bound_instance_tag(tmp_path):
    ws = str(tmp_path / "ws")
    StateManager.reset_instance()
    global_svc = StateManager(ws)
    pid = global_svc.active_project_id
    assert global_svc._instance_tag == "global"

    bound, token = StateManager.create_task_bound(pid, ws)
    try:
        assert bound._instance_tag == f"task:{pid}"
    finally:
        StateManager.release_task_bound(token)
    StateManager.reset_instance()


# ---------- ② 成功落盘 INFO 日志带项目/版号/标签 ----------

def test_save_success_logs_info_with_tag(svc, log_sink):
    svc._instance_tag = "task:proj-x"
    pid = svc.active_project_id
    assert svc.save() is True

    hits = [m for m in log_sink if "落盘" in m and pid in m]
    assert hits, "成功落盘须有 INFO 取证日志"
    assert "本实例=task:proj-x" in hits[-1]
    assert "账本" in hits[-1]


# ---------- ③ 版本闸拒绝 WARNING 带本实例标签 ----------

def test_save_reject_logs_warning_with_tag(svc, log_sink):
    # 对手方实例推高磁盘账本，令 svc 的 _known_version 过期
    rival = StateManager(str(svc._workspace_dir))
    if rival.active_project_id != svc.active_project_id:
        rival.switch_project(svc.active_project_id)
    rival.save()

    svc._instance_tag = "task:stale-one"
    assert svc.save() is False  # 撞版本闸

    hits = [m for m in log_sink if "放弃过期写入" in m]
    assert hits, "拒绝写入须有 WARNING 日志"
    assert "本实例=task:stale-one" in hits[-1]
