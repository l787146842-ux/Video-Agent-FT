"""StudioStateService：临时目录初始化、多项目管理、原子写产物有效"""
import json

import pytest

from src.video_agent.web.state_service import StudioStateService


@pytest.fixture
def svc(tmp_path):
    return StudioStateService(base_dir=tmp_path)


def test_fresh_init_creates_demo_project(svc, tmp_path):
    assert svc.active_project_id
    state_file = tmp_path / "projects" / svc.active_project_id / "state.json"
    assert state_file.exists()
    # 落盘内容必须是合法 JSON
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["project_id"] == svc.active_project_id


def test_create_and_switch_project(svc):
    original = svc.active_project_id
    new_id = svc.create_project("新项目")
    assert svc.active_project_id == new_id
    assert svc.state["project_name"] == "新项目"
    assert svc.state["keyElements"] == []

    assert svc.switch_project(original) is True
    assert svc.active_project_id == original
    # demo 项目应该有内容
    assert svc.state["keyElements"]


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
    svc.state["keyElements"].append({"id": "ke-x", "title": "x", "drafts": []})
    svc.save()
    state_file = tmp_path / "projects" / svc.active_project_id / "state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert any(g["id"] == "ke-x" for g in data["keyElements"])
    # 目录里不应残留写入用的临时文件
    leftovers = [p for p in state_file.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_migration_from_legacy_state_file(tmp_path):
    legacy = {"project_id": "legacy-1", "project_name": "旧项目", "keyElements": [], "shots": [], "audioItems": [], "assets": [], "chatMessages": []}
    (tmp_path / "studio_state.json").write_text(json.dumps(legacy), encoding="utf-8")
    svc = StudioStateService(base_dir=tmp_path)
    assert svc.active_project_id == "legacy-1"
    assert (tmp_path / "projects" / "legacy-1" / "state.json").exists()
