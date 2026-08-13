# -*- coding: utf-8 -*-
"""6666 项目事故回归：确认解析兜底 / 报错可读化 / 过程明细 / 总结强制入正文"""
import pytest

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.core.agent_loop import run_agent_loop, split_actions
from src.video_agent.core.planner import _prepend_script_summary
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


async def test_confirm_variant_stops_loop_with_card(svc, executor):
    """模型写 confirm 变体时：循环照常暂停并带回确认文案（阶段完成卡不丢）"""
    reply = ('提示词已写完\n```studio-actions\n'
             '[{"action": "confirm", "message": "请审阅提示词草案"}]\n```', "stop")
    llm, calls = make_llm([reply])
    result = await run_agent_loop(
        "写提示词", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.confirmation == "请审阅提示词草案"
    assert calls["n"] == 1
    # 不再误报「操作未匹配到目标」
    assert not any("未执行成功" in w for w in result.warnings)


# ---------- 报错可读化（Q3：指名道姓哪个操作没做成） ----------

async def test_unmatched_warning_names_the_action(svc, executor):
    reply = ('处理中\n```studio-actions\n'
             '[{"action":"update_draft","draft_id":"不存在的卡","patch":{"prompt":"x"}}]\n```', "stop")
    llm, _ = make_llm([reply])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.applied_actions == 0
    warns = [w for w in result.warnings if "未执行成功" in w]
    assert warns, result.warnings
    # 旧猜谜文案必须消失，新文案带上具体操作说明
    assert not any("draft/group 不存在？" in w for w in result.warnings)
    assert "不存在的卡" in warns[0] or "操作" in warns[0]


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


# ---------- 总结强制入正文（Q1：script_analyze 与暂停同批时总结不丢） ----------

def test_prepend_script_summary_when_missing():
    results = [{"name": "script_analyze", "ok": True,
                "data": {"summary": "人类文明被二向箔二维化的悲歌"}}]
    out = _prepend_script_summary("正在为您解析故事核心。", results)
    assert out.startswith("**剧本一句话总结**：人类文明被二向箔二维化的悲歌")
    assert "正在为您解析故事核心。" in out


def test_prepend_script_summary_no_duplicate():
    results = [{"name": "script_analyze", "ok": True, "data": {"summary": "总结A"}}]
    visible = "总结A 已展示在开头"
    assert _prepend_script_summary(visible, results) == visible


def test_prepend_script_summary_no_result():
    assert _prepend_script_summary("正文", []) == "正文"
    assert _prepend_script_summary(
        "正文", [{"name": "script_analyze", "ok": False, "data": {"summary": "X"}}]
    ) == "正文"


async def test_wrapped_json_confirmation_recognized(svc, executor):
    """回归（9999 事故）：模型把确认写进 {"studio-actions": [...]} 包装
    （```json 围栏 + name 键变体）也要识别为阶段暂停，且 JSON 不漏进正文。"""
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    reply = (
        '剧本解析完成，请确认制作规格。\n```json\n'
        '{"studio-actions": [{"name": "request_confirmation", '
        '"message": "请确认规格", "options": ['
        '{"label": "16:9", "description": "横屏", "group": "画幅"}]}]}\n```\n',
        "stop",
    )
    llm, calls = make_llm([reply])
    result = await run_agent_loop(
        "开始", llm_call=llm, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1
    assert result.confirmation == "请确认规格"          # 包装格式也识别为暂停
    assert result.confirmation_options                    # 选项正常带出
    assert "studio-actions" not in result.text            # JSON 不泄漏进正文
    assert not any("未执行成功" in w for w in result.warnings)
