"""9999 项目四问修复回归：
1) 一句话总结正文重复两遍（引号样式不同导致判重失效）；
2) 规格暂停未交互确认三项制作参数（待确认占位值被放行）；
3) 编写关键元素提示词后参数栏没有规格分辨率；
4) 拆分分镜输出预算不足（思考占满额度零产出）——预算调整见 test_skill_runtime。
"""
import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.planner import _prepend_script_summary
from src.video_agent.state.provider_prefs import extract_production_params
from src.video_agent.state.manager import StateManager
from src.video_agent.web.actions import StudioActionExecutor


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


def test_prepend_script_summary_no_dup_when_model_showed_curly():
    tool_results = [{"name": "script_analyze", "ok": True, "data": {"summary": _SUMMARY_STRAIGHT}}]
    visible = f"{_SUMMARY_CURLY}\n\n已读取剧本全文。"
    assert _prepend_script_summary(visible, tool_results) == visible


def test_prepend_script_summary_still_prepends_when_absent():
    tool_results = [{"name": "script_analyze", "ok": True, "data": {"summary": _SUMMARY_STRAIGHT}}]
    out = _prepend_script_summary("已读取剧本全文。", tool_results)
    assert out.startswith(f"**剧本一句话总结**：{_SUMMARY_STRAIGHT}")


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


def test_extract_production_params_skips_unconfirmed_lines():
    params = extract_production_params(_SPEC_UNCONFIRMED)
    assert params["image_resolution"] == ""
    assert params["video_resolution"] == ""
    assert params["shot_max_duration"] is None
    confirmed = extract_production_params(_SPEC_CONFIRMED)
    assert confirmed["image_resolution"] == "2K"
    assert confirmed["video_resolution"] == "1080p"
    assert confirmed["shot_max_duration"] == 8


def test_build_spec_param_options_wizard_groups(monkeypatch):
    # 渠道组由真实 API 配置驱动，单测钉死为空保证确定性（6666 后渠道组恒定 included）
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    msg, opts = prompt_gates.build_spec_param_options(_SPEC_UNCONFIRMED)
    assert msg and opts
    groups = {o["group"] for o in opts}
    # 4444：软维度来自 Skill 客观提取（无 state/skill 时不渲染），
    # 无状态调用只出硬参数三组
    assert groups == {"图片分辨率", "视频分辨率", "分镜最大时长"}
    # 向导渲染门槛：≥5 选项
    assert len(opts) >= 5
    # Seedance 出视频模型 → 分镜最大时长推荐 12 秒
    dur_labels = [o["label"] for o in opts if o["group"] == "分镜最大时长"]
    assert any("12 秒（推荐）" in l for l in dur_labels)


def test_build_spec_param_options_empty_when_confirmed(monkeypatch):
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    assert prompt_gates.build_spec_param_options(_SPEC_CONFIRMED) == ("", [])


def test_spec_pause_card_upgrades_when_unconfirmed(monkeypatch):
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    state = {"documents": [{"name": "制片规格.md", "content": _SPEC_UNCONFIRMED}]}
    msg, opts = prompt_gates.spec_pause_card(state)
    assert opts and "尚待您选定" in msg
    # 全部定稿时回退常规审阅暂停卡
    state2 = {"documents": [{"name": "制片规格.md", "content": _SPEC_CONFIRMED}]}
    msg2, opts2 = prompt_gates.spec_pause_card(state2)
    assert msg2 == prompt_gates.SPEC_DOC_PAUSED_MSG
    assert [o["label"] for o in opts2] == [o["label"] for o in prompt_gates.SPEC_DOC_OPTIONS]


def test_apply_spec_param_selections_wizard_reply(monkeypatch):
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    reply = "图片分辨率：2K（推荐）\n视频分辨率：720p（推荐）\n分镜最大时长：12 秒（推荐）"
    new_content, applied = prompt_gates.apply_spec_param_selections(_SPEC_UNCONFIRMED, reply)
    assert len(applied) == 3
    assert "- 图片分辨率：2K" in new_content
    assert "- 视频分辨率：720p" in new_content
    assert "- 分镜最大时长：12 秒" in new_content
    assert "待确认" not in new_content
    # 定稿后可被正常解析
    params = extract_production_params(new_content)
    assert params["shot_max_duration"] == 12


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
    return StudioActionExecutor(svc)


def _write_spec(svc, content):
    # 替换而非追加：demo 状态自带规格文档会按首个命中抢先
    svc.state_dict["documents"] = [
        {"id": "doc-spec", "name": "制片规格.md", "content": content}
    ]


def test_add_draft_stamps_image_resolution_from_spec(svc, executor):
    _write_spec(svc, _SPEC_CONFIRMED)
    executor.execute([{
        "action": "add_group",
        "group_type": "keyElement",
        "title": "程心",
        "draft": {"label": "概念图", "prompt": "角色概念图提示词……"},
    }])
    draft = svc.state_dict["keyElements"][-1]["drafts"][-1]
    assert draft.get("imageResolution") == "2K"


def test_add_shot_draft_stamps_video_resolution_from_spec(svc, executor):
    _write_spec(svc, _SPEC_CONFIRMED)
    executor.execute([{
        "action": "add_group",
        "group_type": "shot",
        "title": "镜头1",
        "draft": {"label": "分镜视频", "prompt": "镜头提示词…… no subtitles no music"},
    }])
    draft = svc.state_dict["shots"][-1]["drafts"][-1]
    assert draft.get("resolution") == "1080p"


def test_update_draft_stamps_resolution_from_spec(svc, executor):
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
    assert draft.get("imageResolution") in ("", None, "2K")
    executor.execute([{
        "action": "update_draft",
        "draft_id": draft["id"],
        "patch": {"prompt": "补充的提示词正文……"},
    }])
    assert draft.get("imageResolution") == "2K"


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
