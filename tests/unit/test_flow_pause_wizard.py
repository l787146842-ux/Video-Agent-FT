"""1111 项目流程断点修复回归：
1) script_analyze 完成后必须停下交互确认总结，不得直冲规格编写（双轨兜底闸）；
2) 制作参数未选定时，任意来源的暂停卡都并入标准「键：值」候选项向导
   （模型自造 label 如「1K（更快）」无法机械落盘）；
3) 确认意图定稿仅在上一轮暂停确为规格暂停时生效（总结暂停的「确认」
   不得误定稿规格待确认参数）。
"""
import asyncio
import json

import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.state.manager import StateManager
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.web.chat_service import _finalize_spec_params


_SPEC_UNCONFIRMED = (
    "- 视频标题：测试\n"
    "- 图片分辨率：2K（待确认）\n"
    "- 视频分辨率：1080p（待确认）\n"
    "- 分镜最大时长：8 秒（待确认）\n"
)


@pytest.fixture(autouse=True)
def _declare_spec_wizard(monkeypatch):
    """本文件验证规格向导机械本身：给全部用例开启 manifest flow 开关
    （S1：默认关闭，门控行为由 tests/unit/test_skill_manifest.py 覆盖）。"""
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(registry, "skill_flow_enabled", lambda skill, key: True)
    monkeypatch.setattr(registry, "spec_wizard_active", lambda skill: True)


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


# ---------- 向导合并：模型自造选项替换为标准「键：值」格式 ----------

def test_merge_wizard_replaces_model_options_same_group(monkeypatch):
    """6666 二轮：合并只针对 Skill 软维度；硬参数（渠道/分辨率/时长）不再向导化。"""
    monkeypatch.setattr(prompt_gates, "skill_spec_dimensions", lambda skill: ["视觉风格", "画幅"])
    state = {
        "usedSkills": ["测试Skill"],
        "documents": [{"name": "制片规格.md", "content": "- 视觉风格：（待定）\n- 画幅：（待定）"}],
        "interaction": {"spec_soft_candidates": {
            "视觉风格": ["写实", "赛博朋克"],
            "画幅": ["16:9", "2.35:1"],
        }},
    }
    model_opts = [
        {"label": "风格A", "group": "视觉风格", "description": ""},
        {"label": "确认规格并开始拆分关键元素", "group": "下一步", "description": ""},
    ]
    msg, opts, merged = prompt_gates.merge_spec_param_wizard(
        state, "请选定参数", model_opts,
    )
    assert merged
    labels = [o["label"] for o in opts]
    # 自造软维度 label 被标准版替换
    assert "风格A" not in labels
    assert "视觉风格：写实" in labels
    assert "画幅：16:9" in labels
    # 非参数维度选项保留
    assert "确认规格并开始拆分关键元素" in labels
    # 硬参数维度不再并入向导
    assert not any(o.get("group") in ("图片分辨率", "视频分辨率", "分镜最大时长") for o in opts)
    # 向导回传可被软维度解析器机械落盘
    reply = "\n".join(o["label"] for o in opts if o.get("group") in ("视觉风格", "画幅"))
    sels = prompt_gates.parse_dim_selections(reply, ["视觉风格", "画幅"])
    assert sels["视觉风格"].startswith("写实")


def test_merge_wizard_noop_without_spec_doc():
    msg, opts, merged = prompt_gates.merge_spec_param_wizard(
        {"documents": []}, "请确认", [{"label": "继续", "description": ""}],
    )
    assert not merged and msg == "请确认"


def test_merge_wizard_noop_when_params_confirmed(monkeypatch):
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    # 完整规格：硬参数 + 软参数行齐备 → 无待选 → 不合并向导
    state = {"documents": [{"name": "制片规格.md", "content": (
        "- 图片分辨率：2K\n- 视频分辨率：720p\n- 分镜最大时长：12 秒\n"
        "- 视频类型：叙事短片\n- 输出语言：中文\n- 时长：约 60 秒\n"
        "- 画幅：16:9 横屏\n- 叙事驱动：故事驱动\n- 视觉风格：写实\n"
    )}]}
    msg, opts, merged = prompt_gates.merge_spec_param_wizard(state, "请确认", [])
    assert not merged


class _StubToolManager:
    async def invoke_tool(self, name, args):
        from src.video_agent.tools.base import ToolResult
        return ToolResult(success=True, data={})


def test_fc_model_pause_merged_with_wizard(monkeypatch):
    """v2 批4：规格未定稿时规格交互唯一入口 = 系统向导——
    模型选项（软维度/硬参数/工作流类）一律直接拒收，不做模糊清洗。"""
    from src.video_agent.skill_runtime import registry
    monkeypatch.setattr(prompt_gates, "skill_spec_dimensions", lambda skill: ["视觉风格", "画幅"])
    monkeypatch.setattr(registry, "spec_wizard_active", lambda name: True)
    runner = FCToolRunner(tool_manager=_StubToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(
        lambda: {
            "usedSkills": ["测试Skill"],
            "documents": [{"name": "制片规格.md", "content": "- 视觉风格：（待定）\n- 画幅：（待定）"}],
            "interaction": {"spec_soft_candidates": {
                "视觉风格": ["写实", "赛博朋克"],
                "画幅": ["16:9", "2.35:1"],
            }},
        }
    ))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "制片规格.md", "content": "- 视觉风格：（待定）"})}},
        {"id": "c2", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({
                "message": "请选定参数",
                "options": [
                    {"label": "风格A", "group": "视觉风格"},
                    {"label": "1K（更快）", "group": "图片分辨率"},
                    {"label": "确认规格并开始拆分关键元素", "group": "下一步"},
                ],
            })}},
    ])
    applied, confirmation, _urls, _inserts, _log, conf_opts, _results, docs_written, _warnings, _overflow = asyncio.run(
        runner.execute(response, injected_skill="任意 Skill"))
    labels = [o["label"] for o in conf_opts]
    assert "风格A" not in labels
    assert "视觉风格：写实" in labels
    assert "1K（更快）" not in labels, "v2：模型选项直接拒收"
    assert "确认规格并开始拆分关键元素" not in labels, "v2：模型工作流选项拒收"


# ---------- 确认意图定稿的暂停类型门槛 ----------

def test_finalize_confirm_intent_requires_spec_pause_kind(svc):
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": _SPEC_UNCONFIRMED}]
    inter = svc.state_dict.setdefault("interaction", {})
    # 总结暂停的「确认」不得定稿规格参数
    inter["pending_pause_kind"] = "summary"
    note = _finalize_spec_params(svc, "确认总结，开始编写制片规格")
    assert note == ""
    assert "待确认" in svc.state_dict["documents"][0]["content"]
    # 规格暂停的「确认」按展示值定稿
    inter["pending_pause_kind"] = "spec"
    note = _finalize_spec_params(svc, "确认成片规格，开始拆分关键元素")
    assert note and "待确认" not in svc.state_dict["documents"][0]["content"]


def test_finalize_explicit_selection_works_without_kind(svc):
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": _SPEC_UNCONFIRMED}]
    note = _finalize_spec_params(svc, "图片分辨率：4K\n视频分辨率：480p\n分镜最大时长：5 秒")
    assert note
    content = svc.state_dict["documents"][0]["content"]
    assert "- 图片分辨率：4K" in content
    assert "- 视频分辨率：480p" in content
    assert "- 分镜最大时长：5 秒" in content


# ---------- 6666：渠道选择落盘 + spec_collected 防重复向导 ----------

def test_spec_pause_card_consumes_spec_collected_flag():
    """收集向导已交互过：规格写入后的暂停用常规卡，且标记被消费"""
    state = {
        "documents": [{"name": "制片规格.md", "content": _SPEC_UNCONFIRMED}],
        "interaction": {"spec_collected": True},
    }
    msg, opts = prompt_gates.spec_pause_card(state)
    assert msg == prompt_gates.SPEC_DOC_PAUSED_MSG
    assert not state["interaction"].get("spec_collected")


def test_merge_wizard_skipped_when_spec_collected():
    state = {
        "documents": [{"name": "制片规格.md", "content": _SPEC_UNCONFIRMED}],
        "interaction": {"spec_collected": True},
    }
    msg, opts, merged = prompt_gates.merge_spec_param_wizard(state, "模型暂停文案", [])
    assert not merged and msg == "模型暂停文案"


def test_channel_groups_from_providers(monkeypatch):
    from src.video_agent.web import provider_config

    monkeypatch.setattr(provider_config, "load_merged_providers", lambda: [
        {"id": "p1", "name": "即梦", "image_models": ["jm-5.0"], "video_models": []},
        {"id": "p2", "name": "火山引擎", "image_models": [], "video_models": ["seedance-2.0"]},
    ])
    groups = prompt_gates._channel_groups()
    titles = [g["group"] for g in groups]
    assert "出图渠道（API 厂商/模型）" in titles
    assert "出视频渠道（API 厂商/模型）" in titles


def test_apply_spec_channel_selections_routes_by_model_list(monkeypatch):
    from src.video_agent.web import provider_config

    monkeypatch.setattr(provider_config, "load_merged_providers", lambda: [
        {"id": "p1", "name": "即梦", "image_models": ["jm-5.0"], "video_models": ["jm-video"]},
        {"id": "p2", "name": "火山引擎", "image_models": [], "video_models": ["seedance-2.0"]},
    ])
    content = "- 视频标题：测试\n- 图像生成：旧渠道 old-model\n- 视频生成：旧渠道 old-video\n"
    reply = "即梦 / jm-5.0\n火山引擎 / seedance-2.0"
    new_content, applied = provider_config.apply_spec_channel_selections(content, reply)
    assert "- 图像生成：即梦 jm-5.0" in new_content
    assert "- 视频生成：火山引擎 seedance-2.0" in new_content
    assert len(applied) == 2


def test_apply_spec_channel_selections_unknown_provider_noop(monkeypatch):
    from src.video_agent.web import provider_config

    monkeypatch.setattr(provider_config, "load_merged_providers", lambda: [
        {"id": "p1", "name": "即梦", "image_models": ["jm-5.0"], "video_models": []},
    ])
    content = "- 图像生成：旧渠道\n"
    new_content, applied = provider_config.apply_spec_channel_selections(content, "不存在厂商 / xxx")
    assert new_content == content and applied == []


def test_consume_confirmation_sets_spec_collected_for_collect_kind(svc):
    from src.video_agent.web.chat_service import _consume_pending_confirmation

    svc.state_dict.setdefault("interaction", {})["pending_pause_kind"] = "collect"
    _consume_pending_confirmation(svc, "图片分辨率：2K\n视频分辨率：720p")
    inter = svc.state_dict["interaction"]
    assert inter.get("spec_collected") is True
    assert not inter.get("pending_pause_kind")
