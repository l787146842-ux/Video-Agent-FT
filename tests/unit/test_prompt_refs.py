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


# ---------- 2026-10-16 音色抢名批（用户裁决「先写引用、音频出来自动解析」配套） ----------
# 病灶：音色卡（mediaType=audio）与角色设定图同住一个 keyElement 组，而组标题
# 只登记「该组第一张有媒体的卡」——音色卡排在前面时（9999 实测「音色·程心」在
# 「设定图·程心」之前）音频抢走组标题 ⇒ `@程心` 解析成**参考音频**而非角色图。
# 实测：给音色卡挂上 audioUrl 后，`@程心` 变成「[参考音频1：程心]」，角色图丢失。
# 后果：音频一旦落地，全篇 `@角色名` 集体从「角色的脸」变成「角色的声音」。
# 本组钉死「音频不抢组标题」+「纯音色卡组仍可引用」两侧边界。

def _ke_group_with_voice_first(img_url: str = "/a/cx.png",
                               audio_url: str = "/a/cx.mp3") -> dict:
    """程心组：**音色卡在设定图之前**（9999 实测顺序），两者都有媒体。"""
    return {
        "keyElements": [{
            "id": "ke-1", "title": "Element_程心",
            "drafts": [
                {"id": "d1", "label": "音色·程心", "mediaType": "audio",
                 "audioType": "voice", "audioUrl": audio_url},
                {"id": "d2", "label": "设定图·程心", "mediaType": "image",
                 "imgUrl": img_url},
            ],
        }],
        "shots": [], "audioItems": [],
    }


def test_voice_card_does_not_steal_group_title_for_image():
    """核心回归：组标题（含裸名）必须指向**角色设定图**，不被音色卡抢走。"""
    m = build_storyboard_media_map(_ke_group_with_voice_first())
    assert m["程心"]["kind"] == "image", "组标题是「角色的脸」，不得为音频"
    assert m["程心"]["url"] == "/a/cx.png"
    assert m["Element_程心"]["kind"] == "image"

    resolved, refs = resolve_prompt_mentions("[角色]: @程心 —— 站在舱内", [], m)
    assert refs == ["/a/cx.png"], "角色图必须被挂上（探测：音频是否抢名）"
    assert "[参考图1：程心]" in resolved


def test_voice_card_still_reachable_by_its_label():
    """对偶：音色卡自身仍可用 label（`音色·程心`）引用到音频。"""
    m = build_storyboard_media_map(_ke_group_with_voice_first())
    assert m["音色·程心"]["kind"] == "audio"
    resolved, refs = resolve_prompt_mentions(
        '[台词]: {程心说: "打击来了？"} @音色·程心', [], m)
    assert refs == ["/a/cx.mp3"]
    assert "[参考音频1：音色·程心]" in resolved


def test_voice_only_group_still_reachable_by_title():
    """边界（防静默降级）：组内**只有音色卡**没有图时，组标题兜底给音频。

    若「音频一律不登记组标题」而不留这条兜底，「只有音色卡」的元素
    （4444 实测形状）会让 `@AA` 变成未命中 ⇒ **静默去记号留文字**
    （不报错、不回喂），即 9999 同一失效类。
    """
    state = {
        "keyElements": [{
            "id": "ke-1", "title": "Element_AA",
            "drafts": [{"id": "d1", "label": "音色·AA", "mediaType": "audio",
                        "audioType": "voice", "audioUrl": "/a/aa.mp3"}],
        }],
        "shots": [], "audioItems": [],
    }
    m = build_storyboard_media_map(state)
    assert m["AA"]["kind"] == "audio", "纯音色卡组：组标题兜底给音频（不静默落空）"
    _, refs = resolve_prompt_mentions("@AA", [], m)
    assert refs == ["/a/aa.mp3"]


def test_image_not_yet_generated_still_reserves_title_for_audio_card():
    """边界（防时间窗复发）：设定图**尚未出图**（无 imgUrl）时，
    组标题仍不得让给音色卡——判据是「组内有视觉**卡**」，与出图进度无关。

    若按「有无 imgUrl」判定，「图未生成」期间就会把标题让给音频 ⇒
    原故障按时间窗复发（本批必须堵住的形状）。
    """
    state = _ke_group_with_voice_first()
    # 抹掉设定图的 URL，模拟「卡在、图还没出」
    state["keyElements"][0]["drafts"][1]["imgUrl"] = ""
    m = build_storyboard_media_map(state)
    assert "程心" not in m, "图未出：组标题暂不登记（不得落到音频上）"
    assert m["音色·程心"]["kind"] == "audio", "音色卡仍按 label 可达"


def test_escaped_placeholder_not_parsed_as_element_token():
    """批3 附带修复：模板转义占位 `\\[角色描述…\\]` 不得被当元素令牌。

    原实现会把它提取为令牌且末尾粘反斜杠，触发「元素令牌未匹配」误报警告。
    """
    raw = "A character turnaround sheet of \\[角色描述，含年龄/性别/外貌/服装/标志性细节\\]."
    assert parse_element_tokens(raw) == [], "转义占位不是元素引用"
    # 对偶：真实令牌仍正常提取
    assert parse_element_tokens("镜头里出现 [程心] 与 [星环号]") == ["程心", "星环号"]


# ---------- 正文内联引用批（2026-10-06，事故 9999 / 用户裁决 A） ----------
# 病灶：名称捕获字符集 `[^\s@＠\[\]]+` 排除面太窄 ⇒ 中文标点被吞进名称，
# 查表落空、**静默去记号留文字**（不报错不回喂）。实测 13 类常见后接字符里
# 只有空白/换行能解析，`@程心，` / `@程心。` / `@程心）` / `@程心说` 全失败——
# 而中文正文里标点紧跟才是常态。本组钉死修复且防回潮。

def test_at_mention_survives_following_cjk_punctuation():
    """中文标点紧跟 @名称 不得被吞进名称（修复前：查表落空、记号静默消失）。"""
    for tail in ("。", "，", "、", "：", "；", "！", "？", ")", "）", "/", "|"):
        resolved, refs = resolve_prompt_mentions(f"看向 @程心{tail}", [], MEDIA_MAP)
        assert refs == ["http://m/1.png"], (
            f"@程心{tail} 未挂上参考图——标点被吞进名称（2026-10-06 事故 9999 复发）")
        assert "[参考图1：程心]" in resolved, f"@程心{tail} 未就地重写"
        assert tail in resolved, f"尾部标点 {tail!r} 被吞掉了（必须原样保留）"


def test_at_mention_survives_trailing_prose_without_space():
    """中文连写（无空格）也要命中：`看向@程心说` → 名称切在「说」之前。"""
    resolved, refs = resolve_prompt_mentions("看向@程心说", [], MEDIA_MAP)
    assert refs == ["http://m/1.png"], "无空格连写时 @名称 应仍被识别"
    assert "[参考图1：程心]说" in resolved
    assert "说" in resolved, "名称之后的正文不得丢失"


def test_at_mention_longest_match_prefers_full_name_with_punctuation():
    """对偶：**名字本身带标点**时必须整名命中，不得被截短。

    防止为实现上一条而把名称切得过狠（如 `艾AA（AA）` 被切成 `艾AA` 查不到）。
    """
    m = {
        "艾AA（AA）": {"url": "http://m/aa.png", "kind": "image"},
        "艾AA": {"url": "http://m/aa2.png", "kind": "image"},
    }
    resolved, refs = resolve_prompt_mentions("特写 @艾AA（AA）。", [], m)
    assert refs == ["http://m/aa.png"], "带括注的全名应整名命中（最长优先）"
    assert "[参考图1：艾AA（AA）]" in resolved
    assert resolved.endswith("。"), "句末标点保留"


def test_at_mention_unmatched_still_strips_mark_keeps_text():
    """未命中语义不变：去记号、留文字（含尾部标点），不报错。"""
    resolved, refs = resolve_prompt_mentions("参考 @不存在的人，继续。", [], MEDIA_MAP)
    assert refs == []
    assert resolved == "参考 不存在的人，继续。", "未命中不得吞掉标点或正文"


def test_at_mention_inline_marker_sits_where_element_is_mentioned():
    """**A 方案的目标形态钉**：位置标记必须**就地**出现在元素提及处。

    这是与「尾部罗列图片清单」的本质区别（9999 现场：图发出去了，但第 N 张图
    对应谁的信息全挤在文末，与画面对不上号）。
    """
    prompt = ("Panel 1: 全景，@程心 与 @AA 飘出；"
              "Panel 2: 近景，@程心 侧脸。")
    mm = dict(MEDIA_MAP)
    mm["AA"] = {"url": "http://m/aa.png", "kind": "image"}
    resolved, refs = resolve_prompt_mentions(prompt, [], mm)
    assert refs == ["http://m/1.png", "http://m/aa.png"]
    # 标记就地：在 Panel 1 / Panel 2 各自的分句内，而不是被挪到文末
    p1, p2 = resolved.split("Panel 2:")
    assert "程心" in p1 and "[参考图" in p1, "Panel 1 内应就地出现标记"
    assert "[参考图1：程心]" in p2, "Panel 2 复用同序号且就地"
    assert not resolved.rstrip().endswith("]"), "标记不得被集中挪到文末"


def test_bracket_notation_single_group_unchanged():
    """防回潮：`<<<image_名称>>>` 有闭合定界符，行为与修复前逐字一致。"""
    resolved, refs = resolve_prompt_mentions("<<<image_程心>>>。", [], MEDIA_MAP)
    assert refs == ["http://m/1.png"]
    assert resolved == "[参考图1：程心]。"


# ---------- 2026-10-19 音色引用批（用户裁决「图与音频各算各的」） ----------
# 病灶（9999 实测 S2）：合并列表 = 4 张图 + 1 条音色，音色排总列表第 5 位 ⇒
# 正文写成 `[参考音频5：音色·程心]`；而发送时按类型分桶（out_audios 只有 1 条）
# ⇒ 模型收到 1 条音频，文本却说「第 5 条」，对不上号。
# 修法：标记序号按**素材类型**独立编号。图片侧口径保持不变。

def _map_with_images_then_voice() -> dict:
    """4 张角色图 + 1 条音色（9999/S2 现场形状：图在前、音色在后）。"""
    return {
        "程心": {"url": "/a/cx.png", "kind": "image"},
        "AA": {"url": "/a/aa.png", "kind": "image"},
        "曹彬": {"url": "/a/cb.png", "kind": "image"},
        "星环号球形舱": {"url": "/a/scene.png", "kind": "image"},
        "音色·程心": {"url": "/a/cx.mp3", "kind": "audio"},
    }


def test_audio_marker_numbered_within_audio_bucket():
    """音频标记用**音频桶内**序号（第 1 条），不是总列表第 5 位。"""
    m = _map_with_images_then_voice()
    base = ["/a/cx.png", "/a/aa.png", "/a/cb.png", "/a/scene.png"]
    resolved, refs = resolve_prompt_mentions(
        "【台词】{程心说：“打击来了？”} @音色·程心", base, m, max_refs=50)
    assert refs == base + ["/a/cx.mp3"]
    assert "[参考音频1：音色·程心]" in resolved, "音频序号必须是音频桶内的 1，不是总列表的 5"
    assert "参考音频5" not in resolved


def test_image_marker_numbering_unchanged_by_audio_rule():
    """对照：图片序号仍是图片桶内序号（本次改动不得动既有图片口径）。"""
    m = _map_with_images_then_voice()
    resolved, refs = resolve_prompt_mentions("@AA 与 @音色·程心", [], m, max_refs=50)
    assert refs == ["/a/aa.png", "/a/cx.mp3"]
    assert "[参考图1：AA]" in resolved, "图片侧从 1 起算（不受音频影响）"
    assert "[参考音频1：音色·程心]" in resolved


def test_multiple_audio_markers_numbered_sequentially_in_audio_bucket():
    """多条音色：音频桶内 1、2、3 连续；中间夹的图片不占音频序号。"""
    m = _map_with_images_then_voice()
    m["音色·AA"] = {"url": "/a/aa.mp3", "kind": "audio"}
    m["音色·曹彬"] = {"url": "/a/cb.mp3", "kind": "audio"}
    prompt = ("{AA说：“为什么…”} @音色·AA {程心说：“打击来了？”} @音色·程心 "
              "{曹彬说：“已经确认。”} @音色·曹彬")
    resolved, _refs = resolve_prompt_mentions(prompt, ["/a/scene.png"], m, max_refs=50)
    assert "[参考音频1：音色·AA]" in resolved
    assert "[参考音频2：音色·程心]" in resolved
    assert "[参考音频3：音色·曹彬]" in resolved
    assert resolved.count("[参考图") == 0, "本组无图片引用，不得凭空产生参考图标记"

