# -*- coding: utf-8 -*-
"""99 项目事故回归：制片规格文档写完后——
1) 正文不再重复拼剧本总结（总结属于解析阶段，只在解析阶段的暂停补）；
2) 不再重复弹出制片规格收集向导（渠道下拉组）：spec_collected 标记被
   spec_pause_card 消费后，同批 merge_spec_param_wizard 双重消费导致向导
   复弹——直接出「确认成片规格/调整成片规格」的下一步引导卡。
"""
import asyncio
import json

import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.state.manager import StateManager
from src.video_agent.web.action_executor import StudioActionExecutor


_SPEC_CONFIRMED = (
    "- 视频标题：测试\n"
    "- 画幅：16:9\n"
    "- 图片分辨率：2K\n"
    "- 视频分辨率：720p\n"
    "- 分镜最大时长：15 秒\n"
)

_CHANNEL_OPTS = [
    {"label": "出图渠道：下拉选择厂商+模型", "description": "", "group": "出图渠道（API 厂商/模型）"},
    {"label": "出视频渠道：下拉选择厂商+模型", "description": "", "group": "出视频渠道（API 厂商/模型）"},
]


@pytest.fixture(autouse=True)
def _declare_spec_wizard(monkeypatch):
    """本文件验证规格审阅卡/向导合并机械本身：开启 manifest flow 开关
    （S1：默认关闭，门控行为由 tests/unit/test_skill_manifest.py 覆盖）。"""
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(registry, "skill_flow_enabled", lambda skill, key: True)
    monkeypatch.setattr(registry, "spec_wizard_active", lambda skill: True)


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


def make_llm(replies):
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return reply[0], reply[1], 0

    return llm_call, calls


class _StubToolManager:
    async def invoke_tool(self, name, args):
        from src.video_agent.tools.base import ToolResult
        return ToolResult(success=True, data={})


# ---------- 问题2回归：规格写完后不再重复弹制片规格交互（双轨） ----------

def test_99_fc_spec_review_card_not_remerged_with_wizard(monkeypatch):
    """FC 轨复现：收集向导已交互过（spec_collected=True），模型写规格未自发
    暂停 → spec_pause_card 出常规审阅卡；同批 merge 不得因标记被双重消费
    而把渠道向导再并进来（99 项目实际故障路径）。"""
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: list(_CHANNEL_OPTS))
    state = {
        "documents": [{"name": "制片规格.md", "content": _SPEC_CONFIRMED}],
        "interaction": {"spec_collected": True},
    }
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: state))
    runner = FCToolRunner(tool_manager=_StubToolManager())
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "制片规格.md", "content": _SPEC_CONFIRMED})}},
    ])
    _applied, confirmation, _urls, _inserts, _log, conf_opts, _results, _docs, _warnings = asyncio.run(
        runner.execute(response, injected_skill="任意 Skill"))
    # 审阅卡（中性选项，0817 B22）而不是收集向导
    assert confirmation == prompt_gates.SPEC_DOC_PAUSED_MSG
    labels = [o["label"] for o in conf_opts]
    assert "确认成片规格，按流程继续" in labels
    assert "调整成片规格" in labels
    groups = {o.get("group") for o in conf_opts}
    assert "出图渠道（API 厂商/模型）" not in groups
    assert "出视频渠道（API 厂商/模型）" not in groups
    # 标记被消费一次即清
    assert not state["interaction"].get("spec_collected")


async def test_99_text_spec_review_card_not_remerged_with_wizard(svc, monkeypatch):
    """4444 方案乙：系统拼装落盘置 spec_review_pending → 轮末注入审阅卡；
    spec_collected 已消费 → 不再重复合并向导。"""
    from src.video_agent.web import skill_docs as sd

    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: list(_CHANNEL_OPTS))
    sd.save_skill_doc(
        "测试流程Skill",
        "# T\n> 调用规则：测试\n将全局制作参数写入 Final_Video_Spec.md"
        "（画幅比例、目标时长）→ text_editor\n",
    )
    svc.state_dict["usedSkills"] = ["测试流程Skill"]
    inter = svc.state_dict.setdefault("interaction", {})
    inter["spec_collected"] = True
    inter["spec_review_pending"] = True
    ex = StudioActionExecutor(svc, gate_enabled=True)
    ex.skill_name = "测试流程Skill"
    r1 = ("规格已生成，请审阅。", "stop")
    llm, calls = make_llm([r1])
    result = await run_agent_loop(
        "确认规格", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 1
    assert result.confirmation == prompt_gates.SPEC_DOC_PAUSED_MSG
    labels = [o["label"] for o in result.confirmation_options]
    assert labels == [o["label"] for o in prompt_gates.spec_review_options(svc.state_dict)]
    groups = {o.get("group") for o in result.confirmation_options}
    assert "出图渠道（API 厂商/模型）" not in groups


async def test_99_model_spec_write_rejected_when_wizard_active(svc, monkeypatch):
    """4444 方案乙钉死：规格流程启用的 Skill，模型手写规格文档被拒收
    （规格由系统拼装），状态里不出现规格文档。"""
    from src.video_agent.web import skill_docs as sd

    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: list(_CHANNEL_OPTS))
    sd.save_skill_doc(
        "测试流程Skill",
        "# T\n> 调用规则：测试\n将全局制作参数写入 Final_Video_Spec.md"
        "（画幅比例、目标时长）→ text_editor\n",
    )
    svc.state_dict["usedSkills"] = ["测试流程Skill"]
    svc.state_dict["documents"] = []
    ex = StudioActionExecutor(svc, gate_enabled=True)
    ex.skill_name = "测试流程Skill"
    r1 = ('规格已保存。\n```studio-actions\n'
          '[{"action":"write_document","name":"制片规格.md","content":"画幅：16:9"}]\n```', "stop")
    llm, _ = make_llm([r1])
    result = await run_agent_loop(
        "写规格", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert not any(
        prompt_gates.is_spec_doc_name(str(d.get("name") or ""))
        for d in svc.state_dict.get("documents", [])
    )


# ---------- 问题1回归：规格写完后的暂停不再重复展示剧本总结 ----------

async def test_99_summary_not_prepended_on_spec_review_pause(svc):
    """规格审阅暂停（pause_kind=spec）正文不带总结时也不补：总结只属于解析阶段
    （audit-0819b：确认经结构化 extra 上抛，原 request_confirmation 文本块退役）"""
    svc.state_dict["analysis"] = {"summary": "太阳系逐渐二维化"}
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": _SPEC_CONFIRMED}]
    svc.state_dict.setdefault("interaction", {})["pending_pause_kind"] = "spec"
    ex = StudioActionExecutor(svc, gate_enabled=False)

    async def llm(system_prompt, messages, stream_hook=None):
        return ("请审阅规格条目。", "stop", 0, 0.0,
                {"confirmation": "请确认规格", "confirmation_options": []})

    result = await run_agent_loop(
        "开始", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert result.confirmation == "请确认规格"
    assert "剧本一句话总结" not in result.text
    assert "太阳系逐渐二维化" not in result.text


async def test_99_model_loop_no_summary_injection(svc):
    """0818 架构板正批：模型循环不再强注入总结/收集卡（顺序与收集归编排器）。"""
    svc.state_dict["analysis"] = {"summary": "太阳系逐渐二维化"}
    svc.state_dict["documents"] = []
    ex = StudioActionExecutor(svc, gate_enabled=True)
    ex.skill_name = "测试流程Skill"

    async def llm(system_prompt, messages, stream_hook=None):
        return ("解析完成。", "stop", 0)

    result = await run_agent_loop(
        "开始", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert "一句话故事总结" not in (result.confirmation or "")
    assert not result.text.startswith("**剧本一句话总结**")
