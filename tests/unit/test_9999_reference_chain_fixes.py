# -*- coding: utf-8 -*-
"""2026-09-26 批（9999 项目三问）：引用链两处口径缺口的回归钉。

现场：`proj-1790358500-25465d26`（项目名 9999，用户截图报告）。三问取证见
`.tmp_probe/audit_A_shotrefs.md` / `audit_B_refassets.md`（只读取证报告）。

本文件钉四件事（每条都写明「不修会怎样」）：

| # | 缺陷 | 不修会怎样 | 本文件对应 |
|---|---|---|---|
| ① | 组名**括注别名**（`艾AA（AA）`）无归一，正文写主名（`艾AA`）恒不命中 | desc 内联图块不渲染、裸名绑定落空、闸机漏检**且零告警** | `TestAliasNameVariants` |
| ② | `refAssets` 写口收**草稿 id**（`draft-…`）却按 URL 消费 | 前端图裂成 alt 文字；生成时参考图被当 URL 发出去 ⇒ **静默落空**（花钱白挂） | `TestRefAssetsNormalization` |
| ③ | `resolve_shot_refs` 取「组内首张有图卡」，无种类判据 | 组内先有视频/其他图卡时取错参考图 | `TestShotRefsKindPreference` |
| ④ | 闸机标题覆盖检查用**单向**剥前缀比对 | 带括注的组名恒不命中 ⇒ 漏引不被拦 | `TestGateTitleCoverageAlias` |
"""
import pytest

from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.models import build_draft_dict


# =====================================================================
# ① 括注别名归一（引用匹配候选名的唯一入口）
# =====================================================================
class TestAliasNameVariants:
    """9999 实测：模型建组入参 `艾AA（AA）`/`曹彬（老年）`/`星环号球形舱（木星轨道）`
    （reasoning 原话即如此，动机是消歧），平台按「名字原样保留」落库；
    而正文/引用写的是括注前主名 ⇒ 旧候选形态（完整标题 + 剥前缀）**逐字子串全不命中**。
    自然对照：无括注的组名（`程心`）一切正常——同一份代码只在这一种命名形态上失配。"""

    def test_alias_name_extracts_main_name(self):
        assert ops.element_alias_name("Element_艾AA（AA）") == "艾AA"
        assert ops.element_alias_name("Element_曹彬（老年）") == "曹彬"
        assert ops.element_alias_name("Element_星环号球形舱（木星轨道）") == "星环号球形舱"
        # 半角括号同待遇
        assert ops.element_alias_name("Element_AA(AA)") == "AA"

    def test_alias_name_empty_when_no_bracket(self):
        """无括注 ⇒ 空串（不产出别名候选；主名 = 剥前缀名，已由第二形态覆盖）。"""
        assert ops.element_alias_name("Element_程心") == ""
        assert ops.element_alias_name("Element_白色薄片") == ""

    def test_alias_name_rejects_too_short_main(self):
        """主名 <2 字符不产出（单字歧义过大，宁缺毋滥）。"""
        assert ops.element_alias_name("Element_A（别名）") == ""

    def test_variants_cover_three_forms(self):
        assert ops.element_name_variants("Element_艾AA（AA）") == [
            "Element_艾AA（AA）", "艾AA（AA）", "艾AA"]
        # 无括注时只有两形态（去重）
        assert ops.element_name_variants("Element_程心") == ["Element_程心", "程心"]

    def test_variants_are_deduped(self):
        """形态重复时不产双份（`Element_A` 剥前缀后与别名同形）。"""
        assert ops.element_name_variants("Element_程心") == list(
            dict.fromkeys(ops.element_name_variants("Element_程心")))

    def test_bare_mention_hits_main_name(self):
        """**本批核心钉子**：正文写主名 `艾AA` ⇒ 裸名提及必须命中。

        修复前 `scan_bare_name_mentions` 只登记「完整标题 + 剥前缀」，
        `艾AA` 不是 `艾AA（AA）` 的子串 ⇒ 返回空 ⇒ 引用静默落空。"""
        kes = [{"id": "ke-1", "title": "Element_艾AA（AA）"},
               {"id": "ke-2", "title": "Element_曹彬（老年）"},
               {"id": "ke-3", "title": "Element_程心"}]
        desc = "人物当前状态：程心（中景偏左，刚睁眼醒转）；艾AA（近景偏右，抓扶手）。曹彬没有马上回答。"
        hits = ops.scan_bare_name_mentions(desc, kes)
        assert "Element_艾AA（AA）" in hits, "带括注别名的主名提及未绑定（问题1 复现）"
        assert "Element_曹彬（老年）" in hits, "带括注别名的主名提及未绑定"
        assert "Element_程心" in hits, "无括注元素回归"

    def test_bare_mention_no_false_positive_on_bracket_form(self):
        """正文写全称括注形态照常命中（不因新增主名形态而丢失既有写法）。"""
        kes = [{"id": "ke-1", "title": "Element_艾AA（AA）"}]
        assert ops.scan_bare_name_mentions("艾AA（AA）站在舱内", kes) == ["Element_艾AA（AA）"]

    def test_token_match_hits_all_three_forms(self):
        """`[艾AA]` / `[艾AA（AA）]` / `[Element_艾AA（AA）]` 三写法同命。"""
        state = {"keyElements": [{"id": "ke-1", "title": "Element_艾AA（AA）"}]}
        for token in ("艾AA", "艾AA（AA）", "Element_艾AA（AA）"):
            matched, unmatched = ops.match_element_titles_report(state, [token])
            assert matched == ["Element_艾AA（AA）"], f"令牌 {token!r} 未命中"
            assert unmatched == []

    def test_token_unmatched_still_reported(self):
        """未匹配令牌仍如实回喂（新增形态不得把 unknown 也吞成命中）。"""
        state = {"keyElements": [{"id": "ke-1", "title": "Element_艾AA（AA）"}]}
        matched, unmatched = ops.match_element_titles_report(state, ["查无此人"])
        assert matched == [] and unmatched == ["查无此人"]

    def test_find_ref_group_hits_main_name(self):
        """读口命中（生成时取概念图的入口）：裸主名必须能取到组。"""
        state = {"keyElements": [{"id": "ke-1", "title": "Element_艾AA（AA）"}]}
        assert ops.find_ref_group(state, "艾AA")["id"] == "ke-1"
        assert ops.find_ref_group(state, "Element_艾AA（AA）")["id"] == "ke-1"

    def test_merge_shot_refs_binds_alias_without_explicit(self):
        """端到端：模型按文档**留空** shot_refs 时，别名元素也能自动挂上。

        修复前 Shot01 复算只能推出 `[星环号球形舱, 程心]`，艾AA 落空
        （现场靠模型手抄才没丢引用 —— 机制本身是坏的）。"""
        state = {
            "keyElements": [
                {"id": "ke-1", "title": "Element_程心"},
                {"id": "ke-2", "title": "Element_艾AA（AA）"},
                {"id": "ke-3", "title": "Element_星环号球形舱（木星轨道）"},
            ],
            "shots": [],
        }
        desc = ("【空间锚点/星环号球形舱（木星轨道）】\n"
                "人物当前状态：程心（中景偏左）；艾AA（近景偏右，抓扶手）。")
        refs = ops.merge_shot_refs(state, desc, [])
        assert "Element_艾AA（AA）" in refs, "留空 shot_refs 时别名元素未自动绑定"
        assert "Element_程心" in refs
        assert "Element_星环号球形舱（木星轨道）" in refs


# =====================================================================
# ② refAssets 写口归一（草稿 id → 媒体 URL）
# =====================================================================
class TestRefAssetsNormalization:
    """9999 实测：79 条 refAssets **全是** `draft-…` id、合法 URL 0 条。
    前端 `<img src="draft-…">` 被 `safeUrl` 拦成空串 ⇒ 图裂成 alt 文字；
    生成时该串被当 URL 塞进 `reference_images` ⇒ 参考图静默落空。"""

    @pytest.fixture
    def state(self):
        return {
            "keyElements": [
                {"id": "ke-1", "title": "Element_程心",
                 "drafts": [dict(build_draft_dict({"label": "三视图"}, draft_id="d-k1"),
                                 imgUrl="/a/chengxin.png")]},
            ],
            "shots": [
                {"id": "shot-1", "title": "Shot_测试",
                 "drafts": [dict(build_draft_dict({"label": "视频卡"}, draft_id="d-s1"),
                                 videoUrl="")]},
            ],
            "audioItems": [],
        }

    def test_draft_id_resolves_to_media_url(self, state):
        """① 卡已有媒体 ⇒ 落其 URL（本批主路径）。"""
        assert ops.normalize_ref_assets(state, ["d-k1"]) == ["/a/chengxin.png"]

    def test_card_without_media_is_dropped(self, state):
        """② 卡在但还没图 ⇒ 丢弃（不留空占位）。"""
        assert ops.normalize_ref_assets(state, ["d-s1"]) == []

    def test_plain_url_preserved(self, state):
        """③ 合法 URL 原样保留（用户手填素材照常可用，不吞输入）。"""
        assert ops.normalize_ref_assets(state, ["/uploads/a.png"]) == ["/uploads/a.png"]
        assert ops.normalize_ref_assets(state, ["https://x/b.png"]) == ["https://x/b.png"]

    def test_unknown_string_preserved(self, state):
        """未知字符串原样保留（不静默丢用户输入）。"""
        assert ops.normalize_ref_assets(state, ["whatever"]) == ["whatever"]

    def test_dedup_keeps_order(self, state):
        """去重保序留首：同元素经 id 与 URL 两种写法只留一条。"""
        out = ops.normalize_ref_assets(state, ["d-k1", "/a/chengxin.png"])
        assert out == ["/a/chengxin.png"]

    def test_empty_and_bad_inputs(self, state):
        assert ops.normalize_ref_assets(state, []) == []
        assert ops.normalize_ref_assets(state, None) == []
        assert ops.normalize_ref_assets(state, ["", "  "]) == []

    def test_patch_draft_normalizes(self, state):
        """写口覆盖：`ops.patch_draft` 落库即 URL（patch 路径）。"""
        draft = build_draft_dict({"label": "x"}, draft_id="d-t")
        changed, dropped = ops.patch_draft(draft, {"refAssets": ["d-k1"]}, state)
        assert changed is True and dropped == []
        assert draft["refAssets"] == ["/a/chengxin.png"]

    def test_append_draft_normalizes(self, state):
        """写口覆盖：`ops.append_draft` 新建卡即归一（建组附带 / 新增卡路径）。"""
        group = {"id": "g1", "drafts": []}
        draft = ops.append_draft(group, {"label": "x", "refAssets": ["d-k1"]}, state)
        assert draft["refAssets"] == ["/a/chengxin.png"]


# =====================================================================
# ③ resolve_shot_refs 种类判据
# =====================================================================
class TestShotRefsKindPreference:
    """原实现「组内首张有 imgUrl 的卡」隐式依赖卡序；组内先有视频类图卡时取错图。"""

    def test_prefers_image_card_over_video_card(self):
        state = {
            "keyElements": [
                {"id": "ke-1", "title": "Element_程心", "drafts": [
                    # 视频卡在前且带 imgUrl（首帧缩略）——旧实现会取它
                    dict(build_draft_dict({"label": "视频", "mediaType": "video"},
                                          draft_id="d-v"), imgUrl="/a/frame.png"),
                    dict(build_draft_dict({"label": "三视图"}, draft_id="d-i"),
                         imgUrl="/a/sheet.png"),
                ]},
            ],
        }
        shot = {"id": "s1", "shotRefs": ["Element_程心"]}
        refs = ops.resolve_shot_refs(state, shot)
        assert [r["url"] for r in refs] == ["/a/sheet.png"], "未优先取图像类设定图"

    def test_still_works_when_only_one_image(self):
        """既有正确结果不回归：组内只有一张图时照常取。"""
        state = {"keyElements": [
            {"id": "ke-1", "title": "Element_程心",
             "drafts": [dict(build_draft_dict({"label": "三视图"}, draft_id="d-i"),
                             imgUrl="/a/sheet.png")]}]}
        refs = ops.resolve_shot_refs(state, {"id": "s1", "shotRefs": ["Element_程心"]})
        assert [r["url"] for r in refs] == ["/a/sheet.png"]

    def test_alias_ref_reaches_media(self):
        """别名写法也能取到图（与 ① 同一读口）。"""
        state = {"keyElements": [
            {"id": "ke-1", "title": "Element_艾AA（AA）",
             "drafts": [dict(build_draft_dict({"label": "三视图"}, draft_id="d-i"),
                             imgUrl="/a/aa.png")]}]}
        refs = ops.resolve_shot_refs(state, {"id": "s1", "shotRefs": ["艾AA"]})
        assert [r["url"] for r in refs] == ["/a/aa.png"]


# =====================================================================
# ④ 闸机标题覆盖检查（带括注组名的漏检）
# =====================================================================
class TestGateTitleCoverageAlias:
    """闸机用 `strip_type_prefix(组名) in strip_type_prefix(标题)` **单向**比对；
    组名带括注（`艾AA（AA）`）时不是标题（`…艾AA质问…`）的子串 ⇒ 恒不命中，
    漏引不被拦也不回喂。本钉子钉「该判定现在能看见别名主名」。"""

    def _missing(self, title, refs, kes):
        """复刻 fc_gates.structure_integrity_gate 的 missing 判定式。"""
        ref_keys = {ops.strip_type_prefix(str(r)) for r in refs}
        out = []
        for k in kes:
            t = str(k.get("title") or "").strip()
            kid = str(k.get("id") or "")
            short = ops.element_alias_name(t) or ops.strip_type_prefix(t)
            hit = any(n and n in ops.strip_type_prefix(title)
                      for n in (short, ops.strip_type_prefix(t)))
            if t and hit and kid not in refs and ops.strip_type_prefix(t) not in ref_keys \
                    and ops.element_alias_name(t) not in ref_keys:
                out.append(t)
        return out

    def test_alias_element_detected_as_missing(self):
        kes = [{"id": "ke-1", "title": "Element_艾AA（AA）"}]
        title = "全息窗弹出苍老曹彬，艾AA质问木星城为何未躲进掩体"
        assert self._missing(title, [], kes) == ["Element_艾AA（AA）"], \
            "标题点名了艾AA 但未引用，闸机应判定 missing（旧实现恒为空）"

    def test_not_missing_when_referenced_by_alias(self):
        """已按主名引用 ⇒ 不再算漏引（别名也进 ref_keys 比对）。"""
        kes = [{"id": "ke-1", "title": "Element_艾AA（AA）"}]
        title = "艾AA质问木星城"
        assert self._missing(title, ["艾AA"], kes) == []

    def test_not_missing_when_referenced_by_full_title(self):
        kes = [{"id": "ke-1", "title": "Element_艾AA（AA）"}]
        assert self._missing("艾AA质问", ["Element_艾AA（AA）"], kes) == []

    def test_no_false_positive_for_unrelated_element(self):
        """标题未点名 ⇒ 不算漏引（不因放宽形态而误报）。"""
        kes = [{"id": "ke-1", "title": "Element_瓦西里"}]
        assert self._missing("程心与艾AA在舱中初醒", [], kes) == []


# =====================================================================
# ⑤ 提示词媒体映射（`<<<image_名称>>>` / `@名称` 解析）
# =====================================================================
class TestPromptMentionMediaMap:
    """提示词里的引用记号要能查到图：模型写主名（`<<<image_艾AA>>>`）时必须命中。

    修复前映射只登记「完整标题 + 剥前缀」两形态，主名查表落空 ⇒
    `resolve_prompt_mentions` **静默去记号留文字**（不报错不回喂），
    表现为「提示词里写了引用、却没挂上参考图」。"""

    @staticmethod
    def _state():
        return {"keyElements": [
            {"id": "ke-1", "title": "Element_艾AA（AA）", "drafts": [
                dict(build_draft_dict({"label": "三视图"}, draft_id="d-1"),
                     imgUrl="/a/aa.png")]},
            {"id": "ke-2", "title": "Element_程心", "drafts": [
                dict(build_draft_dict({"label": "三视图"}, draft_id="d-2"),
                     imgUrl="/a/cx.png")]},
        ]}

    def test_map_contains_alias_main_name(self):
        from src.video_agent.core.prompt_refs import build_storyboard_media_map
        mm = build_storyboard_media_map(self._state())
        assert mm["艾AA"]["url"] == "/a/aa.png"
        assert mm["艾AA（AA）"]["url"] == "/a/aa.png"
        assert mm["Element_艾AA（AA）"]["url"] == "/a/aa.png"

    def test_mention_resolves_to_real_ref(self):
        """端到端：`<<<image_艾AA>>>` 重写为位置标记并把图纳入参考列表。"""
        from src.video_agent.core.prompt_refs import (
            build_storyboard_media_map, resolve_prompt_mentions,
        )
        mm = build_storyboard_media_map(self._state())
        eff, refs = resolve_prompt_mentions(
            "[角色]: <<<image_艾AA>>> 与 <<<image_程心>>>", [], mm, max_refs=5)
        assert refs == ["/a/aa.png", "/a/cx.png"]
        assert "<<<" not in eff, "记号未解析（静默降级为文字）"
        assert "艾AA" in eff

    def test_at_mention_bracket_form_resolves(self):
        """`@[艾AA]` 写法同命（方括号包络早已容忍，本钉子保形态集齐全）。"""
        from src.video_agent.core.prompt_refs import (
            build_storyboard_media_map, resolve_prompt_mentions,
        )
        mm = build_storyboard_media_map(self._state())
        _eff, refs = resolve_prompt_mentions("@[艾AA] 特写", [], mm, max_refs=5)
        assert refs == ["/a/aa.png"]
