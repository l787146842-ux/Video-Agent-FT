"""9999 项目四问修复回归：
1) 一句话总结正文重复两遍（引号样式不同导致判重失效）；
2) 规格暂停未交互确认三项制作参数（待确认占位值被放行）；
3) 编写关键元素提示词后参数栏没有规格分辨率；
4) 拆分分镜输出预算不足（思考占满额度零产出）——预算调整见 test_skill_runtime。
"""
import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.provider_config import stamp_draft_spec_preference
from src.video_agent.state.provider_prefs import extract_production_params
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS


# ---------- 问题1：总结去重 ----------

_SUMMARY_STRAIGHT = '程心一行在木星轨道得知掩体计划失效，"启示"号发现白色小薄片。'
_SUMMARY_CURLY = '程心一行在木星轨道得知掩体计划失效，“启示”号发现白色小薄片。'


def test_summary_already_visible_quote_style_insensitive():
    assert prompt_gates.summary_already_visible(f"正文开头\n{_SUMMARY_CURLY}", _SUMMARY_STRAIGHT)


def test_summary_already_visible_markdown_bold_insensitive():
    visible = f"**剧本一句话总结**：{_SUMMARY_CURLY}"
    assert prompt_gates.summary_already_visible(visible, _SUMMARY_STRAIGHT)


def test_summary_not_visible_when_absent():
    assert not prompt_gates.summary_already_visible("完全无关的正文", _SUMMARY_STRAIGHT)


# ---------- 问题2：规格制作参数待确认兑底 ----------
# spec_unconfirmed_params/build_spec_param_options/spec_pause_card/
# apply_spec_param_selections 相关测试已随用户裁决 2026-08-31 退役删除（D-08 清偿）：
# 规格向导参数收集链整体退役；硬参数唯一来源仍为全局设置（见下方存活用例）。
# （_SPEC_CONFIRMED 常量保留：问题3 补印用例仍用作规格文档夹具。）

_SPEC_CONFIRMED = (
    "- 图片分辨率：2K\n"
    "- 视频分辨率：1080p\n"
    "- 分镜最大时长：8 秒\n"
    "- 视频类型：叙事短片\n"
    "- 输出语言：中文\n"
    "- 时长：约 60 秒\n"
    "- 画幅：16:9 横屏\n"
    "- 叙事驱动：故事驱动\n"
    "- 视觉风格：写实\n"
)


def test_extract_production_params_global_settings_sole_source(set_global_setting):
    """6666 二轮：制作参数唯一来源为顶部全局设置，规格文档行不再参与决策。"""
    set_global_setting("default_image_resolution", "4K")
    set_global_setting("default_video_resolution", "480p")
    set_global_setting("max_shot_duration", 5)
    params = extract_production_params(_SPEC_CONFIRMED)
    assert params == {
        "image_resolution": "4K",
        "video_resolution": "480p",
        "shot_max_duration": 5,
    }


# ---------- 问题3：草稿创建/更新时按全局设置补印分辨率参数栏 ----------
# Q2 裁决 2026-09-01：文本轨退役，补印唯一实现 = provider_config.
# stamp_draft_spec_preference（FC 轨 storyboard_add_draft/patch_draft 同调）。

@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


def _write_spec(svc, content):
    # 替换而非追加：demo 状态自带规格文档会按首个命中抢先（规格内容不再参与补印决策）
    svc.state_dict["documents"] = [
        {"id": "doc-spec", "name": "制片规格.md", "content": content}
    ]


def test_add_draft_stamps_image_resolution_from_global_settings(svc, set_global_setting):
    set_global_setting("default_image_resolution", "4K")
    _write_spec(svc, _SPEC_CONFIRMED)  # 规格文档内容不再参与决策
    draft = {"label": "概念图", "prompt": "角色概念图提示词……"}
    stamp_draft_spec_preference(svc.state_dict, draft, CAT_KEY_ELEMENTS)
    assert draft.get("imageResolution") == "4K"


def test_add_shot_draft_stamps_video_resolution_from_global_settings(svc, set_global_setting):
    set_global_setting("default_video_resolution", "720p")
    _write_spec(svc, _SPEC_CONFIRMED)
    draft = {"label": "分镜视频", "mediaType": "video",
             "prompt": "镜头提示词…… no subtitles no music"}
    stamp_draft_spec_preference(svc.state_dict, draft, CAT_SHOTS)
    assert draft.get("resolution") == "720p"


def test_update_draft_stamps_resolution_from_global_settings(svc, set_global_setting):
    """更新路径同口径：草稿无分辨率时补印全局默认（FC 轨 patch_draft 同调）。"""
    set_global_setting("default_image_resolution", "4K")
    _write_spec(svc, _SPEC_CONFIRMED)
    draft = {"label": "概念图", "prompt": ""}
    assert not draft.get("imageResolution")
    stamp_draft_spec_preference(svc.state_dict, draft, CAT_KEY_ELEMENTS)
    assert draft.get("imageResolution") == "4K"


def test_draft_explicit_resolution_not_overridden(svc, set_global_setting):
    set_global_setting("default_image_resolution", "4K")
    _write_spec(svc, _SPEC_CONFIRMED)
    draft = {"label": "概念图", "prompt": "提示词……", "imageResolution": "1K"}
    stamp_draft_spec_preference(svc.state_dict, draft, CAT_KEY_ELEMENTS)
    assert draft.get("imageResolution") == "1K"  # 草稿自带不覆盖


def test_no_spec_still_stamps_from_global_settings(svc, set_global_setting):
    """6666 二轮口径：补印唯一来源为全局设置，无规格文档也照常补印。"""
    set_global_setting("default_image_resolution", "4K")
    svc.state_dict["documents"] = []  # demo 状态自带规格文档，先清掉
    draft = {"label": "概念图", "prompt": "提示词……"}
    stamp_draft_spec_preference(svc.state_dict, draft, CAT_KEY_ELEMENTS)
    assert draft.get("imageResolution") == "4K"
