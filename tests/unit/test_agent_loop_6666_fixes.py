# -*- coding: utf-8 -*-
"""6666 项目事故回归：确认解析兜底 / 报错可读化 / 过程明细 / 总结强制入正文"""
import pytest

from src.video_agent.web.action_executor import StudioActionExecutor
from src.video_agent.core.agent_loop import run_agent_loop, split_actions
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StudioActionExecutor(svc)


def make_llm(replies):
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return reply[0], reply[1], 0

    return llm_call, calls


# ---------- 确认请求兜底解析（Q3/Q7：笨模型写变体导致确认卡丢失） ----------

def test_split_actions_confirm_alias():
    """action=confirm/pause 等别名也要识别为确认请求"""
    for name in ("confirm", "confirmation", "pause", "workflow_pause", "request_confirmation"):
        executable, cont, confirmation, opts = split_actions(
            [{"action": name, "message": "请审阅", "options": [{"label": "A"}]}]
        )
        assert executable == [] and not cont
        assert confirmation == "请审阅", name
        assert opts == [{"label": "A", "description": ""}]


def test_split_actions_type_key_and_confirm_key():
    """type 键替代 action 键；无动作名但有 confirmation 键也兜底"""
    executable, cont, confirmation, _ = split_actions(
        [{"type": "request_confirmation", "message": "确认下"}]
    )
    assert confirmation == "确认下" and executable == []

    executable, cont, confirmation, _ = split_actions([{"confirmation": "看看结果"}])
    assert confirmation == "看看结果" and executable == []

    executable, cont, confirmation, _ = split_actions([{"request_confirmation": True}])
    assert confirmation and executable == []


async def test_structured_confirmation_stops_loop_with_card(svc, executor):
    """audit-0819b 单轨化：暂停确认经第 5 元组 extra 上抛（原「confirm 文本
    变体解析」随文本块通道退役）——循环照常暂停并带回确认文案"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return ("提示词已写完", "stop", 1,
                0.0, {"confirmation": "请审阅提示词草案", "confirmation_options": []})

    result = await run_agent_loop(
        "写提示词", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.confirmation == "请审阅提示词草案"
    assert calls["n"] == 1
    # 不再误报「操作未匹配到目标」
    assert not any("未执行成功" in w for w in result.warnings)


# ---------- 报错可读化（Q3）：文本轨执行警告随 4-4 退役；FC 轨工具失败
# 经 fc_tool_runner 回喂链可见（test_fc_tool_feedback 覆盖） ----------


# ---------- 过程明细（Q8：重试/读入也进时间线） ----------

async def test_bad_output_retry_recorded_in_trace(svc, executor):
    llm, _ = make_llm([("", "stop"), ("恢复完成", "stop")])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert "恢复完成" in result.text
    summaries = [
        a.get("summary", "")
        for s in result.trace.get("steps", []) for a in s.get("actions", [])
    ]
    assert any("自动重做" in s for s in summaries), summaries


async def test_prelude_notes_recorded_in_first_step(svc, executor):
    llm, _ = make_llm([("好的", "stop")])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
        prelude_notes=[
            ("read_skill", "加载 Skill「剧本生视频」流程规范进上下文"),
            ("read_uploaded_doc", "读取并存档上传文档《太阳系二维化.md》"),
        ],
    )
    steps = result.trace.get("steps", [])
    assert steps and steps[0]["step"] == 1
    summaries = [a.get("summary", "") for a in steps[0].get("actions", [])]
    assert any("剧本生视频" in s for s in summaries)
    assert any("太阳系二维化" in s for s in summaries)


# ---------- 总结展示随 0818 架构板正批退役（平台不再强注入） ----------

async def test_structured_confirmation_options_passthrough(svc, executor):
    """回归（9999 事故改造，audit-0819b）：暂停选项经结构化通道原样带出；
    原「包装 JSON 确认解析」随文本块通道退役（ADR-0001）。"""
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return ("剧本解析完成，请确认制作规格。", "stop", 0, 0.0, {
            "confirmation": "请确认规格",
            "confirmation_options": [
                {"label": "16:9", "description": "横屏", "group": "画幅"},
            ],
        })

    result = await run_agent_loop(
        "开始", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1
    assert result.confirmation == "请确认规格"          # 结构化暂停
    assert result.confirmation_options                    # 选项原样带出
    assert "studio-actions" not in result.text            # 全程无文本块参与
    assert not any("未执行成功" in w for w in result.warnings)
