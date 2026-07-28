"""集成测试：故事板分组/草稿 CRUD 完整流程"""
import pytest
from fastapi.testclient import TestClient

from src.video_agent.web.app import app
from src.video_agent.state.manager import StateManager


@pytest.fixture(autouse=True)
def reset_state(tmp_path):
    """每个测试使用独立的临时工作区"""
    StateManager.reset_instance()
    svc = StateManager(str(tmp_path))
    StateManager._instance = svc
    yield svc
    StateManager.reset_instance()


@pytest.fixture
def client():
    return TestClient(app)


class TestStoryboardGroupsRead:
    """分组读取"""

    def test_get_groups_returns_three_categories(self, client, reset_state):
        resp = client.get("/api/storyboard/groups")
        assert resp.status_code == 200
        data = resp.json()
        assert "keyElements" in data
        assert "shots" in data
        assert "audioItems" in data

    def test_demo_project_has_initial_groups(self, client, reset_state):
        """demo 项目应有初始分组"""
        resp = client.get("/api/storyboard/groups")
        data = resp.json()
        # demo 数据有 keyElements 和 shots
        assert len(data["keyElements"]) >= 1
        assert len(data["shots"]) >= 1


class TestStoryboardDraftCRUD:
    """草稿增删改"""

    def test_add_draft_to_group(self, client, reset_state):
        """给已有分组添加草稿"""
        groups = client.get("/api/storyboard/groups").json()
        group_id = groups["keyElements"][0]["id"]

        resp = client.post(f"/api/storyboard/groups/{group_id}/drafts", json={
            "label": "测试草稿",
            "prompt": "测试提示词",
            "mediaType": "image",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "draft_id" in data

        # 验证确实添加了
        groups_after = client.get("/api/storyboard/groups").json()
        drafts = groups_after["keyElements"][0]["drafts"]
        assert any(d["label"] == "测试草稿" for d in drafts)

    def test_add_draft_to_nonexistent_group_404(self, client):
        resp = client.post("/api/storyboard/groups/nonexistent/drafts", json={
            "label": "x",
            "prompt": "y",
        })
        assert resp.status_code == 404

    def test_update_draft_fields(self, client, reset_state):
        """更新草稿字段"""
        groups = client.get("/api/storyboard/groups").json()
        draft = groups["keyElements"][0]["drafts"][0]
        draft_id = draft["id"]

        resp = client.patch(f"/api/storyboard/drafts/{draft_id}", json={
            "prompt": "更新后的提示词",
            "tag": "已优化",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 验证更新生效
        groups_after = client.get("/api/storyboard/groups").json()
        updated = next(
            d for g in groups_after["keyElements"]
            for d in g["drafts"] if d["id"] == draft_id
        )
        assert updated["prompt"] == "更新后的提示词"
        assert updated["tag"] == "已优化"

    def test_update_draft_not_found_404(self, client):
        resp = client.patch("/api/storyboard/drafts/nonexistent", json={"prompt": "x"})
        assert resp.status_code == 404

    def test_update_draft_alias_path(self, client, reset_state):
        """设计方案 §4.2 路径别名 /api/state/draft/{id}"""
        groups = client.get("/api/storyboard/groups").json()
        draft_id = groups["keyElements"][0]["drafts"][0]["id"]

        resp = client.patch(f"/api/state/draft/{draft_id}", json={"tag": "别名路径"})
        assert resp.status_code == 200


class TestStoryboardGroupPatch:
    """分组字段编辑"""

    def test_update_group_title(self, client, reset_state):
        groups = client.get("/api/storyboard/groups").json()
        group_id = groups["shots"][0]["id"]

        resp = client.patch(f"/api/storyboard/groups/{group_id}", json={
            "title": "修改后的镜头标题",
        })
        assert resp.status_code == 200

        groups_after = client.get("/api/storyboard/groups").json()
        updated = next(g for g in groups_after["shots"] if g["id"] == group_id)
        assert updated["title"] == "修改后的镜头标题"

    def test_update_group_not_found_404(self, client):
        resp = client.patch("/api/storyboard/groups/nonexistent", json={"title": "x"})
        assert resp.status_code == 404

    def test_update_group_alias_path(self, client, reset_state):
        """设计方案 §4.2 路径别名 /api/state/group/{id}"""
        groups = client.get("/api/storyboard/groups").json()
        group_id = groups["keyElements"][0]["id"]

        resp = client.patch(f"/api/state/group/{group_id}", json={"desc": "别名描述"})
        assert resp.status_code == 200


class TestStoryboardPersistence:
    """持久化验证"""

    def test_changes_surive_reload(self, tmp_path, client, reset_state):
        """修改后重新加载状态应保留"""
        groups = client.get("/api/storyboard/groups").json()
        group_id = groups["keyElements"][0]["id"]

        # 添加草稿
        client.post(f"/api/storyboard/groups/{group_id}/drafts", json={
            "label": "持久化测试",
            "prompt": "persist",
        })

        # 模拟重启：重置单例并从磁盘重新加载
        StateManager.reset_instance()
        svc2 = StateManager(str(tmp_path))
        StateManager._instance = svc2

        groups_after = client.get("/api/storyboard/groups").json()
        all_drafts = [d for g in groups_after["keyElements"] for d in g.get("drafts", [])]
        assert any(d["label"] == "持久化测试" for d in all_drafts)
