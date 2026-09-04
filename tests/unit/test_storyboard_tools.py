"""
Storyboard Tools 单元测试 — 闭集枚举进 Schema（批 2 T3）。

聚焦 CreateGroupInput.group_type 闭集拒收轴：闭集外值经
ToolManager.invoke_tool 返回 success=False 且 error_code=="validation"
（校验轴由批 3 在 tools/manager.py 铺好，此处为生产端落点）。
"""
import pytest
from pydantic import ValidationError

from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.storyboard_tools import (
    CreateGroupInput,
    MediaToChatInput,
    StoryboardMediaToChatTool,
    register_storyboard_tools,
)


@pytest.fixture(autouse=True)
def _reset_tools():
    ToolManager.reset()
    register_storyboard_tools()
    yield
    ToolManager.reset()


class TestCreateGroupTypeEnumClosedSet:
    """group_type 闭集枚举：keyElement | shot | audio，集外值拒收"""

    async def test_invalid_group_type_rejected_via_invoke(self):
        result = await ToolManager.invoke_tool(
            "storyboard_create_group", {"group_type": "bogus", "title": "测试分组"}
        )
        assert result.success is False
        assert result.error_code == "validation"
        assert result.retryable is False

    def test_invalid_group_type_schema_rejected(self):
        with pytest.raises(ValidationError):
            CreateGroupInput.model_validate({"group_type": "scene", "title": "x"})

    def test_valid_group_types_accepted(self):
        for gt in ("keyElement", "shot", "audio"):
            params = CreateGroupInput.model_validate({"group_type": gt, "title": "x"})
            assert params.group_type == gt


class TestDraftDescFieldBatch1:
    """批 1 · A2「卡片装得下描述」：desc 落盘 + 白名单外字段原子拒收。

    3333 事故：模型给 add_draft/create_group 附带 content/desc/tags，
    build_draft_dict 白名单外静默丢弃 → 空壳卡假成功。现口径：
    desc 落盘；白名单外（content/tags 等）原子拒收（不写任何字段）。
    """

    @pytest.fixture
    def svc(self, tmp_path):
        StateManager.reset_instance()
        instance = StateManager(str(tmp_path))
        StateManager._instance = instance
        yield instance
        StateManager.reset_instance()

    async def _new_group(self, group_type="keyElement", title="t") -> str:
        result = await ToolManager.invoke_tool(
            "storyboard_create_group", {"group_type": group_type, "title": title})
        assert result.success is True, result.error
        return result.data["group_id"]

    async def test_desc_lands_on_added_draft(self, svc):
        gid = await self._new_group()
        result = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid, "group_type": "keyElement",
            "draft": {"label": "角色·程心", "desc": "年龄 28；外貌：黑色短发；服装：作训服"},
        })
        assert result.success is True, result.error
        group = next(g for g in svc.state_dict["keyElements"] if g["id"] == gid)
        assert group["drafts"][0]["desc"].startswith("年龄 28")

    async def test_desc_lands_on_group_attached_draft(self, svc):
        result = await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "keyElement", "title": "场景",
            "draft": {"label": "太空电梯", "desc": "空间：碳纳米管井道；光源：顶光；氛围：冷峻"},
        })
        assert result.success is True, result.error
        group = next(g for g in svc.state_dict["keyElements"]
                     if g["id"] == result.data["group_id"])
        assert group["drafts"][0]["desc"].startswith("空间：碳纳米管井道")

    async def test_unknown_draft_field_rejected_atomically_on_add(self, svc):
        """content/tags 白名单外 → 明确报错，状态零污染（目标组零新增草稿）。"""
        gid = await self._new_group()
        result = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid, "group_type": "keyElement",
            "draft": {"label": "x", "desc": "d", "content": "正文", "tags": ["a"]},
        })
        assert result.success is False
        assert result.error_code == "validation"
        assert "content" in result.error and "tags" in result.error
        assert "desc" in result.error, "报错须指路 desc 字段"
        group = next(g for g in svc.state_dict["keyElements"] if g["id"] == gid)
        assert group["drafts"] == [], "失败路径不得半写入"

    async def test_unknown_attached_field_rejected_atomically_on_create_group(self, svc):
        before = len(svc.state_dict.get("shots") or [])
        result = await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "shot", "title": "分镜",
            "draft": {"label": "x", "content": "正文"},
        })
        assert result.success is False
        assert result.error_code == "validation"
        assert "content" in result.error
        assert len(svc.state_dict.get("shots") or []) == before, "失败路径不得建组"

    async def test_explicit_id_allowed_on_add(self, svc):
        """新建通道允许显式 id（patch 通道改 id 仍拒收）。"""
        gid = await self._new_group()
        result = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid, "group_type": "keyElement",
            "draft": {"id": "ke-custom-1", "label": "x"},
        })
        assert result.success is True, result.error
        group = next(g for g in svc.state_dict["keyElements"] if g["id"] == gid)
        assert any(d["id"] == "ke-custom-1" for d in group["drafts"])


class TestFailureShoutAndAtomicityBatch3:
    """批 3 · B5/B6：失败会喊（三要素）+ 失败原子性（哈希比对零污染）。

    标尺 = flova 转录：「镜头 ID 重复」失败两次，每次都明示
    「现有故事板没有被改动」；报错须含 ①原因 ②已保留什么 ③缺什么才能继续。
    """

    @pytest.fixture
    def svc(self, tmp_path):
        StateManager.reset_instance()
        instance = StateManager(str(tmp_path))
        StateManager._instance = instance
        yield instance
        StateManager.reset_instance()

    @staticmethod
    def _board_hash(svc) -> str:
        import hashlib
        import json as _json
        return hashlib.sha256(_json.dumps(
            {k: svc.state_dict.get(k) for k in
             ("keyElements", "shots", "audioItems")},
            ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    async def _new_group(self, svc, group_type="keyElement", title="t") -> str:
        result = await ToolManager.invoke_tool(
            "storyboard_create_group", {"group_type": group_type, "title": title})
        assert result.success is True, result.error
        return result.data["group_id"]

    async def test_unknown_field_failure_norm_and_state_hash_unchanged(self, svc):
        """白名单外参数失败：报错含保留声明与补救指引，故事板哈希前后一致。"""
        gid = await self._new_group(svc)
        before = self._board_hash(svc)
        result = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid, "group_type": "keyElement",
            "draft": {"label": "x", "content": "正文", "tags": ["a"]},
        })
        assert result.success is False
        assert "content" in result.error and "tags" in result.error
        assert "保持原样" in result.error, "② 已保留什么状态"
        assert "重新提交" in result.error and "desc" in result.error, "③ 缺什么才能继续"
        assert self._board_hash(svc) == before, "失败零污染（哈希比对）"

    async def test_duplicate_explicit_id_rejected_atomically(self, svc):
        """重复 ID（flova 标尺）：写入前拦截、报错含保留声明、状态零污染。"""
        gid = await self._new_group(svc)
        first = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid, "group_type": "keyElement",
            "draft": {"id": "dup-1", "label": "第一张"},
        })
        assert first.success is True, first.error
        before = self._board_hash(svc)
        dup = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid, "group_type": "keyElement",
            "draft": {"id": "dup-1", "label": "重复卡"},
        })
        assert dup.success is False
        assert dup.error_code == "validation"
        assert "dup-1" in dup.error and "ID 重复" in dup.error
        assert "保持原样" in dup.error and ("省略 id" in dup.error or "patch_draft" in dup.error)
        assert self._board_hash(svc) == before, "重复 ID 失败零污染（哈希比对）"
        gid2 = await self._new_group(svc, title="t2")
        cross = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid2, "group_type": "keyElement",
            "draft": {"id": "dup-1", "label": "跨组重复"},
        })
        assert cross.success is False, "跨组同 id 同样拒收"

    async def test_group_not_found_failure_norm(self, svc):
        result = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": "ghost", "group_type": "keyElement",
            "draft": {"label": "x"},
        })
        assert result.success is False
        assert "未做任何改动" in result.error and "read_state_group" in result.error

    async def test_failure_feedback_declares_state_preserved(self):
        """B5 ② 全局状态保留声明进入失败回喂（模型不得假设失败污染状态）。"""
        from src.video_agent.core.fc_feedback import compose_failure_feedback

        out = compose_failure_feedback(
            "image_generate", "上游超时", fail_count=1, error_code="timeout")
        assert "既有工作台状态未被本次失败改动" in out
        assert "建议" in out



    """storyboard_media_to_chat 的 target 结构化校验（对齐同族 view_storyboard_media）：
    draft_ids/target 均未命中合法取值 → error_code=validation 结构化报错（附合法取值），
    不再误报成「没有找到带媒体的目标草稿」（如传 current 等不支持值）。"""

    @pytest.fixture
    def svc(self, tmp_path):
        StateManager.reset_instance()
        instance = StateManager(str(tmp_path))
        StateManager._instance = instance
        yield instance
        StateManager.reset_instance()

    @pytest.mark.parametrize("target", ["current", "bogus", ""])
    async def test_invalid_target_structured_validation_error(self, svc, target):
        tool = StoryboardMediaToChatTool()
        result = await tool.aexecute(MediaToChatInput(target=target))
        assert result.success is False
        assert result.error_code == "validation"
        assert result.retryable is False
        # 报错附合法取值清单，与描述口径一致（不含 current）
        for valid in ("all", "all_keyElements", "all_shots", "all_audio"):
            assert valid in result.error
        assert "没有找到带媒体的目标草稿" not in str(result.error)

    async def test_valid_target_not_blocked_by_validation(self, svc):
        """合法 target 不进校验报错分支（空故事板回落既有「没找到」语义）。"""
        tool = StoryboardMediaToChatTool()
        result = await tool.aexecute(MediaToChatInput(target="all"))
        assert result.success is False
        assert result.error_code != "validation"
