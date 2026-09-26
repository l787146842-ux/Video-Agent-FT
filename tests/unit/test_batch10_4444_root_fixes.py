# -*- coding: utf-8 -*-
"""批10（2026-09-23，事故 4444 实跑复盘）：四项根因修复的回归钉。

事故素材：`proj-1790159421-bfd25491`（项目名 4444），跑于 2026-09-23 18:30–18:49，
一次完整 5 轮实跑（无 504、无子代理死亡）。逐项取证见
`reports/4444-运行问题取证-20260923.md`（该取证报告正文已归档删除，结论已固化为本文件回归钉）。

本文件钉四件事（每条都写明「不修会怎样」）：

| # | 事故编号 | 缺陷 | 本文件对应 |
|---|---|---|---|
| P0-A | 4444/P0-A | shotRefs 引用链**写口 canonical / 读口逐字**，恒不命中 | `TestShotRefsCanonicalResolution` |
| P0-B | 4444/P0-B | 下发 schema 丢 `$defs` → `$ref` 悬空，条目字段名到不了模型 | `TestToolSchemaRefInlining` |
| P1-1 | 4444/P1-1 | 无「改分组」工具 → 改一个引用要删光重建整类目 | `TestPatchGroupTool` |
| P1-3 | 4444/P1-3 | 失败计数按**工具名**累计，同批第 N 个成员被冤枉「已失败 2 次」 | `TestPerCallFailureCounter` |
"""
import json

import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.storyboard_tools import (
    PatchGroupInput,
    StoryboardPatchGroupTool,
    register_storyboard_tools,
)


@pytest.fixture(autouse=True)
def _reset_tools():
    ToolManager.reset()
    register_storyboard_tools()
    # `todo_write` 是 P0-B 的取证对象（唯一的嵌套 BaseModel 入参），
    # 默认 fixture 只注册故事板工具，此处显式补上
    from src.video_agent.tools.todo_tools import register_todo_tools

    register_todo_tools()
    yield
    ToolManager.reset()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    for cat in ("keyElements", "shots", "audioItems"):
        instance.state_dict[cat] = []
    yield instance
    StateManager.reset_instance()


# =====================================================================
# P0-A · shotRefs 引用链 canonical 解析
# =====================================================================
class TestShotRefsCanonicalResolution:
    """4444/P0-A：**写口 canonical、读口逐字**的口径漂移。

    病灶：落盘组标题带容器前缀（`Element_程心`，写口 `normalize_group_title`
    幂等补），而 `shotRefs` 存**裸名**（`程心`，写口 `dedup_shot_refs` 明写
    「裸名与 Element_ 前缀算同一引用」）。读口旧实现却是
    `if id != ref and title != ref: continue` —— 逐字比对 ⇒ **恒不命中**。

    实跑取证（4444 真实 state 复算）：22 镜 90 条 shotRefs → `image_refs`
    **0**、`audio_refs` **0**；改 canonical 键复算 → **90/90 命中**。

    同源失配在 `core/prompt_refs.py`（批3 R3）**已修过**，判词逐字：
    「平台在别处早就做了裸名归一，**唯独本引用链漏了，属口径漂移而非设计**」。
    ——本类即把那条判词钉在引用链上。

    ⚠️ 为何此前测试全绿：现有两用例**恰好只测带前缀写法**
    （`test_video_multimodal.py` 用 `Element_侦探`、`test_888_fixes.py`
    的标题恰为无前缀裸名），两条路径都绕开了真实落盘形态。
    """

    @pytest.fixture
    def state(self):
        return {
            "keyElements": [
                {"id": "ke-chengxin", "title": "Element_程心", "drafts": [
                    {"mediaType": "image", "imgUrl": "http://img/cx.png"},
                    {"mediaType": "audio", "audioType": "voice",
                     "audioUrl": "http://aud/cx.wav"},
                ]},
                {"id": "ke-aa", "title": "Element_AA", "drafts": [
                    {"mediaType": "audio", "audioType": "voice",
                     "audioUrl": "http://aud/aa.wav"},
                ]},
            ],
            "shots": [], "audioItems": [],
        }

    def test_bare_name_hits_image_ref(self, state):
        """裸名（真实落盘形态）必须命中 —— 这条就是 4444 恒 0 的那条。"""
        shot = {"id": "s1", "shotRefs": ["程心"]}
        refs = ops.resolve_shot_refs(state, shot)
        assert [r["url"] for r in refs] == ["http://img/cx.png"], (
            "裸名 shotRefs 未命中关键元素图 —— 引用链退回逐字比对")

    def test_prefixed_name_still_hits(self, state):
        """带前缀写法向后兼容（存量数据与既有测试口径不翻）。"""
        shot = {"id": "s2", "shotRefs": ["Element_程心"]}
        assert len(ops.resolve_shot_refs(state, shot)) == 1

    def test_group_id_still_hits(self, state):
        """组 id 写法同口径兼容（旧注释声称支持，实测同样失效）。"""
        shot = {"id": "s3", "shotRefs": ["ke-chengxin"]}
        assert len(ops.resolve_shot_refs(state, shot)) == 1

    def test_unknown_ref_yields_nothing(self, state):
        """查无此元素不命中（不做模糊匹配，避免误挂他人参考图）。"""
        shot = {"id": "s4", "shotRefs": ["查无此人"]}
        assert ops.resolve_shot_refs(state, shot) == []

    def test_voice_anchor_resolves_for_bare_name(self, state):
        """音色锚点（reference_audio）同样按 canonical 命中（姊妹轴）。"""
        shot = {"id": "s5", "shotRefs": ["程心", "AA"]}
        urls = [r["url"] for r in ops.resolve_shot_audio_refs(state, shot)]
        assert urls == ["http://aud/cx.wav", "http://aud/aa.wav"]

    def test_voice_card_preferred_over_other_audio(self, state):
        """同组内若有非 voice 音源，**voice 卡优先**（音色锚点的规范载体）。"""
        state["keyElements"][0]["drafts"].append(
            {"mediaType": "audio", "audioType": "sfx", "audioUrl": "http://aud/sfx.wav"})
        shot = {"id": "s6", "shotRefs": ["程心"]}
        urls = [r["url"] for r in ops.resolve_shot_audio_refs(state, shot)]
        assert urls == ["http://aud/cx.wav"], "未优先取 voice 卡"

    def test_non_voice_falls_back_when_no_voice_card(self, state):
        """无 voice 卡时回落该组任意音源（存量兼容，非硬判）。"""
        state["keyElements"] = [
            {"id": "ke-x", "title": "Element_程心",
             "drafts": [{"mediaType": "audio", "audioType": "sfx",
                         "audioUrl": "http://aud/only.wav"}]}]
        shot = {"id": "s7", "shotRefs": ["程心"]}
        assert [r["url"] for r in ops.resolve_shot_audio_refs(state, shot)] == \
            ["http://aud/only.wav"]

    def test_find_ref_group_is_single_entry_point(self):
        """四处消费共用同一入口（本次事故正是四处各写一遍且全部逐字比对）。"""
        import inspect
        src = inspect.getsource(ops.resolve_shot_refs)
        assert "find_ref_group" in src
        src2 = inspect.getsource(ops.resolve_shot_audio_refs)
        assert "find_ref_group" in src2

    def test_web_consumers_use_shared_entry_point(self):
        """web 层两个抄写点也改走 find_ref_group（防回潮成各自比对）。"""
        import inspect
        from src.video_agent.web.routes import generate_image
        from src.video_agent.web import multimodal_builder

        for mod in (generate_image, multimodal_builder):
            text = inspect.getsource(mod)
            assert "find_ref_group" in text, f"{mod.__name__} 未走统一入口"


# =====================================================================
# P0-B · 下发 schema 的 $ref 内联
# =====================================================================
class TestToolSchemaRefInlining:
    """4444/P0-B：`_full_schemas` 只取 properties+required，**丢弃 `$defs`**。

    pydantic 对嵌套 BaseModel（`List[TodoItem]`）产出
    `items: {"$ref": "#/$defs/TodoItem"}` —— 丢 `$defs` 后该引用**悬空**，
    条目字段名一个字节都到不了模型。实跑取证：`todo_write` 被调 11 次、
    **失败 7 次**，模型原地盲猜键名 `title`→`text`→`label`→`item` 四种全错
    （而状态值每次都填对，证明它读懂了描述、只是不知道键叫什么）。

    ⚠️ 为何此前测试全绿：`test_todo_write.py` 全走 `invoke_tool(name, {...})`
    **直传 dict**，验的是 pydantic 执行链路（`$defs` 在 pydantic 内部完好）；
    缺陷在 `_full_schemas` **下发链路**。两条路各自都对，交汇处漏了。
    ——故本类的钉子必须打在下发层。
    """

    def _schemas(self):
        ToolManager._schema_cache = None
        return ToolManager._full_schemas()

    def test_no_dangling_ref_in_any_tool_schema(self):
        """全部工具的下发 schema 一律自足（含 `$ref`/`$defs` 即 FAIL）。"""
        offenders = []
        for s in self._schemas():
            blob = json.dumps(s["function"]["parameters"], ensure_ascii=False)
            if "$ref" in blob or "$defs" in blob:
                offenders.append(s["function"]["name"])
        assert offenders == [], (
            f"下发 schema 仍含未解析引用（模型看不见子字段名）：{offenders}")

    def test_todo_write_item_fields_reach_the_model(self):
        """`todo_write` 的条目字段名必须真的下发（4444 盲猜 7 次的直接原因）。"""
        schema = next(s for s in self._schemas()
                      if s["function"]["name"] == "todo_write")
        blob = json.dumps(schema, ensure_ascii=False)
        assert '"content"' in blob, "条目字段 content 未下发"
        assert '"status"' in blob, "条目字段 status 未下发"
        assert "in_progress" in blob, "状态枚举未下发"

    def test_inlined_item_keeps_structural_constraints(self):
        """内联后仍保留 `additionalProperties: false` 与 required（形状不退化）。"""
        schema = next(s for s in self._schemas()
                      if s["function"]["name"] == "todo_write")
        items = schema["function"]["parameters"]["properties"]["todos"]["items"]
        assert items.get("additionalProperties") is False
        assert set(items.get("required") or []) == {"content", "status"}
        assert set((items.get("properties") or {}).keys()) == {"content", "status"}

    def test_referenced_model_docstring_not_leaked(self):
        """被引用模型的**类 docstring** 不得进模型上下文。

        pydantic 把类 docstring 映射成该模型的 `description`。内联首次会让它
        进入模型可见文本（`TodoItem` 的 docstring 写着「对齐 dsh」「pydantic
        extra=forbid」「:83-84 注释逐字」等**实现说明**）——这些 prose 从未
        进过模型上下文，属**内联引入的新泄漏面**（同 4444/Q2①「内部机制词
        喂进模型上下文」事故口径）。字段级 description 是有意写给模型的，保留。
        """
        schema = next(s for s in self._schemas()
                      if s["function"]["name"] == "todo_write")
        items = schema["function"]["parameters"]["properties"]["todos"]["items"]
        assert "description" not in items, "被引用模型的 docstring 泄漏进模型上下文"
        assert "title" not in items, "被引用模型的类名泄漏进模型上下文"
        # 字段级 description 必须保留（那是有意写给模型的）
        assert items["properties"]["content"].get("description")

    def test_inliner_is_fail_loud_on_undefined_ref(self):
        """引用解析不到定义时**抛错**，不回落成残缺 schema（fail-loud）。"""
        from src.video_agent.tools.manager import inline_json_schema_refs

        with pytest.raises(ValueError):
            inline_json_schema_refs({
                "type": "object",
                "properties": {"x": {"items": {"$ref": "#/$defs/Nope"}}},
                "$defs": {},
            })

    def test_inliner_handles_schema_without_defs(self):
        """无 `$defs` 的普通 schema 原样通过（24 个既有工具零变化）。"""
        from src.video_agent.tools.manager import inline_json_schema_refs

        plain = {"type": "object", "properties": {"a": {"type": "string"}},
                 "required": ["a"]}
        assert inline_json_schema_refs(plain) == plain


# =====================================================================
# P1-1 · storyboard_patch_group
# =====================================================================
class TestPatchGroupTool:
    """4444/P1-1：`ops.patch_group` 与 `PATCH /storyboard/groups/{id}` 早就存在，
    **却从未接线成模型工具** —— 模型改一个分组的 `shotRefs` 只能
    「删除整组 + 重建整组」。4444 为此**删光 22 个 shot 组再重建 22 个**、
    耗时 261.6s，且重建产生**全新 group id**（中途任一批失败即留下残缺故事板）。

    与 09-23 批2 补 `storyboard_delete_draft` 是同一类缺口（既有能力未接线）。
    """

    async def _mk_shot(self, svc, refs=("程心",)):
        r = await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "shot", "title": "程心苏醒",
            "desc": "[程心] 睁眼", "summary": "缓推（约5s）",
            "shot_refs": list(refs)})
        assert r.success is True, r.error
        return r.data["group_id"]

    async def test_tool_registered(self):
        assert ToolManager.get_tool("storyboard_patch_group") is not None

    async def test_patch_shot_refs_keeps_group_id_and_order(self, svc):
        """**核心钉**：改引用后分组 **id 与顺序逐个未变**（4444 事故的反面）。

        删除重建会换掉全部 id（子代理自己也警告「旧 id 已删除，后续阶段
        勿沿用」）——本条把「就地更新」钉死。
        """
        gid = await self._mk_shot(svc)
        await self._mk_shot(svc)
        ids_before = [g["id"] for g in svc.state_dict["shots"]]
        order_before = [g["title"] for g in svc.state_dict["shots"]]

        r = await ToolManager.invoke_tool("storyboard_patch_group", {
            "group_id": gid, "group_type": "shot",
            "patch": {"shotRefs": ["程心", "AA"]}})
        assert r.success is True, r.error
        assert [g["id"] for g in svc.state_dict["shots"]] == ids_before, \
            "改引用后 group id 变了（退化成删除重建）"
        assert [g["title"] for g in svc.state_dict["shots"]] == order_before
        target = next(g for g in svc.state_dict["shots"] if g["id"] == gid)
        assert target["shotRefs"] == ["程心", "AA"]

    async def test_shot_refs_dedup_canonical(self, svc):
        """shotRefs 走 canonical 去重（裸名与带前缀算同一引用，与建组同口径）。"""
        gid = await self._mk_shot(svc)
        r = await ToolManager.invoke_tool("storyboard_patch_group", {
            "group_id": gid, "group_type": "shot",
            "patch": {"shotRefs": ["程心", "Element_程心"]}})
        assert r.success is True, r.error
        target = next(g for g in svc.state_dict["shots"] if g["id"] == gid)
        assert target["shotRefs"] == ["程心"], "canonical 去重未生效"

    async def test_whitelist_rejection_is_atomic(self, svc):
        """白名单外字段**原子拒收**：不写入任何字段（含合法字段也不写）。"""
        gid = await self._mk_shot(svc)
        before = json.dumps(svc.state_dict["shots"], ensure_ascii=False, sort_keys=True)
        r = await ToolManager.invoke_tool("storyboard_patch_group", {
            "group_id": gid, "group_type": "shot",
            "patch": {"desc": "新描述", "badField": 1}})
        assert r.success is False
        assert r.error_code == "validation" and r.retryable is False
        after = json.dumps(svc.state_dict["shots"], ensure_ascii=False, sort_keys=True)
        assert before == after, "拒收却改动了状态（非原子）"
        assert "badField" in str(r.error) and "保持原样" in str(r.error)

    async def test_empty_patch_rejected(self, svc):
        """空 patch 拒收，不假装成功（防「空提交返回 success」的假成功）。"""
        gid = await self._mk_shot(svc)
        r = await ToolManager.invoke_tool("storyboard_patch_group", {
            "group_id": gid, "patch": {}})
        assert r.success is False and r.error_code == "validation"

    async def test_not_found_reports_three_elements(self, svc):
        """not found 三要素：原因 + 状态保留声明 + 下一步（与同族工具同口径）。"""
        r = await ToolManager.invoke_tool("storyboard_patch_group", {
            "group_id": "nope", "patch": {"desc": "x"}})
        assert r.success is False
        assert r.error_code == "not_found" and r.retryable is False
        assert "not found" in str(r.error)
        assert "保持原样" in str(r.error)
        assert "read_state_group" in str(r.error)

    async def test_title_normalized_with_container_prefix(self, svc):
        """title 写口归一：幂等补容器前缀（与建组同一写口，防引用锚点口径破裂）。"""
        r = await ToolManager.invoke_tool("storyboard_create_group", {
            "group_type": "keyElement", "title": "程心"})
        gid = r.data["group_id"]
        r2 = await ToolManager.invoke_tool("storyboard_patch_group", {
            "group_id": gid, "group_type": "keyElement",
            "patch": {"title": "新程心"}})
        assert r2.success is True, r2.error
        assert svc.state_dict["keyElements"][0]["title"] == "Element_新程心"

    def test_patch_field_whitelist_is_single_source(self):
        """入参 hint 只引用 ALLOWED_GROUP_FIELDS，不复制名单（P1 单一事实源）。"""
        from src.video_agent.tools import storyboard_tools as st

        for f in ops.ALLOWED_GROUP_FIELDS:
            assert f in st._GROUP_FIELDS_HINT
        assert PatchGroupInput.model_fields["patch"] is not None
        assert StoryboardPatchGroupTool.name == "storyboard_patch_group"

    def test_visible_to_subagent_not_main_agent(self):
        """结构与 create/delete_group 同档：主代理 deny、故事板阶段持有。

        （fail-loud：二者必须同批改，否则 subagent import 期即 raise。）
        """
        from src.video_agent.core.subagent import MAIN_AGENT_DENY, _STAGE_TOOLS

        assert "storyboard_patch_group" in MAIN_AGENT_DENY
        assert "storyboard_patch_group" in _STAGE_TOOLS["storyboard_design"]


# =====================================================================
# P1-3 · 逐调用失败计数
# =====================================================================
class TestPerCallFailureCounter:
    """4444/P1-3：失败计数按**工具名**累计，而提示语说的是「**同参**重试」。

    实跑取证：同一批 5 个 shot（内容各不相同）各自失败，从第 2 个起每个都收到
    「该工具已连续失败 2 次，**同参**重试大概率仍失败」——对第 5 个纯属冤枉
    （它才第一次上场，且它的问题与别人不同）。计数键必须是**入参**而非工具名。
    """

    def test_fingerprint_distinguishes_different_args(self):
        from src.video_agent.core.fc_tool_runner import _call_fingerprint

        a = _call_fingerprint("t", {"x": 1})
        b = _call_fingerprint("t", {"x": 2})
        assert a != b, "不同入参必须取到不同指纹（否则又退化成按工具名计数）"

    def test_fingerprint_same_args_stable(self):
        from src.video_agent.core.fc_tool_runner import _call_fingerprint

        assert _call_fingerprint("t", {"a": 1, "b": 2}) == \
            _call_fingerprint("t", {"b": 2, "a": 1}), "键序不应影响指纹"

    def test_fingerprint_survives_unserializable_args(self):
        """入参不可 JSON 化时不抛错（记账不得打断执行路径）。"""
        from src.video_agent.core.fc_tool_runner import _call_fingerprint

        assert isinstance(_call_fingerprint("t", {"o": object()}), str)

    def test_runner_uses_per_call_counter(self):
        """执行器须持有逐调用计数与总量计数两本账（各司其职）。"""
        import inspect
        from src.video_agent.core import fc_tool_runner as m

        src = inspect.getsource(m.FCToolRunner.__init__)
        assert "_call_fail_counts" in src and "_tool_fail_totals" in src
        assert "_tool_fail_counts" not in src, "旧按工具名计数未清除"
