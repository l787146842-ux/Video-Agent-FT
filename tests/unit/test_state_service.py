"""StateManager：临时目录初始化、多项目管理、原子写产物有效"""
import json

import pytest

from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


def test_fresh_init_creates_demo_project(svc, tmp_path):
    assert svc.active_project_id
    # 任务 #18 / P10：落盘校验改经 repo 接口读回（后端无关：
    # json 读 state.json / sqlite 读唯一事实源）；内容必须是合法 JSON 反序列化结果
    data = svc._repo.load_project(svc.active_project_id)
    assert data is not None
    assert data["project_id"] == svc.active_project_id


def test_create_and_switch_project(svc):
    original = svc.active_project_id
    new_id = svc.create_project("新项目")
    assert svc.active_project_id == new_id
    assert svc.state_dict["project_name"] == "新项目"
    # 产品意图：新建项目不预建任何占位分组与欢迎消息，
    # 全部由 Agent 按任务拆解结果创建，避免执行任务前先删一遍空组
    assert svc.state_dict["keyElements"] == []
    assert svc.state_dict["shots"] == []
    assert svc.state_dict["audioItems"] == []
    assert svc.state_dict["chatMessages"] == []

    assert svc.switch_project(original) is True
    assert svc.active_project_id == original
    # demo 项目应该有内容
    assert svc.state_dict["keyElements"]


def test_switch_to_missing_project_fails(svc):
    assert svc.switch_project("no-such-project") is False


def test_delete_project(svc, tmp_path):
    first = svc.active_project_id
    second = svc.create_project("第二个")
    assert svc.delete_project(second) is True
    assert svc.active_project_id == first
    assert not (tmp_path / "projects" / second).exists()


def test_cannot_delete_last_project(svc):
    assert svc.delete_project(svc.active_project_id) is False


def test_save_is_valid_json_after_mutation(svc, tmp_path):
    svc.state_dict["keyElements"].append({"id": "ke-x", "title": "x", "drafts": []})
    svc.save()
    # 任务 #18 / P10：落盘校验改经 repo 接口读回（后端无关）
    data = svc._repo.load_project(svc.active_project_id)
    assert any(g["id"] == "ke-x" for g in data["keyElements"])
    # 工作区里不应残留写入用的临时文件（两后端都适用）
    leftovers = list((tmp_path / "projects").rglob("*.tmp"))
    assert leftovers == []


def test_migration_from_legacy_state_file(tmp_path):
    legacy = {"project_id": "legacy-1", "project_name": "旧项目", "keyElements": [], "shots": [], "audioItems": [], "assets": [], "chatMessages": []}
    (tmp_path / "studio_state.json").write_text(json.dumps(legacy), encoding="utf-8")
    svc = StateManager(str(tmp_path))
    assert svc.active_project_id == "legacy-1"
    # 任务 #18 / P10：迁移结果经 repo 接口校验（后端无关：json 落项目目录 /
    # sqlite 落唯一事实源，镜像退役后 sqlite 不再产出 state.json）
    assert svc._repo.load_project("legacy-1") is not None
