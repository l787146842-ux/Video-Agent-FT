# -*- coding: utf-8 -*-
"""8888 二轮回归：切换项目旧状态覆盖 + 流程体验带修复。

8888 项目现场：任务级隔离后全局单例在任务期间不刷新，switch_project 的
「保存当前」用单例过期空壳回写文件，抹掉后台任务写好的数据（12:19:21 实证）。
"""
from src.video_agent.state.manager import StateManager


def _fresh(ws: str, project_id: str) -> StateManager:
    """全新实例加载指定项目（模拟重连/核对落盘内容）。"""
    svc = StateManager(ws)
    if svc.active_project_id != project_id:
        svc.switch_project(project_id)
    return svc


# ---------- A3：切换/保存不得回退后台任务的新写入 ----------

def test_8888_switch_does_not_regress_task_writes(tmp_path):
    """钉死 8888 现场：任务实例写新后，单例来回切换不得抹掉文件；
    单例持过期内存直接 save() 也必须被版本闸放弃。"""
    ws = str(tmp_path / "ws")
    singleton = StateManager(ws)
    p8888 = singleton.create_project("8888")
    p1111 = singleton.create_project("1111")  # 单例停在 1111（空壳），与现场一致

    # 后台任务实例（contextvar 隔离的同构模拟）：写关键元素并落盘
    task = StateManager(ws)
    task.switch_project(p8888)
    task.state_dict["keyElements"] = [{"id": "ke-1", "title": "程心", "drafts": []}]
    task.save()

    # 用户来回切换：不得再出现「空壳回写抹数据」
    singleton.switch_project(p8888)
    assert singleton.state_dict["keyElements"], "切换应加载任务写好的完整数据"
    singleton.switch_project(p1111)
    singleton.switch_project(p8888)
    assert singleton.state_dict["keyElements"]

    # 任务又写新（分镜），单例内存过期（无分镜）直接 save() → 版本闸放弃
    task.state_dict["shots"] = [{"id": "s-1", "title": "镜头1", "drafts": []}]
    task.save()
    singleton.state_dict["shots"] = []  # 模拟单例的过期视图
    singleton.save()  # 必须被放弃，不得回退文件

    fresh = _fresh(ws, p8888)
    assert fresh.state_dict["keyElements"]
    assert fresh.state_dict["shots"], "过期实例的保存必须被版本闸放弃"


def test_8888_parallel_projects_no_cross_write(tmp_path):
    """双项目并行：各自实例各自落盘，互不串写。"""
    ws = str(tmp_path / "ws")
    a = StateManager(ws)
    pa = a.create_project("A")
    b = StateManager(ws)
    pb = b.create_project("B")
    if a.active_project_id != pa:
        a.switch_project(pa)

    a.state_dict["keyElements"] = [{"id": "ke-a", "title": "元素A", "drafts": []}]
    a.save()
    b.state_dict["keyElements"] = [{"id": "ke-b", "title": "元素B", "drafts": []}]
    b.save()

    fa = _fresh(ws, pa)
    fb = _fresh(ws, pb)
    assert [g["title"] for g in fa.state_dict["keyElements"]] == ["元素A"]
    assert [g["title"] for g in fb.state_dict["keyElements"]] == ["元素B"]


def test_8888_normal_single_instance_save_still_works(tmp_path):
    """版本闸不得误伤正常单实例读写链：连续 update/save 均落盘。"""
    ws = str(tmp_path / "ws")
    svc = StateManager(ws)
    pid = svc.create_project("常规")
    svc.state_dict["keyElements"] = [{"id": "ke-1", "title": "程心", "drafts": []}]
    svc.save()
    svc.state_dict["keyElements"][0]["title"] = "AA"
    svc.save()
    fresh = _fresh(ws, pid)
    assert fresh.state_dict["keyElements"][0]["title"] == "AA"
