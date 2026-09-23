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


class TestK4ThreeSourceRefMerge:
    """K4 批（2026-09-16 对齐 flova）：shotRefs 三源合并 =
    显式 shot_refs ∪ [元素名] 令牌 ∪ 裸名提及（去重保序）；
    未匹配令牌回喂不变。"""

    @pytest.fixture
    def svc(self, tmp_path):
        StateManager.reset_instance()
        instance = StateManager(str(tmp_path))
        StateManager._instance = instance
        instance.state_dict["keyElements"] = [
            {"id": "ke-1", "title": "Element_程心", "desc": "", "drafts": []},
            {"id": "ke-2", "title": "S1 星环号球形舱", "desc": "", "drafts": []},
        ]
        instance.state_dict["analysis"] = {"summary": "一句话总结"}
        instance.state_dict["documents"] = [
            {"name": "制片规格.md", "content": "规格"}]
        yield instance
        StateManager.reset_instance()

    async def test_three_source_merge_dedup_order(self, svc):
        result = await ToolManager.invoke_tool(
            "storyboard_create_group",
            {"group_type": "shot", "title": "S01",
             "desc": "程心 苏醒于 [S1 星环号球形舱] 内。",
             "summary": "含内部剪辑（约10s）",
             "shot_refs": ["S1 星环号球形舱"]})
        assert result.success is True, result.error
        group = svc.state_dict["shots"][-1]
        # 显式 ∪ 令牌 ∪ 裸名提及，去重保序（显式在前）
        assert group["shotRefs"] == ["S1 星环号球形舱", "Element_程心"]

    async def test_unmatched_token_still_reported(self, svc):
        result = await ToolManager.invoke_tool(
            "storyboard_create_group",
            {"group_type": "shot", "title": "S02",
             "desc": "程心 望着 [白色薄膜]。",
             "summary": "含内部剪辑（约8s）"})
        assert result.success is True
        group = svc.state_dict["shots"][-1]
        assert group["shotRefs"] == ["Element_程心"]
        assert "白色薄膜" in (result.data.get("detail") or "")


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
            "summary": "含内部剪辑（约10s）",
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

    标尺 = 外部实测转录：「镜头 ID 重复」失败两次，每次都明示
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
        """重复 ID（外部标杆 标尺）：写入前拦截、报错含保留声明、状态零污染。"""
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

    async def test_draft_json_string_coerced(self, svc):
        """批 6 · A3 宽容解析：draft 传 JSON 字符串自动拆包（8888 高频误用）。"""
        import json as _json
        gid = await self._new_group(svc)
        result = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid, "group_type": "keyElement",
            "draft": _json.dumps({"label": "程心", "desc": "黑色短发"}, ensure_ascii=False),
        })
        assert result.success is True, result.error
        group = next(g for g in svc.state_dict["keyElements"] if g["id"] == gid)
        assert group["drafts"][0]["desc"] == "黑色短发"

    async def test_draft_bad_string_rejected_atomically(self, svc):
        """draft 字符串拆不了包 → 三要素报错、状态零污染（不再是 pydantic 裸错）。"""
        gid = await self._new_group(svc)
        before = self._board_hash(svc)
        result = await ToolManager.invoke_tool("storyboard_add_draft", {
            "group_id": gid, "group_type": "keyElement",
            "draft": "这不是JSON",
        })
        assert result.success is False
        assert result.error_code == "validation"
        assert "JSON 对象" in result.error and "保持原样" in result.error
        assert self._board_hash(svc) == before

    async def test_shot_desc_tokens_fill_shot_refs(self, svc):
        """批 6 · A3 令牌解析：分镜描述里的 [元素名] 自动同步 shotRefs。"""
        await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "keyElement", "title": "太空艇"})
        shot = await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "shot", "title": "追击戏",
            "desc": "太空艇穿越陨石带，背景出现 [太空艇] 与指挥舱",
            "summary": "含内部剪辑（约10s）",
        })
        assert shot.success is True, shot.error
        group = next(g for g in svc.state_dict["shots"] if g["id"] == shot.data["group_id"])
        assert "Element_太空艇" in (group.get("shotRefs") or []), \
            f"令牌未解析进 shotRefs: {group.get('shotRefs')}"

    async def test_shot_explicit_shot_refs_merge_with_tokens(self, svc):
        """K4 批（2026-09-16）：显式 shot_refs 与令牌/裸名提及合并（去重保序，
        显式在前）——取代旧「显式为准、令牌只在缺省时解析」口径。"""
        await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "keyElement", "title": "太空艇"})
        shot = await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "shot", "title": "追击",
            "desc": "出现 [太空艇]",
            "summary": "含内部剪辑（约10s）",
            "shot_refs": ["显式引用"],
        })
        assert shot.success is True, shot.error
        group = next(g for g in svc.state_dict["shots"] if g["id"] == shot.data["group_id"])
        assert group.get("shotRefs") == ["显式引用", "Element_太空艇"]

    async def test_unknown_token_dropped_not_rejected(self, svc):
        """匹配不到元素的令牌静默丢弃（令牌是引导不是闸，不锁死）。"""
        shot = await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "shot", "title": "空镜",
            "desc": "雨夜街道 [不存在的元素]",
            "summary": "缓慢推近（约5s）",
        })
        assert shot.success is True, shot.error
        group = next(g for g in svc.state_dict["shots"] if g["id"] == shot.data["group_id"])
        assert group.get("shotRefs") == []

    async def test_failure_feedback_declares_state_preserved(self):
        """B5 ② 全局状态保留声明进入失败回喂（模型不得假设失败污染状态）。"""
        from src.video_agent.core.fc_feedback import compose_failure_feedback

        out = compose_failure_feedback(
            "image_generate", "上游超时", fail_count=1, error_code="timeout")
        assert "既有工作台状态未被本次失败改动" in out
        assert "建议" in out


class TestCreateGroupReceiptCarriesGroupId:
    """批2（Q3，用户裁决 2026-09-23）：**建组回执必须把 group_id 交给模型**。

    根因：`storyboard_create_group` 把 id 放在 `data["group_id"]`，而回喂
    格式化分支（fc_feedback.format_tool_results）**只取 `data["detail"]`**——
    group_id 从不进入模型上下文。模型建完组拿不到 id，只能靠 `current` 兜底，
    而 `current` 恒指该类目第一组（`find_group` 回落 `groups[0]`，非"最近组"），
    于是后续 add_draft 落错组——3333 三张音色卡落进音频层的机制根因。
    """

    def test_group_id_in_feedback_text(self):
        from src.video_agent.core.fc_feedback import format_tool_results

        out = format_tool_results([{
            "name": "storyboard_create_group", "ok": True,
            "data": {"group_id": "ke-7"},
        }])
        assert "ke-7" in out, "建组回执未携带 group_id（模型无法定位新组）"
        assert "current" in out, "应提示勿依赖 current（其语义非『最近组』）"

    def test_group_id_and_detail_both_present(self):
        """group_id 与既有 detail 并存（令牌未匹配提示不得被挤掉）。"""
        from src.video_agent.core.fc_feedback import format_tool_results

        out = format_tool_results([{
            "name": "storyboard_create_group", "ok": True,
            "data": {"group_id": "sh-3", "detail": "已建组，但描述中的 [元素名] 令牌未匹配"},
        }])
        assert "sh-3" in out and "令牌未匹配" in out

    def test_no_group_id_no_regression(self):
        """无 group_id 的工具回喂不受影响（不产生空行/畸形文案）。"""
        from src.video_agent.core.fc_feedback import format_tool_results

        out = format_tool_results([{
            "name": "script_analyze", "ok": True, "data": {"detail": "分析完成"},
        }])
        assert "分析完成" in out
        assert "分组 ID" not in out


class TestCreateGroupDescriptionContract:
    """批2（Q1-B/Q2-A，用户裁决）：建组正面契约必须在场。

    该引导句 2026-09-16 d75a374 被删且无闸机接管，直接导致：
      ①关键元素未一组一卡（2222 三个粗组）→ 前端候选源全是组标题；
      ②分镜引用候选源错位 → 26 镜 0 块引用。
    本条钉死契约不再被静默删除（且必须通过 description lint）。
    """

    def test_positive_contract_present(self):
        from src.video_agent.tools.storyboard_tools import StoryboardCreateGroupTool

        d = StoryboardCreateGroupTool.description
        assert "每个元素单独一组" in d, "关键元素一组一卡契约丢失"
        assert "组名=元素名" in d
        assert "[元素名]" in d, "分镜引用令牌契约丢失"

    def test_passes_description_lint(self):
        """契约句不得引入 lint 禁令词（说明层只留正面契约）。"""
        from src.video_agent.tools.storyboard_tools import StoryboardCreateGroupTool
        import importlib.util
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "_desc_lint", root / "scripts" / "check_tool_descriptions.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod._check_description(StoryboardCreateGroupTool.description) == []


class TestDeleteDraftTool:
    """批2（Q3）：删单卡工具接线（ops.delete_draft 早已存在但从未暴露为工具）。"""

    @pytest.fixture
    def svc(self, tmp_path):
        StateManager.reset_instance()
        instance = StateManager(str(tmp_path))
        StateManager._instance = instance
        # 清空默认演示盘面：编号口径（'1-2'）按类别从 1 起算，
        # 盘面有存量组会让编号指向演示数据而非本用例新建的组。
        for cat in ("keyElements", "shots", "audioItems"):
            instance.state_dict[cat] = []
        instance.save()
        yield instance
        StateManager.reset_instance()

    async def _seed_two_cards(self, svc):
        """经真实工具流建组+建卡（id 由平台归一，不手写裸 id）。"""
        gid = (await ToolManager.invoke_tool(
            "storyboard_create_group",
            {"group_type": "keyElement", "title": "程心"})).data["group_id"]
        for label in ("三视图", "错卡"):
            r = await ToolManager.invoke_tool("storyboard_add_draft", {
                "group_id": gid, "group_type": "keyElement",
                "draft": {"label": label, "mediaType": "image", "imgUrl": f"/a/{label}.png"},
            })
            assert r.success is True, r.error
        group = next(g for g in svc.state_dict["keyElements"] if g["id"] == gid)
        return gid, [d["id"] for d in group["drafts"]]

    async def test_tool_registered(self):
        from src.video_agent.tools.manager import ToolManager

        assert ToolManager.get_tool("storyboard_delete_draft") is not None

    async def test_delete_by_real_id(self, svc):
        gid, ids = await self._seed_two_cards(svc)
        target, keep = ids[1], ids[0]
        res = await ToolManager.invoke_tool(
            "storyboard_delete_draft", {"draft_id": target, "draft_type": "keyElement"})
        assert res.success is True, res.error
        assert res.data["deleted"] == [target]
        group = next(g for g in svc.state_dict["keyElements"] if g["id"] == gid)
        left = [d["id"] for d in group["drafts"]]
        assert left == [keep], "目标卡应被删除、其余卡保持"

    async def test_delete_by_index_ref(self, svc):
        """编号口径（'1-2'）也可用（经 find_draft 解析后按真实 ID 删）。"""
        gid, ids = await self._seed_two_cards(svc)
        res = await ToolManager.invoke_tool(
            "storyboard_delete_draft", {"draft_id": "1-2", "draft_type": "keyElement"})
        assert res.success is True, res.error
        group = next(g for g in svc.state_dict["keyElements"] if g["id"] == gid)
        left = [d["id"] for d in group["drafts"]]
        assert left == [ids[0]]

    async def test_missing_draft_reports_not_found(self, svc):
        gid, ids = await self._seed_two_cards(svc)
        res = await ToolManager.invoke_tool(
            "storyboard_delete_draft", {"draft_id": "不存在", "draft_type": "keyElement"})
        assert res.success is False
        assert "not found" in str(res.error)
        # 状态保持原样
        group = next(g for g in svc.state_dict["keyElements"] if g["id"] == gid)
        assert len(group["drafts"]) == 2


class TestCategoryMediaMatrixSchemaLayer:
    """批4/5（D-2=schema 层 / D-3=给字段+正面契约，不加硬判）。

    取证根因：平台**不存在**「类目×能力」矩阵——真实出处是前端散落的
    if/Switch + 后端按**阶段**的单点黑名单（维度不同、不可互推）；
    类目约束缺失已致实跑混装（2222 keyElement 组内 3 张 audio 卡、
    3333 shot 组内 15 张 image 卡）。
    """

    def test_matrix_single_source_matches_user_spec(self):
        """矩阵逐格对齐用户要求（逐字：KE 全通；shot 只视频；audio 只音频）。"""
        from src.video_agent.state import storyboard_ops as ops

        ke = ops.CATEGORY_MEDIA_MATRIX["keyElement"]
        assert ke["place"] == frozenset({"image", "video", "audio"})
        assert ke["generate"] == frozenset({"image", "video", "audio"})

        shot = ops.CATEGORY_MEDIA_MATRIX["shot"]
        assert shot["place"] == frozenset({"video"}), "分镜只能放视频"
        assert shot["generate"] == frozenset({"video"}), "分镜只能出视频"

        audio = ops.CATEGORY_MEDIA_MATRIX["audio"]
        assert audio["place"] == frozenset({"audio"}), "音频只能放音频"
        assert audio["generate"] == frozenset({"audio"}), "音频只能出音频"

    def test_matrix_is_queryable_data(self):
        """矩阵是可查数据（单一事实源），非散落 if。"""
        from src.video_agent.state import storyboard_ops as ops

        assert ops.matrix_media_for("shot", "place") == frozenset({"video"})
        assert ops.matrix_media_for("audio", "generate") == frozenset({"audio"})
        # 未知类目/能力 → 空集（不约束，不误判）
        assert ops.matrix_media_for("不存在", "place") == frozenset()
        assert ops.matrix_media_for("shot", "不存在") == frozenset()

    def test_contract_line_is_positive_only(self):
        """契约句只陈述「能做什么」（正面契约），且过 description lint 词表。"""
        from src.video_agent.state import storyboard_ops as ops

        line = ops.matrix_contract_line("shot")
        assert "可放：视频" in line and "可出：视频" in line
        for banned in ("不得", "禁止", "不要", "不允许", "违规"):
            assert banned not in line, f"契约句含禁令词 {banned}"

    def test_contract_visible_in_tool_schema(self):
        """契约必须在**模型可见的 schema 描述**里（D-2=schema 层的落点）。"""
        from src.video_agent.tools.storyboard_tools import CreateGroupInput

        desc = CreateGroupInput.model_fields["group_type"].description
        assert "类目能力矩阵" in desc
        assert "shot（该类目可放：视频；可出：视频）" in desc


class TestElementAndAudioTypeFields:
    """批5（D-1/D-2/D-3）：归属语义落成模型可见字段。

    根因：平台注释里写对了归属（audio ← key_elements 音色卡），
    但可执行代码 0 命中、草稿白名单没有 elementType/audioType——
    模型**没有字段可用**，只能自发用 tag/desc 表达而平台不消费。
    """

    def test_fields_in_whitelist(self):
        from src.video_agent.state import storyboard_ops as ops

        assert "audioType" in ops.ALLOWED_DRAFT_FIELDS
        assert "audioType" in ops.ALLOWED_NEW_DRAFT_FIELDS
        assert "elementType" in ops.ALLOWED_GROUP_FIELDS

    def test_vocabularies_declared(self):
        """取值词表登记为单一事实源；voice = Skill 明文的 key_element_audio。"""
        from src.video_agent.state import storyboard_ops as ops

        assert "voice" in ops.AUDIO_TYPES
        assert ops.AUDIO_TYPES[0] == "voice", "voice 应为首项（主用途）"
        assert ops.ELEMENT_TYPES == ("character", "scene", "prop")

    def test_audio_type_visible_in_draft_hint(self):
        """audioType 必须在 draft 字段提示里（模型才知道有这个格子）。"""
        from src.video_agent.tools.storyboard_tools import AddDraftInput

        desc = AddDraftInput.model_fields["draft"].description
        assert "audioType" in desc
        assert "voice" in desc

    async def test_element_type_persists_on_group(self, tmp_path):
        StateManager.reset_instance()
        svc = StateManager(str(tmp_path))
        StateManager._instance = svc
        for cat in ("keyElements", "shots", "audioItems"):
            svc.state_dict[cat] = []
        try:
            r = await ToolManager.invoke_tool("storyboard_create_group", {
                "group_type": "keyElement", "title": "程心",
                "element_type": "character"})
            assert r.success is True, r.error
            g = svc.state_dict["keyElements"][0]
            assert g.get("elementType") == "character"
        finally:
            StateManager.reset_instance()

    async def test_audio_type_persists_on_draft(self, tmp_path):
        StateManager.reset_instance()
        svc = StateManager(str(tmp_path))
        StateManager._instance = svc
        for cat in ("keyElements", "shots", "audioItems"):
            svc.state_dict[cat] = []
        try:
            gid = (await ToolManager.invoke_tool("storyboard_create_group", {
                "group_type": "keyElement", "title": "程心"})).data["group_id"]
            r = await ToolManager.invoke_tool("storyboard_add_draft", {
                "group_id": gid, "group_type": "keyElement",
                "draft": {"label": "程心音色", "mediaType": "audio",
                          "audioType": "voice"}})
            assert r.success is True, r.error
            d = svc.state_dict["keyElements"][0]["drafts"][0]
            assert d.get("audioType") == "voice"
        finally:
            StateManager.reset_instance()

    async def test_element_type_absent_by_default(self, tmp_path):
        """不传则不落字段（空=未声明，不强制、不判错——给字段而非加闸）。"""
        StateManager.reset_instance()
        svc = StateManager(str(tmp_path))
        StateManager._instance = svc
        for cat in ("keyElements", "shots", "audioItems"):
            svc.state_dict[cat] = []
        try:
            r = await ToolManager.invoke_tool("storyboard_create_group", {
                "group_type": "keyElement", "title": "程心"})
            assert r.success is True, r.error
            assert "elementType" not in svc.state_dict["keyElements"][0]
        finally:
            StateManager.reset_instance()


class TestSectionCategoryFieldChain:
    """批9 P-1（D-2 裁决）：补「章节 → 类目 → 字段」完整链。

    全量审计（16 Skill）结论：①章节名→映射 ✅ 全对应；
    ②章节→注入 ⚠️ 4 个发不出去；③**章节→字段 ❌ 真消费仅 2** ——
    用户所指"对应不上"落在第三层：章节语义止步于平台内部代号
    （section 名），从未落到模型可见字段。本类钉死补上的中间一级。
    """

    def test_section_maps_to_category(self):
        """三章节各自对应一个故事板类目（用户点名的那三个）。"""
        from src.video_agent.state import storyboard_ops as ops

        assert ops.category_for_section("storyboard_ke") == "keyElements"
        assert ops.category_for_section("storyboard_shot") == "shots"
        assert ops.category_for_section("storyboard_audio") == "audioItems"

    def test_unknown_section_returns_empty(self):
        """未知章节 → 空串（无承载，不误判到某个类目）。"""
        from src.video_agent.state import storyboard_ops as ops

        assert ops.category_for_section("") == ""
        assert ops.category_for_section("不存在章节") == ""

    def test_reverse_lookup_consistent(self):
        """反向查与正向查同源（双向一致）。"""
        from src.video_agent.state import storyboard_ops as ops

        for sec, cat in ops.SECTION_CATEGORY_BINDING.items():
            # 反向查返回的是**章节名**列表，须含本 section
            assert sec in ops.sections_for_category(cat)
            assert ops.category_for_section(sec) == cat

    def test_binding_covers_real_skill_sections(self):
        """绑定表的 section 名必须是平台真实存在的（防拼错=静默失效）。"""
        from src.video_agent.skill_runtime.registry import CAPABILITY_TOOL_STAGES
        from src.video_agent.state import storyboard_ops as ops

        known = {s for secs in CAPABILITY_TOOL_STAGES.values() for s in secs}
        for sec in ops.SECTION_CATEGORY_BINDING:
            assert sec in known, f"绑定表 section {sec!r} 不在平台章节映射里"

    def test_binding_targets_are_real_categories(self):
        """绑定目标必须是真实类目（防写到不存在的键）。"""
        from src.video_agent.state import storyboard_ops as ops
        from src.video_agent.state.models import ALL_CATEGORIES

        for cat in ops.SECTION_CATEGORY_BINDING.values():
            assert cat in ALL_CATEGORIES


class TestMediaToChatTargetValidation:
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
