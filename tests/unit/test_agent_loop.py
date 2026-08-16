"""run_agent_loop：多步 continue 协议、截断告警、上限终止"""
import pytest

from src.video_agent.web.action_executor import StudioActionExecutor
from src.video_agent.core.agent_loop import run_agent_loop, _claims_structure_done
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

async def test_all_gate_bypassed_writes_and_keeps_model_pause(svc, monkeypatch):
    """文本轨操作不再被闸机拦截：分组照常创建，模型自带的暂停原样保留"""
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(
        registry, "skill_flow_enabled", lambda skill, key: key == "spec_gate",
    )
    ex = StudioActionExecutor(svc, gate_enabled=True)
    ex.skill_name = "测试流程Skill"
    # 第1轮：无规格文档直拆关键元素 + 请求确认 → 照常执行并附警告
    r1 = ('已完成关键元素拆解，共创建 2 个分组。\n```studio-actions\n'
          '[{"action":"add_group","group_type":"keyElement","title":"Element_A","draft":{"label":"d"}},'
          '{"action":"add_group","group_type":"keyElement","title":"Element_B","draft":{"label":"d"}},'
          '{"action":"request_confirmation","message":"已拆好，请确认"}]\n```', "stop")
    llm, calls = make_llm([r1])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 1  # 无拦截，不需要修正轮
    # 模型自带的暂停原样保留（系统不再强制覆盖）
    assert result.confirmation == "已拆好，请确认"
    # 正文保留模型总结
    assert "已完成关键元素拆解" in result.text
    # 规格文档未写入但操作已执行（flow_gates=None 时不强制）；
    # 814Gb：规格前置用户侧静默，不再进 gate_warnings
    assert not any(d.get("name") == "制片规格.md" for d in (svc.state_dict.get("documents") or []))
    assert not any("规格文档" in w for w in ex.gate_warnings)
    # 关键元素已真实创建
    titles = [g.get("title") for g in (svc.state_dict.get("keyElements") or [])]
    assert "Element_A" in titles and "Element_B" in titles


def test_executor_records_gate_warnings(svc, monkeypatch):
    """814Gb：规格前置用户侧静默（执行侧强制由 FlowGateSet 承担），下批次重置"""
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(
        registry, "skill_flow_enabled", lambda skill, key: key == "spec_gate",
    )
    ex = StudioActionExecutor(svc, gate_enabled=True)
    ex.skill_name = "测试流程Skill"
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "title": "E1", "draft": {"label": "d"}},
        {"action": "add_group", "group_type": "keyElement", "title": "E2", "draft": {"label": "d"}},
    ])
    assert applied == 2
    assert ex.gate_rejections == []
    assert not any("规格文档" in w for w in ex.gate_warnings)
    # 写入规格文档后再执行：放行；拦截记录（rejections）按批次重置，
    # 警告（gate_warnings）按任务累积供回复展示，不要求清空
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "title": "E1", "draft": {"label": "d"}},
    ])
    assert applied == 1
    assert ex.gate_rejections == []


# ---------- 8888 事故回归：拆完分镜虚报「提示词已写好」并引导开始生成 ----------

async def test_structure_strips_inline_prompt_keeps_model_confirmation(svc):
    """拆完分镜后：模型确认文案保留；结构阶段内联提示词被剥离（P0-2）"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    long_prompt = "详细的视频生成提示词草案内容" * 10
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
    # 模型自带的确认文案保留；选项换成系统阶段卡（8888 二轮 B8）
    assert result.confirmation == "确认分镜与音频草案，开始生成视频"
    assert [o["label"] for o in result.confirmation_options] == [
        o["label"] for o in prompt_gates.SHOT_STRUCTURE_OPTIONS]
    # 结构阶段内联提示词被剥离，草稿卡仍建立
    shot_group = next(g for g in svc.state_dict["shots"] if g.get("title") == "Shot_A")
    assert shot_group["drafts"][0]["prompt"] == ""
    assert ex.prompts_stripped == 1
    assert "系统说明" not in result.text


async def test_keyelement_structure_keeps_model_pause(svc):
    """只建关键元素时：模型自带的暂停文案原样保留"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    r1 = ('拆好了。\n```studio-actions\n'
          '[{"action":"add_group","group_type":"keyElement","title":"Element_A","draft":{"label":"d"}},'
          '{"action":"request_confirmation","message":"确认草案，开始生成"}]\n```', "stop")
    llm, _ = make_llm([r1])
    result = await run_agent_loop(
        "拆关键元素", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert result.confirmation == "确认草案，开始生成"
    assert [o["label"] for o in result.confirmation_options] == [
        o["label"] for o in prompt_gates.STORYBOARD_STRUCTURE_OPTIONS]


# ---------- 5555 事故回归：规格文档写入后的系统级暂停兜底（文本轨） ----------

async def test_spec_doc_written_injects_pause_and_blocks_continue(svc, monkeypatch):
    """写完规格后模型输出 continue 想直冲下一步：系统强制停在规格审阅。
    6666 二轮：硬参数由全局设置提供，规格审阅卡不再升级为候选项向导。
    （4444：无 usedSkills 时模型写规格不拒收——拒收仅对真实选中的 Skill 生效）"""
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(registry, "skill_flow_enabled", lambda skill, key: True)
    monkeypatch.setattr(
        registry, "spec_wizard_active", lambda skill: skill == "测试流程Skill")
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    ex = StudioActionExecutor(svc, gate_enabled=True)
    ex.skill_name = "测试流程Skill"
    r1 = ('规格已保存，接下来开始拆解。\n```studio-actions\n'
          '[{"action":"write_document","name":"制片规格.md","content":"画幅：16:9"},'
          '{"action":"continue","reason":"拆解关键元素"}]\n```', "stop")
    r2 = ("不该走到这一轮", "stop")
    llm, calls = make_llm([r1, r2])
    result = await run_agent_loop(
        "确认规格", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 1  # continue 被暂停兜底压住，没有进第二轮
    assert result.confirmation == prompt_gates.SPEC_DOC_PAUSED_MSG
    # 6666 二轮：测试 Skill 无软维度、硬参数不再向导化 → 常规审阅卡（无分页组）
    assert not any(o.get("group") for o in result.confirmation_options)
    # 规格文档已真实写入
    assert any(d["name"] == "制片规格.md" for d in svc.state_dict["documents"])


async def test_spec_doc_confirmed_params_uses_plain_pause_card(svc, monkeypatch):
    """三项制作参数已定稿：沿用常规审阅暂停卡（9999 事故升级的分母场景）"""
    import json as _json
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(registry, "skill_flow_enabled", lambda skill, key: True)
    monkeypatch.setattr(
        registry, "spec_wizard_active", lambda skill: skill == "测试流程Skill")
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    ex = StudioActionExecutor(svc, gate_enabled=True)
    ex.skill_name = "测试流程Skill"
    spec = ("画幅：16:9\n图片分辨率：2K\n视频分辨率：720p\n分镜最大时长：12 秒\n"
            "视频类型：叙事短片\n输出语言：中文\n时长：约 60 秒\n"
            "叙事驱动：故事驱动\n视觉风格：写实")
    block = _json.dumps([
        {"action": "write_document", "name": "制片规格.md", "content": spec},
        {"action": "continue", "reason": "拆解关键元素"},
    ], ensure_ascii=False)
    r1 = (f'规格已保存。\n```studio-actions\n{block}\n```', "stop")
    llm, calls = make_llm([r1])
    result = await run_agent_loop(
        "确认规格", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 1
    assert result.confirmation == prompt_gates.SPEC_DOC_PAUSED_MSG
    labels = [o["label"] for o in result.confirmation_options]
    assert labels == [o["label"] for o in prompt_gates.spec_review_options(svc.state_dict)]


async def test_spec_doc_written_keeps_model_confirmation(svc):
    """写完规格且模型已自发 request_confirmation：不覆盖模型的暂停"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    r1 = ('规格已保存。\n```studio-actions\n'
          '[{"action":"write_document","name":"制片规格.md","content":"画幅：16:9"},'
          '{"action":"request_confirmation","message":"请审阅规格条目"}]\n```', "stop")
    llm, _ = make_llm([r1])
    result = await run_agent_loop(
        "确认规格", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert result.confirmation == "请审阅规格条目"


async def test_non_spec_doc_written_keeps_continue(svc):
    """写入普通文档：不注入暂停，continue 照常生效"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    r1 = ('先写个大纲。\n```studio-actions\n'
          '[{"action":"write_document","name":"大纲.md","content":"正文"},'
          '{"action":"continue","reason":"继续"}]\n```', "stop")
    r2 = ("大纲写完收工", "stop")
    llm, calls = make_llm([r1, r2])
    result = await run_agent_loop(
        "写大纲", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 2
    assert result.confirmation == ""


# ---------- 8888 事故回归：暂停轮正文缺总结时从工作台状态补 ----------

async def test_confirmation_turn_summary_not_prepended_anymore(svc):
    """8888 二轮：总结由收集卡模板内嵌，正文不再补拼（防总结两遍）。"""
    svc.state_dict["analysis"] = {"summary": "太阳系逐渐二维化"}
    svc.state_dict.setdefault("interaction", {})["pending_pause_kind"] = (
        prompt_gates.SPEC_COLLECT_KIND
    )
    ex = StudioActionExecutor(svc, gate_enabled=False)
    r1 = ("请确认制片规格参数。\n```studio-actions\n"
          '[{"action":"request_confirmation","message":"请确认规格"}]\n```', "stop")
    llm, _ = make_llm([r1])
    result = await run_agent_loop(
        "开始", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert result.confirmation == "请确认规格"
    assert not result.text.startswith("**剧本一句话总结**")


async def test_confirmation_turn_no_duplicate_summary(svc):
    """模型正文已带总结：不重复注入"""
    svc.state_dict["analysis"] = {"summary": "太阳系逐渐二维化"}
    ex = StudioActionExecutor(svc, gate_enabled=False)
    r1 = ("一句话总结：太阳系逐渐二维化。请确认规格。\n```studio-actions\n"
          '[{"action":"request_confirmation","message":"请确认规格"}]\n```', "stop")
    llm, _ = make_llm([r1])
    result = await run_agent_loop(
        "开始", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert result.text.count("太阳系逐渐二维化") == 1


# ---------- 8888 事故回归：部分提示词被闸机拦截仍引导确认 ----------

_GOOD_SHOT_PROMPT = (
    "镜头总时长：10秒。镜头缓慢推入，中景：主角抬头凝视远方翻涌的云层，双手微微颤抖；"
    "随后切至远景，天空被光幕逐渐覆盖。音效 <风声低鸣>，no music, no subtitles。"
)


async def test_partial_bad_prompt_rejected_and_healed(svc):
    """决策 D（质量优先）：不合格提示词被拒绝并回喂模型修正，确认被撤销"""
    ex = StudioActionExecutor(svc, gate_enabled=True)
    st = svc.state_dict
    st["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    # 关键元素已有概念图（解除分镜提示词时序闸）
    st["keyElements"] = [{"id": "ke-1", "title": "E1",
                          "drafts": [{"id": "draft-ke1", "imgUrl": "http://x/y.png"}]}]
    st["shots"] = [
        {"id": "shot-1", "title": "S1", "drafts": [{"id": "draft-s1", "tag": "Agent", "prompt": ""}]},
        {"id": "shot-2", "title": "S2", "drafts": [{"id": "draft-s2", "tag": "Agent", "prompt": ""}]},
    ]
    bad = _GOOD_SHOT_PROMPT.replace("no subtitles", "")  # 缺负面约束 → 被质量闸拦截
    # 第1轮：一条合格、一条不合格 → 合格写入，不合格拒绝并触发修正循环
    r1 = ('提示词已全部写好。\n```studio-actions\n'
          '[{"action":"update_draft","draft_type":"shot","draft_id":"draft-s1","patch":{"prompt":"'
          + _GOOD_SHOT_PROMPT + '"}},'
          '{"action":"update_draft","draft_type":"shot","draft_id":"draft-s2","patch":{"prompt":"'
          + bad + '"}},'
          '{"action":"request_confirmation","message":"请确认提示词草案"}]\n```', "stop")
    llm, calls = make_llm([r1])
    result = await run_agent_loop(
        "编写分镜的视频提示词", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] > 1  # 触发 gate_heal 修正循环
    assert result.confirmation == ""  # 存在被拦操作时不接受暂停/确认
    # 合格提示词写入，不合格提示词保持为空
    assert st["shots"][0]["drafts"][0]["prompt"] == _GOOD_SHOT_PROMPT
    assert st["shots"][1]["drafts"][0]["prompt"] == ""
    assert ex.gate_rejections


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
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    # 模拟 planner 流式路径：逐条预执行（accumulate）
    act = {"action": "add_group", "group_type": "keyElement", "title": "Element_S", "draft": {"label": "d"}}
    assert ex.execute([act], accumulate=True) == 1
    ex.stream_consumed = 1
    ex.stream_preapplied = 1
    # 模拟 agent_loop：同一动作再次出现在解析结果里 → 应被剔除，不重复建组
    reply = ('完成\n```studio-actions\n'
             '[{"action":"add_group","group_type":"keyElement","title":"Element_S","draft":{"label":"d"}}]\n```', "stop")
    # 结构首建后系统会强制再跑一轮自检补漏：第二轮模型暂停审阅
    pause = ('自检完成\n```studio-actions\n'
             '[{"action":"request_confirmation","message":"自检完成"}]\n```', "stop")
    llm, calls = make_llm([reply, pause])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert calls["n"] == 2
    assert result.applied_actions == 1  # 只计流式预执行的那一次
    assert result.confirmation  # 结构自检后统一暂停
    titles = [g.get("title") for g in svc.state_dict["keyElements"] if g.get("title") == "Element_S"]
    assert len(titles) == 1  # 没有重复建组


async def test_bad_output_malformed_retried_then_ok(svc, executor):
    """回归（5555 事故）：MALFORMED_FUNCTION_CALL 视为坏输出自动重试，重试成功则正常推进，
    用户不再需要手动发「继续」。"""
    bad = ("", "MALFORMED_FUNCTION_CALL")
    good = ("已完成", "stop")
    llm, calls = make_llm([bad, good])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 2  # 首调失败 + 重试一次成功
    assert "已完成" in result.text


async def test_bad_output_exhausts_retries_with_clear_message(svc, executor):
    """空响应+畸形连续发生：重试上限 2 次，最终文案写明故障性质与重试次数。"""
    llm, calls = make_llm([
        ("", ""),                                # 首调空响应
        ("", "MALFORMED_FUNCTION_CALL"),          # 重试 1 畸形
        ("", "MALFORMED_FUNCTION_CALL"),          # 重试 2 仍畸形 → 达到上限
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 3  # 首调 + 2 次重试，不多不少
    assert "输出异常" in result.text
    assert "重试 2 次" in result.text


async def test_false_claim_warns_but_keeps_pause(svc, executor):
    """回归（7777 事故 × 4444 改造）：声称拆解完成但故事板为空 →
    只附警告不拦人：暂停照常递给用户，不强制补跑第二轮（用户拍板的
    闸机哲学：永不拦截只警告，系统不没收模型的暂停）。"""
    # 清空 demo 项目自带分组，构造「新项目故事板为空」场景
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    claim_pause = (
        '已完成关键元素穷尽拆解，各分组已写入故事板\n```studio-actions\n'
        '[{"action":"request_confirmation","message":"请审阅关键元素"}]\n```', "stop")
    llm, calls = make_llm([claim_pause])
    result = await run_agent_loop(
        "拆解关键元素", llm_call=llm, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1                       # 只跑一轮，不打回重做
    assert result.confirmation == "请审阅关键元素"  # 暂停原样递给用户
    assert len(svc.state_dict["keyElements"]) == 0  # 客观事实：确实没拆
    assert "穷尽拆解" in result.text              # 正文不再被丢弃（附警告交用户核验）
    assert any("故事板实际仍为空" in w for w in result.warnings)


async def test_future_tense_pause_no_warning_empty_board(svc, executor):
    """回归（4444 事故）：规格阶段的合法暂停文案带将来时（总结已完成…
    将拆解关键元素），故事板为空也不得触发虚报警告，暂停照常递给用户。"""
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    legit_pause = (
        '剧本总结已完成，请确认制作规格，确认后我将拆解关键元素\n```studio-actions\n'
        '[{"action":"request_confirmation","message":"请确认制作规格"}]\n```', "stop")
    llm, calls = make_llm([legit_pause])
    result = await run_agent_loop(
        "开始", llm_call=llm, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1
    assert result.confirmation == "请确认制作规格"
    assert result.warnings == []


# ---------- 疑似虚报识别：邻近窗口 + 将来时豁免（4444 事故改造） ----------

def test_claims_adjacency_and_future_exemption():
    # 真声称（拆解与完成紧邻）：仍要识别出来附警告
    assert _claims_structure_done("已完成拆解，请验收")
    assert _claims_structure_done("拆解完成，请审阅")
    assert _claims_structure_done("关键元素拆解完成并写入故事板")
    assert _claims_structure_done("已创建 30 个分组并写入故事板")
    # 将来时/流程预告：不算声称（4444 误伤措辞）
    assert not _claims_structure_done("总结已完成，请确认规格，确认后将拆解关键元素")
    assert not _claims_structure_done("确认后进入关键元素拆解阶段，请确认规格")
    assert not _claims_structure_done("规格确认后、关键元素拆分后暂停")
    assert not _claims_structure_done("接下来拆解关键元素，先确认规格")
    # 完成与拆解距离过远（各说各的）：不算声称
    assert not _claims_structure_done(
        "规格文档已完成定稿写入，涵盖画幅与风格。接下来我们做关键元素的穷尽式拆解工作。"
    )


def test_claims_no_cross_text_seam_false_positive():
    """回归（2222 事故）：正文结尾「…关键元素拆解。」与暂停文案开头「剧本解析完成」
    跨文本拼接会产生假相邻——每段必须独立判定，不得误报。"""
    text = (
        "请在下方规格向导中选择或确认成片制作参数，"
        "确认后将为您生成《制作规格说明书》并开启故事板关键元素拆解。"
    )
    confirm = "### 剧本解析完成：《太阳系二维化》\n请在下方规格向导中选择或确认成片制作参数。"
    assert not _claims_structure_done(text, confirm)
    assert not _claims_structure_done(text)
    assert not _claims_structure_done(confirm)
    # 真谎报仍要识别（不受跨文本改造影响）
    assert _claims_structure_done("已完成关键元素拆解并写入故事板，请验收")


async def test_legit_pause_not_blocked(svc, executor):
    """真实拆解后的暂停不被虚报闸误伤：故事板非空时照常递给用户。"""
    real_split = (
        '已完成关键元素拆解并录入故事板\n```studio-actions\n'
        '[{"action":"add_group","group_type":"keyElement","title":"Element_A","desc":"角色"},'
        '{"action":"request_confirmation","message":"请审阅"}]\n```', "stop")
    llm, calls = make_llm([real_split])
    result = await run_agent_loop(
        "拆解关键元素", llm_call=llm, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1  # 一轮到位，无拦截
    assert result.confirmation
    assert not any("虚报" in w for w in result.warnings)
