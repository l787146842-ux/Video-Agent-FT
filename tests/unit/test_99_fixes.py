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
from src.video_agent.core.action_executor import StateOperationExecutor


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

