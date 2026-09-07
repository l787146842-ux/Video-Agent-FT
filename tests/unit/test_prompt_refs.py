# -*- coding: utf-8 -*-
"""提示词引用解析（prompt_refs）单测：@ 原生记号 + <<<image_名称>>> Flova 方言同义。"""
from src.video_agent.core.prompt_refs import resolve_prompt_mentions

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


def test_flova_notation_hit_same_track_as_at():
    """<<<image_名称>>> 命中：与 @ 同轨——自动纳入参考列表 + 位置标记重写。"""
    prompt = "[场景]: <<<image_星环号球形舱>>> — 冷白灯带。"
    resolved, refs = resolve_prompt_mentions(prompt, [], MEDIA_MAP)
    assert resolved == "[场景]: [参考图1：星环号球形舱] — 冷白灯带。"
    assert refs == ["http://m/2.png"]


def test_flova_notation_unmatched_strips_mark_keeps_text():
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


def test_base_refs_kept_and_flova_hit_reuses_index():
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
