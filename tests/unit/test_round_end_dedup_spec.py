"""9999 项目四问修复回归：
1) 一句话总结正文重复两遍（引号样式不同导致判重失效）；
2) 规格暂停未交互确认三项制作参数（待确认占位值被放行）；
3) 编写关键元素提示词后参数栏没有规格分辨率；
4) 拆分分镜输出预算不足（思考占满额度零产出）——预算调整见 test_skill_runtime。
"""
import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.state.provider_prefs import extract_production_params
from src.video_agent.state.manager import StateManager
from src.video_agent.core.action_executor import StateOperationExecutor


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


# ---------- 问题2：规格制作参数待确认兜底 ----------

_SPEC_UNCONFIRMED = (
    "- 视频标题：三体·薄膜\n"
    "- 画幅：16:9\n"
    "- 视频生成：火山引擎 doubao-seedance-2-0-260128\n"
    "- 图片分辨率：2K（待确认）\n"
    "- 视频分辨率：1080p（待确认）\n"
    "- 分镜最大时长：8 秒/镜头（待确认）\n"
)

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


def test_unconfirmed_params_detected():
    assert set(prompt_gates.spec_unconfirmed_params(_SPEC_UNCONFIRMED)) == {
        "图片分辨率", "视频分辨率", "分镜最大时长",
    }
    assert prompt_gates.spec_unconfirmed_params(_SPEC_CONFIRMED) == []


def test_unconfirmed_params_missing_lines():
    assert set(prompt_gates.spec_unconfirmed_params("- 画幅：16:9")) == {
        "图片分辨率", "视频分辨率", "分镜最大时长",
    }


def test_extract_production_params_global_settings_sole_source(set_global_setting):
    """6666 二轮：制作参数唯一来源为顶部全局设置，规格文档行不再参与决策。"""
    set_global_setting("default_image_resolution", "4K")
    set_global_setting("default_video_resolution", "480p")
    set_global_setting("max_shot_duration", 5)
    params = extract_production_params(_SPEC_UNCONFIRMED)
    assert params == {
        "image_resolution": "4K",
        "video_resolution": "480p",
        "shot_max_duration": 5,
    }


def test_build_spec_param_options_no_hard_params_without_skill(monkeypatch):
    """6666 二轮：无 Skill 软维度时向导为空，硬参数组不再兜底出现。"""
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    msg, opts = prompt_gates.build_spec_param_options(_SPEC_UNCONFIRMED)
    assert msg == "" and opts == []


def test_build_spec_param_options_empty_when_confirmed(monkeypatch):
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    assert prompt_gates.build_spec_param_options(_SPEC_CONFIRMED) == ("", [])


def test_spec_pause_card_uses_review_card_when_no_skill_dims(monkeypatch):
    """6666 二轮：规格文档硬参数行不再触发候选项向导（全局设置唯一来源）；
    8888 二轮：审阅选项客观具体。"""
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    state = {"documents": [{"name": "制片规格.md", "content": _SPEC_UNCONFIRMED}]}
    msg, opts = prompt_gates.spec_pause_card(state)
    assert msg == prompt_gates.SPEC_DOC_PAUSED_MSG
    assert [o["label"] for o in opts] == [o["label"] for o in prompt_gates.spec_review_options(state)]


def test_apply_spec_param_selections_wizard_reply(monkeypatch):
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    reply = "图片分辨率：2K（推荐）\n视频分辨率：720p（推荐）\n分镜最大时长：12 秒（推荐）"
    new_content, applied = prompt_gates.apply_spec_param_selections(_SPEC_UNCONFIRMED, reply)
    assert len(applied) == 3
    assert "- 图片分辨率：2K" in new_content
    assert "- 视频分辨率：720p" in new_content
    assert "- 分镜最大时长：12 秒" in new_content
    assert "待确认" not in new_content
    # 制作参数唯一来源为全局设置（extract 不再解析规格文档行）
    from src.video_agent.config import settings

    params = extract_production_params(new_content)
    assert params["shot_max_duration"] == settings.max_shot_duration


def test_apply_spec_param_selections_confirm_intent_keeps_displayed_values():
    new_content, applied = prompt_gates.apply_spec_param_selections(
        _SPEC_UNCONFIRMED, "确认成片规格，开始拆分关键元素"
    )
    assert len(applied) == 3
    assert "- 图片分辨率：2K" in new_content
    assert "- 视频分辨率：1080p" in new_content
    assert "- 分镜最大时长：8 秒" in new_content.replace("/镜头", "")
    assert "待确认" not in new_content


def test_apply_spec_param_selections_adjust_leaves_untouched():
    new_content, applied = prompt_gates.apply_spec_param_selections(
        _SPEC_UNCONFIRMED, "视觉风格改成赛博朋克"
    )
    assert applied == []
    assert new_content == _SPEC_UNCONFIRMED


# ---------- 问题3：草稿创建时按规格补印分辨率参数栏 ----------

@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


def _write_spec(svc, content):
    # 替换而非追加：demo 状态自带规格文档会按首个命中抢先
    svc.state_dict["documents"] = [
        {"id": "doc-spec", "name": "制片规格.md", "content": content}
    ]


def test_add_draft_stamps_image_resolution_from_global_settings(svc, executor, set_global_setting):
    set_global_setting("default_image_resolution", "4K")
    _write_spec(svc, _SPEC_CONFIRMED)  # 规格文档内容不再参与决策
    executor.execute([{
        "action": "add_group",
        "group_type": "keyElement",
        "title": "程心",
        "draft": {"label": "概念图", "prompt": "角色概念图提示词……"},
    }])
    draft = svc.state_dict["keyElements"][-1]["drafts"][-1]
    assert draft.get("imageResolution") == "4K"


def test_add_shot_draft_stamps_video_resolution_from_global_settings(svc, executor, set_global_setting):
    set_global_setting("default_video_resolution", "720p")
    _write_spec(svc, _SPEC_CONFIRMED)
    executor.execute([{
        "action": "add_group",
        "group_type": "shot",
        "title": "镜头1",
        "draft": {"label": "分镜视频", "prompt": "镜头提示词…… no subtitles no music"},
    }])
    draft = svc.state_dict["shots"][-1]["drafts"][-1]
    assert draft.get("resolution") == "720p"


def test_update_draft_stamps_resolution_from_global_settings(svc, executor, set_global_setting):
    set_global_setting("default_image_resolution", "4K")
    _write_spec(svc, _SPEC_CONFIRMED)
    executor.execute([{
        "action": "add_group",
        "group_type": "keyElement",
        "title": "AA",
    }])
    group = svc.state_dict["keyElements"][-1]
    executor.execute([{
        "action": "add_draft",
        "group_id": group["id"],
        "draft": {"label": "概念图", "prompt": ""},
    }])
    draft = group["drafts"][-1]
    assert draft.get("imageResolution") in ("", None, "4K")
    executor.execute([{
        "action": "update_draft",
        "draft_id": draft["id"],
        "patch": {"prompt": "补充的提示词正文……"},
    }])
    assert draft.get("imageResolution") == "4K"


def test_draft_explicit_resolution_not_overridden(svc, executor):
    _write_spec(svc, _SPEC_CONFIRMED)
    executor.execute([{
        "action": "add_group",
        "group_type": "keyElement",
        "title": "白Ice",
        "draft": {"label": "概念图", "prompt": "提示词……", "imageResolution": "4K"},
    }])
    draft = svc.state_dict["keyElements"][-1]["drafts"][-1]
    assert draft.get("imageResolution") == "4K"


def test_no_spec_no_stamp(svc, executor):
    svc.state_dict["documents"] = []  # demo 状态自带规格文档，先清掉
    executor.execute([{
        "action": "add_group",
        "group_type": "keyElement",
        "title": "无规格元素",
        "draft": {"label": "概念图", "prompt": "提示词……"},
    }])
    draft = svc.state_dict["keyElements"][-1]["drafts"][-1]
    # 无规格时保持工厂默认值，不补印
    assert draft.get("imageResolution") == "1K"
