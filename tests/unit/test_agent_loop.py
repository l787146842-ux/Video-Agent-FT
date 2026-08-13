"""run_agent_loop：多步 continue 协议、截断告警、上限终止"""
import pytest

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core import prompt_gates
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StudioActionExecutor(svc)


def make_llm(replies):
    """按次序返回预设回复的假 LLM；记录每轮收到的 system prompt"""
    calls = {"n": 0, "systems": []}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["systems"].append(system_prompt)
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        # 返回 3 元组 (content, finish_reason, fc_applied)
        return reply[0], reply[1], 0

    return llm_call, calls


async def test_single_step_no_continue(svc, executor):
    reply = ('创建完成\n```studio-actions\n'
             '[{"action":"add_group","group_type":"shot","title":"分镜A","draft":{"label":"d","prompt":"p"}}]\n```', "stop")
    llm, calls = make_llm([reply])
    result = await run_agent_loop(
        "拆解", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.steps == 1
    assert result.applied_actions == 1
    assert calls["n"] == 1
    assert "创建完成" in result.text


async def test_continue_triggers_second_round(svc, executor):
    r1 = ('第一轮\n```studio-actions\n'
          '[{"action":"add_group","group_type":"shot","title":"S1","draft":{"label":"d","prompt":"p"}},'
          '{"action":"continue","reason":"继续补充"}]\n```', "stop")
    r2 = ('第二轮完成\n```studio-actions\n'
          '[{"action":"add_group","group_type":"shot","title":"S2","draft":{"label":"d","prompt":"p"}}]\n```', "stop")
    llm, calls = make_llm([r1, r2])
    result = await run_agent_loop(
        "拆解全部", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.steps == 2
    assert result.applied_actions == 2  # continue 本身不计数
    assert calls["n"] == 2
    titles = [g["title"] for g in svc.state_dict["shots"]]
    assert "S1" in titles and "S2" in titles


async def test_max_steps_cap(svc, executor):
    looping = ('循环\n```studio-actions\n[{"action":"continue","reason":"永远继续"}]\n```', "stop")
    llm, calls = make_llm([looping])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[], max_steps=3,
    )
    assert result.steps == 3
    assert calls["n"] == 3
    assert any("上限" in w for w in result.warnings)


async def test_truncation_warning(svc, executor):
    truncated = ('被截断的回复\n```studio-actions\n[{"action":"add_group","title":"未闭合', "length")
    llm, _ = make_llm([truncated])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.steps == 1
    assert any("截断" in w for w in result.warnings)
    assert any("解析失败" in w for w in result.warnings)
    assert result.applied_actions == 0


async def test_context_refreshed_each_round(svc, executor):
    ctx_calls = {"n": 0}

    def context_builder():
        ctx_calls["n"] += 1
        return f"ctx-{ctx_calls['n']}"

    r1 = ('a\n```studio-actions\n[{"action":"continue"}]\n```', "stop")
    r2 = ("done", "stop")
    llm, calls = make_llm([r1, r2])
    await run_agent_loop(
        "x", llm_call=llm, context_builder=context_builder, executor=executor, history=[],
    )
    # 每轮都要重建上下文，且两轮拿到的不同
    assert calls["systems"] == ["ctx-1", "ctx-2"]


# ---------- P2-6：FC 提前终止 ----------

def make_fc_llm(replies):
    """按次序返回预设回复的假 LLM；fc_applied 从预设元组第三位取"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return reply[0], reply[1], reply[2]

    return llm_call, calls


async def test_fc_stop_with_visible_text_ends_early(svc, executor):
    """模型明确 stop 且已产出可见文本：单轮即终止，不追加总结轮"""
    llm, calls = make_fc_llm([("已完成创建", "stop", 1)])
    result = await run_agent_loop(
        "创建分镜", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 1
    assert result.steps == 1
    assert result.applied_actions == 1
    assert "已完成创建" in result.text


async def test_fc_tool_calls_finish_continues_chain(svc, executor):
    """finish=tool_calls 表示链路未完：继续下一轮（多步工具链不受影响）"""
    llm, calls = make_fc_llm([
        ("处理中", "tool_calls", 1),
        ("全部完成", "stop", 1),
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 2
    assert result.applied_actions == 2
    assert "全部完成" in result.text


async def test_fc_stop_without_text_continues(svc, executor):
    """stop 但无可见文本（模型可能还想做更多）：继续下一轮"""
    llm, calls = make_fc_llm([
        ("", "stop", 1),
        ("收尾总结", "stop", 0),
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 2
    assert result.applied_actions == 1


# ---------- 流程闸机自愈（8888 事故：操作全被拦但正文虚报成功并暂停） ----------

async def test_all_gate_blocked_heals_and_retries(svc):
    """文本轨操作全被闸机拦截：不接受虚报暂停，回喂拦截原因让模型补做后重试"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    # 清空 demo 故事板：确保「首次搭建」硬闸生效（首拆只允许关键元素）
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    # 第1轮：首次搭建直接拆分镜 + 虚报成功并请求确认 → 被首拆硬闸全部拦截
    r1 = ('已完成分镜拆解，共创建 2 个镜头。\n```studio-actions\n'
          '[{"action":"add_group","group_type":"shot","title":"Shot_A","draft":{"label":"d"}},'
          '{"action":"add_group","group_type":"shot","title":"Shot_B","draft":{"label":"d"}},'
          '{"action":"request_confirmation","message":"已拆好，请确认"}]\n```', "stop")
    # 第2轮（自愈）：先写规格文档再暂停
    r2 = ('规格已写入。\n```studio-actions\n'
          '[{"action":"write_document","name":"Final_Video_Spec.md","content":"标题：测试"},'
          '{"action":"request_confirmation","message":"规格文档已写入，请审阅"}]\n```', "stop")
    llm, calls = make_llm([r1, r2])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 2  # 拦截后触发了修正轮
    # 暂停文案来自修正轮，不是虚报的「已拆好」
    assert result.confirmation == "规格文档已写入，请审阅"
    assert "已拆好" not in result.confirmation
    # 虚报正文被丢弃，最终正文只有修正轮产出
    assert "已完成分镜拆解" not in result.text
    assert "规格已写入" in result.text
    # 规格文档真正写入了
    assert any(d.get("name") == "Final_Video_Spec.md" for d in svc.state_dict["documents"])
    # 分镜并未被虚假创建（只查本用例试图创建的分组，避免单例残留数据干扰）
    titles = [g.get("title") for g in (svc.state_dict.get("shots") or [])]
    assert "Shot_A" not in titles and "Shot_B" not in titles


def test_executor_records_gate_rejections(svc):
    """执行器记录闸机拦截原因（供 agent_loop 回喂），下批次重置"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    applied = ex.execute([
        {"action": "add_group", "group_type": "shot", "title": "S1", "draft": {"label": "d"}},
        {"action": "add_group", "group_type": "shot", "title": "S2", "draft": {"label": "d"}},
    ])
    assert applied == 0
    assert ex.gate_rejections and "关键元素" in ex.gate_rejections[0]
    assert len(ex.gate_rejections) == 1  # 同批同原因去重
    # 写入规格文档后再执行：放行且拦截记录重置
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "title": "E1", "draft": {"label": "d"}},
    ])
    assert applied == 1
    assert ex.gate_rejections == []


# ---------- 8888 事故回归：拆完分镜虚报「提示词已写好」并引导开始生成 ----------

async def test_structure_pause_overrides_false_confirmation(svc):
    """拆完分镜后：确认卡片强制换成分镜拆分审阅文案，正文附更正说明"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    long_prompt = "详细的视频生成提示词草案内容" * 10  # >40 字，会被结构纯净闸剥离
    r1 = ('已拆解 1 个分镜并编写了视频生成提示词草案。\n```studio-actions\n'
          '[{"action":"add_group","group_type":"shot","title":"Shot_A",'
          '"draft":{"label":"d","prompt":"' + long_prompt + '"}},'
          '{"action":"request_confirmation","message":"确认分镜与音频草案，开始生成视频",'
          '"options":[{"label":"确认草案，开始生成视频"}]}]\n```', "stop")
    llm, calls = make_llm([r1])
    result = await run_agent_loop(
        "拆解分镜", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 1
    # 确认文案被系统覆盖为分镜拆分审阅（而非虚报的「确认草案，开始生成」）
    assert result.confirmation == prompt_gates.SHOT_STRUCTURE_PAUSED_MSG
    assert result.confirmation_options == prompt_gates.SHOT_STRUCTURE_OPTIONS
    assert "开始生成视频" not in result.confirmation
    assert any("继续编写视频提示词" in o["label"] for o in result.confirmation_options)
    # 内联详细提示词被剥离，卡片只有骨架（按标题定位本用例新建的分组，避开 demo 残留）
    shot_group = next(g for g in svc.state_dict["shots"] if g.get("title") == "Shot_A")
    assert shot_group["drafts"][0]["prompt"] == ""
    # 正文附带更正说明，不再只剩虚报文字
    assert "系统说明" in result.text


async def test_keyelement_structure_pause_wording(svc):
    """只建关键元素时：暂停文案用关键元素拆分审阅版（下一步写生图提示词）"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    r1 = ('拆好了。\n```studio-actions\n'
          '[{"action":"add_group","group_type":"keyElement","title":"Element_A","draft":{"label":"d"}},'
          '{"action":"request_confirmation","message":"确认草案，开始生成"}]\n```', "stop")
    llm, _ = make_llm([r1])
    result = await run_agent_loop(
        "拆关键元素", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert result.confirmation == prompt_gates.STORYBOARD_STRUCTURE_PAUSED_MSG
    assert result.confirmation_options == prompt_gates.STORYBOARD_STRUCTURE_OPTIONS


# ---------- 8888 事故回归：部分提示词被闸机拦截仍引导确认 ----------

_GOOD_SHOT_PROMPT = (
    "镜头总时长：10秒。镜头缓慢推入，中景：主角抬头凝视远方翻涌的云层，双手微微颤抖；"
    "随后切至远景，天空被光幕逐渐覆盖。音效 <风声低鸣>，no music, no subtitles。"
)


async def test_partial_gate_blocked_heals_before_confirmation(svc):
    """9 写 8 拦类事故：部分提示词被拦时不接受确认，回喂重写后再暂停"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    st = svc.state_dict
    st["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    # 关键元素已有概念图（解除分镜提示词时序闸）
    st["keyElements"] = [{"id": "ke-1", "title": "E1",
                          "drafts": [{"id": "draft-ke1", "imgUrl": "http://x/y.png"}]}]
    st["shots"] = [
        {"id": "shot-1", "title": "S1", "drafts": [{"id": "draft-s1", "tag": "Agent", "prompt": ""}]},
        {"id": "shot-2", "title": "S2", "drafts": [{"id": "draft-s2", "tag": "Agent", "prompt": ""}]},
    ]
    bad = _GOOD_SHOT_PROMPT.replace("no subtitles", "")  # 缺负面约束 → 被质量闸拦截
    # 第1轮：一条写入成功、一条被拦，模型却请求确认提示词 → 不接受，回喂重写
    r1 = ('提示词已全部写好。\n```studio-actions\n'
          '[{"action":"update_draft","draft_type":"shot","draft_id":"draft-s1","patch":{"prompt":"'
          + _GOOD_SHOT_PROMPT + '"}},'
          '{"action":"update_draft","draft_type":"shot","draft_id":"draft-s2","patch":{"prompt":"'
          + bad + '"}},'
          '{"action":"request_confirmation","message":"请确认提示词草案"}]\n```', "stop")
    # 第2轮（自愈）：补齐被拦的那条后再请求确认
    r2 = ('已补齐重写。\n```studio-actions\n'
          '[{"action":"update_draft","draft_type":"shot","draft_id":"draft-s2","patch":{"prompt":"'
          + _GOOD_SHOT_PROMPT + '"}},'
          '{"action":"request_confirmation","message":"提示词已全部写入卡片，请确认"}]\n```', "stop")
    llm, calls = make_llm([r1, r2])
    result = await run_agent_loop(
        "编写分镜的视频提示词", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 2  # 拦截后触发了修正轮
    # 暂停来自修正轮，不是第1轮的虚假确认
    assert result.confirmation == "提示词已全部写入卡片，请确认"
    # 第1轮虚报正文被丢弃
    assert "提示词已全部写好" not in result.text
    # 两条提示词最终都写入了卡片
    assert st["shots"][0]["drafts"][0]["prompt"] == _GOOD_SHOT_PROMPT
    assert st["shots"][1]["drafts"][0]["prompt"] == _GOOD_SHOT_PROMPT
    assert any("拦截" in w for w in result.warnings)


# ---------- 边写边填：流式增量提取器 + 预执行去重 ----------

async def test_streaming_extractor_emits_objects_incrementally():
    """studio-actions 块逐 chunk 喂入：每个 JSON 对象一闭合即可提取"""
    from src.video_agent.web.action_parser import StreamingActionExtractor
    ext = StreamingActionExtractor()
    block = (
        '[{"action":"update_draft","draft_id":"a","patch":{"prompt":"第一段提示词"}},'
        '{"action":"update_draft","draft_id":"b","patch":{"prompt":"含花括号{对话}与转义\\"引号"}}]'
    )
    got = []
    for i in range(0, len(block), 7):  # 任意切块喂入
        got.extend(ext.feed(block[i:i + 7]))
    assert len(got) == 2
    assert got[0]["draft_id"] == "a"
    assert got[1]["patch"]["prompt"] == '含花括号{对话}与转义"引号'


async def test_stream_preapplied_actions_not_reexecuted(svc):
    """流式预执行过的动作在批末不得重复执行（add_group 重复会建重分组）"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    # 模拟 planner 流式路径：逐条预执行（accumulate）
    act = {"action": "add_group", "group_type": "keyElement", "title": "Element_S", "draft": {"label": "d"}}
    assert ex.execute([act], accumulate=True) == 1
    ex.stream_consumed = 1
    ex.stream_preapplied = 1
    # 模拟 agent_loop：同一动作再次出现在解析结果里 → 应被剔除，不重复建组
    reply = ('完成\n```studio-actions\n'
             '[{"action":"add_group","group_type":"keyElement","title":"Element_S","draft":{"label":"d"}}]\n```', "stop")
    llm, calls = make_llm([reply])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 1
    assert result.applied_actions == 1  # 只计流式预执行的那一次
    titles = [g.get("title") for g in svc.state_dict["keyElements"] if g.get("title") == "Element_S"]
    assert len(titles) == 1  # 没有重复建组
