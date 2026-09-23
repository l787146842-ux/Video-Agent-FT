# -*- coding: utf-8 -*-
"""提示词引用解析（prompt_refs）单测：@ 原生记号 + <<<image_名称>>> 外部标杆方言同义。

2026-09-23 批3（Q4/Q6，用户裁决「引用记号必须能工作」）新增三条根因回归：
  R1 方括号被吞 / R2 Skill 模板转义下划线 / R3 写口补前缀而引用链只认前缀。
"""
from src.video_agent.core.prompt_refs import (
    build_storyboard_media_map, resolve_prompt_mentions,
)
from src.video_agent.state.storyboard_ops import parse_element_tokens

MEDIA_MAP = {
    "程心": {"url": "http://m/1.png", "kind": "image"},
    "星环号球形舱": {"url": "http://m/2.png", "kind": "image"},
    "缺失元素": {"url": "http://m/3.png", "kind": "image"},
}


def test_at_mention_hit_appends_and_rewrites():
    prompt = "镜头推进到 @程心 面部特写。"
    resolved, refs = resolve_prompt_mentions(prompt, [], MEDIA_MAP)
    assert resolved == "镜头推进到 [参考图1：程心] 面部特写。"
    assert refs == ["http://m/1.png"]


def test_bracket_notation_hit_same_track_as_at():
    """<<<image_名称>>> 命中：与 @ 同轨——自动纳入参考列表 + 位置标记重写。"""
    prompt = "[场景]: <<<image_星环号球形舱>>> — 冷白灯带。"
    resolved, refs = resolve_prompt_mentions(prompt, [], MEDIA_MAP)
    assert resolved == "[场景]: [参考图1：星环号球形舱] — 冷白灯带。"
    assert refs == ["http://m/2.png"]


def test_bracket_notation_unmatched_strips_mark_keeps_text():
    """<<<image_未登记>>> 未命中：去记号保留名称文字（与 @ 未命中同口径）。"""
    prompt = "引用 <<<image_不存在的人>>> 试探。"
    resolved, refs = resolve_prompt_mentions(prompt, [], MEDIA_MAP)
    assert resolved == "引用 不存在的人 试探。"
    assert refs == []


def test_mixed_notations_share_ref_list():
    """两种记号混用：同一参考列表、序号连续、同名不重复入列。"""
    prompt = "@程心 与 <<<image_程心>>> 同框，背景 <<<image_星环号球形舱>>>。"
    resolved, refs = resolve_prompt_mentions(prompt, [], MEDIA_MAP)
    assert refs == ["http://m/1.png", "http://m/2.png"]
    assert "[参考图1：程心]" in resolved
    assert resolved.count("[参考图1：程心]") == 2, "同名二次引用复用同序号"
    assert "[参考图2：星环号球形舱]" in resolved


def test_base_refs_kept_and_bracket_hit_reuses_index():
    base = ["http://m/1.png"]
    prompt = "<<<image_程心>>> 回眸。"
    resolved, refs = resolve_prompt_mentions(prompt, base, MEDIA_MAP)
    assert refs == base, "base_refs 原顺序保持"
    assert resolved == "[参考图1：程心] 回眸。"


def test_max_refs_overflow_keeps_text():
    prompt = "@程心 @星环号球形舱 @缺失元素"
    resolved, refs = resolve_prompt_mentions(prompt, [], MEDIA_MAP, max_refs=2)
    assert refs == ["http://m/1.png", "http://m/2.png"]
    assert resolved.endswith("缺失元素"), "超限引用仅保留文字"


# ---------- 批3 三条根因回归（2026-09-23） ----------

def test_r1_bracketed_at_mention_not_swallowed():
    """R1：`@[程心]` 的方括号不得被吞进捕获名（原 `[^\\s@＠]+` 会吞）。"""
    resolved, refs = resolve_prompt_mentions("镜头给到 @[程心] 特写。", [], MEDIA_MAP)
    assert refs == ["http://m/1.png"], "带方括号的 @ 引用必须命中"
    assert "[参考图1：程心]" in resolved
    assert "[程心]" not in resolved, "方括号不得残留进正文"


def test_r1_plain_at_mention_still_works():
    """R1 对偶：裸 `@程心` 不受影响。"""
    _, refs = resolve_prompt_mentions("@程心", [], MEDIA_MAP)
    assert refs == ["http://m/1.png"]


def test_r2_escaped_underscore_matches():
    """R2：Skill 模板原文是 `<<<image\\_名称>>>`（Markdown 转义），原正则连匹配都不成立。"""
    resolved, refs = resolve_prompt_mentions("<<<image\\_程心>>>", [], MEDIA_MAP)
    assert refs == ["http://m/1.png"], "转义下划线形态必须命中"
    assert "<<<image\\_程心>>>" not in resolved, "记号应被重写而非原样留存"


def test_r2_real_skill_template_line_parses():
    """R2：Skill 模板整行原样（含 `\\[场景\\]` 占位）必须能解析出引用。"""
    line = "\\[场景\\]: <<<image\\_星环号球形舱>>> — \\[当前光影基调描述\\]"
    resolved, refs = resolve_prompt_mentions(line, [], MEDIA_MAP)
    assert refs == ["http://m/2.png"]
    assert "[参考图1：星环号球形舱]" in resolved


def test_r2_bare_underscore_still_works():
    """R2 对偶：裸 `image_` 形态不受影响（两形态同轨）。"""
    _, refs = resolve_prompt_mentions("<<<image_程心>>>", [], MEDIA_MAP)
    assert refs == ["http://m/1.png"]


def test_r3_bare_name_alias_for_prefixed_group_title():
    """R3：写口补 `Element_` 前缀，而模型写裸名 —— 裸名必须可引用。

    实跑全量 110 次 `<<<image_X>>>` 引用中带前缀者 0 次（命中 0 次），
    根因即映射只注册带前缀标题；本用例钉死裸名别名。
    """
    state = {
        "keyElements": [{
            "id": "ke-1", "title": "Element_程心",
            "drafts": [{"id": "d1", "label": "角色三视图",
                        "mediaType": "image", "imgUrl": "/a/cx.png"}],
        }],
        "shots": [], "audioItems": [],
    }
    m = build_storyboard_media_map(state)
    assert "Element_程心" in m, "前缀名保留（向后兼容）"
    assert "程心" in m, "裸名别名必须注册（模型实际写法）"
    assert m["程心"]["url"] == "/a/cx.png"

    _, refs = resolve_prompt_mentions("<<<image_程心>>>", [], m)
    assert refs == ["/a/cx.png"], "裸名引用必须挂上参考图"
    _, refs2 = resolve_prompt_mentions("<<<image_Element_程心>>>", [], m)
    assert refs2 == ["/a/cx.png"], "带前缀写法仍可用"


def test_escaped_placeholder_not_parsed_as_element_token():
    """批3 附带修复：模板转义占位 `\\[角色描述…\\]` 不得被当元素令牌。

    原实现会把它提取为令牌且末尾粘反斜杠，触发「元素令牌未匹配」误报警告。
    """
    raw = "A character turnaround sheet of \\[角色描述，含年龄/性别/外貌/服装/标志性细节\\]."
    assert parse_element_tokens(raw) == [], "转义占位不是元素引用"
    # 对偶：真实令牌仍正常提取
    assert parse_element_tokens("镜头里出现 [程心] 与 [星环号]") == ["程心", "星环号"]
