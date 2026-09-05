"""run_agent_loop：FC 单轨循环语义（audit-0819b 协议单轨化，决策史见 git tag adr-archive-20260901）。

钉死：多步链（finish=tool_calls 继续）、max_steps 上限、每轮上下文重建、
纯文本收尾轮、结构化暂停确认（llm_call 第 5 元组 extra）、虚报审计与
假停兜底（轮末策略在纯文本轮执行）、坏输出重试。

文本块解析路径（continue/确认/动作经 studio-actions 文本）已随双轨退役
删除，对应旧用例同批退役；暂停确认现唯一经 workflow_pause FC 工具产生
（单一正名，audit-0819d；fc_tool_runner → 5 元组 extra 上抛）。
"""
import pytest

from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.round_end_policies import _claims_structure_done
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


def _p5(reply):
    """测试数据便捷写法：3/4 元组补齐为 5 元组契约 (plan_ms=0.0 / extra={})。"""
    if len(reply) == 5:
        return reply
    return reply + (0.0, {}) if len(reply) == 3 else reply + ({},)


def make_plain_llm(replies):
    """纯文本回复桩：每轮都是收尾轮（无工具调用）"""
    calls = {"n": 0, "systems": []}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["systems"].append(system_prompt)
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return reply[0], reply[1], 0, 0.0, {}

    return llm_call, calls


def make_fc_llm(replies):
    """FC 轮桩：元素为 5 元组 (content, finish, fc_applied, plan_ms, extra)，
    允许 3/4 元组便捷写法（经 _p5 补齐）；
    extra = {"confirmation": str, "confirmation_options": list}（audit-0819b）。
    """
    calls = {"n": 0, "systems": []}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["systems"].append(system_prompt)
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return _p5(reply)

    return llm_call, calls


# ---------- 多步链（FC 语义：finish=tool_calls / 无可见正文 → 续轮） ----------

async def test_fc_tool_chain_continues_and_caps(svc, executor):
    """finish=tool_calls 链路未完 → 续轮；达到 max_steps 上限 → 终止并告警"""
    llm, calls = make_fc_llm([
        ("处理中", "tool_calls", 1),
        ("继续", "tool_calls", 1),
        ("还在做", "tool_calls", 1),
        ("不会到达", "stop", 1),
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=3,
    )
    assert result.steps == 3
    assert calls["n"] == 3
    assert any("上限" in w for w in result.warnings)


async def test_context_refreshed_each_round(svc, executor):
    """每轮都要重建上下文（看到上一轮执行后的最新状态），且两轮拿到的不同"""
    llm, calls = make_fc_llm([
        ("处理中", "tool_calls", 1),
        ("收尾总结", "stop", 0),
    ])
    await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: f"ctx-{len(calls['systems']) + 1}",
        executor=executor, history=[],
    )
    assert calls["systems"] == ["ctx-1", "ctx-2"]


async def test_pure_text_round_is_terminal(svc, executor):
    """单轨化后纯文本回复 = 收尾轮：无 continue 通道，一轮终止"""
    llm, calls = make_plain_llm([("第一轮回复", "stop"), ("不该到达", "stop")])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 1
    assert result.steps == 1
    assert "第一轮回复" in result.text


# ---------- P2-6：FC 提前终止 ----------

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


# ---------- 批 9：全拒收轮回喂继续（回合终止盲区修复，9999 死锁根因） ----------

async def test_all_rejected_round_feeds_back_and_continues(svc, executor):
    """全拒收轮（fc_applied=0 但发起过调用）不得按纯文本轮终止：
    拒因回喂已在 messages，循环必须再走一轮让模型看到"先 workflow_pause"指引。"""
    llm, calls = make_fc_llm([
        ("现在生成形象图", "tool_calls", 0, 0.0, {"had_fc_calls": True}),
        ("收到拦截指引，先暂停请求确认", "tool_calls", 0, 0.0,
         {"had_fc_calls": True, "confirmation": "请确认生成", "pause_id": "p1"}),
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 2, "全拒收轮后循环必须继续（不得终止回合）"
    assert result.confirmation == "请确认生成"
    assert result.pause_id == "p1"


async def test_all_rejected_stop_with_text_still_continues(svc, executor):
    """全拒收轮 + stop + 可见文本：'自称完成'不可信（9999 实证），
    提前终止规则让位——仍续轮消费拒因回喂。"""
    llm, calls = make_fc_llm([
        ("好的！关键元素已创建。现在生成形象图。", "stop", 0, 0.0, {"had_fc_calls": True}),
        ("已按指引请求确认", "stop", 0),
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 2
    assert result.steps == 2
    assert "已按指引请求确认" in result.text


async def test_all_rejected_rounds_still_capped_by_max_steps(svc, executor):
    """全拒收轮续轮仍受 max_steps 封顶（无死循环风险）。"""
    llm, calls = make_fc_llm([
        ("继续撞闸", "tool_calls", 0, 0.0, {"had_fc_calls": True}),
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
        max_steps=2,
    )
    assert calls["n"] == 2
    assert result.steps == 2
    assert any("上限" in w for w in result.warnings)


async def test_pure_text_round_still_terminal_after_fix(svc, executor):
    """未发起任何工具调用的纯文本轮照常收尾（修复不改变正常收尾语义）。"""
    llm, calls = make_fc_llm([("普通回复", "stop", 0), ("不该到达", "stop", 0)])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 1
    assert result.steps == 1
    assert "普通回复" in result.text
    assert result.applied_actions == 0


# ---------- 批 12：产出类被拒的混合轮续轮（1000 正向修复） ----------

async def test_mixed_round_productive_reject_continues(svc, executor):
    """混合轮（部分调用成功 + 产出类被拒）+ stop + 可见文本 → 不提前终止：
    部分成功不代表产出落账（1000 实证：read_skill 成功 + 写规格被拒，
    模型口播"已写入制片规格"假完成收尾），拒因必须被下一轮消费。"""
    llm, calls = make_fc_llm([
        ("已读取规范，现在写入规格。", "stop", 1, 0.0,
         {"had_fc_calls": True, "rejected_productive_tools": ["document_write"]}),
        ("收到拦截指引，先暂停请求确认。", "stop", 0),
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 2, "产出类被拒的混合轮不得按纯文本轮提前终止"
    assert result.steps == 2


async def test_mixed_round_readonly_reject_still_terminal(svc, executor):
    """负样本：本轮无产出类被拒（extra 无该键）→ 照旧提前终止。"""
    llm, calls = make_fc_llm([
        ("参考规范已说明，无需进一步操作。", "stop", 1, 0.0,
         {"had_fc_calls": True}),
    ])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 1 and result.steps == 1


async def test_productive_reject_budget_exhausts(svc, executor):
    """续轮预算（recovery_policy productive_reject.max_retries=2）耗尽 →
    收尾并附产物缺失警告，不烧满 max_steps（防打转）。"""
    replies = [
        (f"口播完成 {i}", "stop", 1, 0.0,
         {"had_fc_calls": True, "rejected_productive_tools": ["document_write"]})
        for i in range(5)
    ]
    llm, calls = make_fc_llm(replies)
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
        max_steps=5,
    )
    assert calls["n"] == 3, "首轮 + 预算内续轮 2 次 = 第 3 轮收尾"
    assert result.steps == 3
    assert any("未能执行" in w for w in result.warnings), \
        f"预算耗尽收尾必须附产物缺失警告: {result.warnings}"


# ---------- 批 12：对账扩展（宣称完成 ↔ 产物账本，1000 假话口播兜底） ----------

async def test_false_claim_spec_audit_warns_when_spec_missing(svc, executor):
    """纯文本轮口播「规格已写入」而规格文档缺失 → 虚报警告（此前仅确认轮
    有结构对账）。"""
    llm, _ = make_plain_llm([("已锁定规格参数，制片规格已写入。", "stop")])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert any("虚报" in w and "制片规格" in w for w in result.warnings), \
        f"规格宣称应对账警告: {result.warnings}"


async def test_false_claim_spec_audit_passes_when_spec_exists(svc, executor):
    """规格文档确实存在 → 不误报（4444 误报校准基调）。"""
    svc.state_dict["documents"] = [
        {"name": "制片规格.md", "content": "# 制片规格\n时长：3分钟"}]
    llm, _ = make_plain_llm([("制片规格已写入。", "stop")])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert not any("虚报" in w for w in result.warnings)


async def test_false_claim_future_tense_exempt(svc, executor):
    """将来时措辞（接下来写入）不算宣称（未来时豁免保持）。"""
    llm, _ = make_plain_llm([("规格已定，接下来写入制片规格文档。", "stop")])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert not any("虚报" in w for w in result.warnings)


# ---------- audit-0819b：结构化暂停确认（5 元组 extra 直通） ----------

async def test_structured_confirmation_stops_loop(svc, executor):
    """FC 批经 workflow_pause 产生的确认经第 5 元组上抛：循环停止、
    文案与选项原样带回，且不再经任何文本块（协议单轨）。"""
    opts = [
        {"label": "继续下一步", "description": "推进下一阶段"},
        {"label": "我要调整", "description": "告诉我要改什么"},
    ]
    llm, calls = make_fc_llm([
        ("拆解完成，请确认。", "stop", 2,
         0.0, {"confirmation": "已拆解完毕，请确认", "confirmation_options": opts}),
        ("不该到达", "stop", 0),
    ])
    result = await run_agent_loop(
        "拆解", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 1                      # 确认即停，没有第二轮
    assert result.confirmation == "已拆解完毕，请确认"
    assert result.confirmation_options == opts
    assert result.applied_actions == 2          # 工具执行照计
    assert "拆解完成，请确认。" in result.text      # 正文原样可见（无文本块可清洗）


async def test_fc_text_visible_as_is(svc, executor):
    """单轨化：FC 轮正文原样可见（studio-actions 文本通道已退役，
    模型输出即用户可见，harness 不再做动作块清洗/解析）。"""
    llm, _ = make_fc_llm([("任务已完成，故事板已更新。", "stop", 1)])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert result.text == "任务已完成，故事板已更新。"


# ---------- 坏输出防护（S03 承重不变） ----------

async def test_bad_output_malformed_retried_then_ok(svc, executor):
    """回归（5555 事故）：MALFORMED_FUNCTION_CALL 视为坏输出自动重试，重试成功则正常推进，
    用户不再需要手动发「继续」。"""
    bad = ("", "MALFORMED_FUNCTION_CALL")
    good = ("已完成", "stop")
    llm, calls = make_plain_llm([bad, good])
    result = await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 2  # 首调失败 + 重试一次成功
    assert "已完成" in result.text


async def test_bad_output_exhausts_retries_with_clear_message(svc, executor):
    """空响应+畸形连续发生：重试上限 2 次，最终文案写明故障性质与重试次数。"""
    llm, calls = make_plain_llm([
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


# ---------- 轮末策略（纯文本收尾轮执行：虚报审计 / 假停兜底） ----------

async def test_false_claim_warns_but_keeps_pause(svc, executor):
    """回归（7777 × 4444）：声称拆解完成但故事板为空 → 只附警告不拦人：
    结构化暂停照常递给用户（闸机哲学：永不拦截只警告，系统不没收模型的暂停）。"""
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    llm, calls = make_fc_llm([
        ("已完成关键元素穷尽拆解，各分组已写入故事板", "stop", 0,
         0.0, {"confirmation": "请审阅关键元素", "confirmation_options": []}),
    ])
    result = await run_agent_loop(
        "拆解关键元素", llm_call=llm, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1                            # 只跑一轮，不打回重做
    assert result.confirmation == "请审阅关键元素"        # 暂停原样递给用户
    assert len(svc.state_dict["keyElements"]) == 0    # 客观事实：确实没拆
    # 虚报审计在 FC 确认轮同样承重（单轨化不豁免）：附警告不拦人
    #（批 12 对账扩展：文案泛化为产物族口径——结构搭建是产物之一）
    assert any("虚报" in w and "结构搭建" in w and "产物实际缺失" in w
               for w in result.warnings)


async def test_future_tense_pause_no_warning_empty_board(svc, executor):
    """回归（4444）：规格阶段合法暂停带将来时（总结已完成…将拆解），
    故事板为空也不得触发虚报警告，暂停照常递给用户。"""
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    llm, calls = make_fc_llm([
        ("剧本总结已完成，请确认制作规格，确认后我将拆解关键元素", "stop", 0,
         0.0, {"confirmation": "请确认制作规格", "confirmation_options": []}),
    ])
    result = await run_agent_loop(
        "开始", llm_call=llm, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1
    assert result.confirmation == "请确认制作规格"
    assert result.warnings == []


async def test_legit_pause_not_blocked(svc, executor):
    """真实拆解后的暂停不被虚报闸误伤：故事板非空时照常递给用户。"""
    # Q2 后文本轨动作退役：故事板结构直接经状态写入布置（与 FC 工具落点同构）
    svc.state_dict["keyElements"] = [{
        "id": "ke-a", "title": "Element_A", "desc": "角色", "drafts": [],
    }]
    llm, calls = make_fc_llm([
        ("已完成关键元素拆解并录入故事板", "stop", 1,
         0.0, {"confirmation": "请审阅", "confirmation_options": []}),
    ])
    result = await run_agent_loop(
        "拆解关键元素", llm_call=llm, context_builder=lambda: "ctx",
        executor=executor, history=[],
    )
    assert calls["n"] == 1  # 一轮到位，无拦截
    assert result.confirmation == "请审阅"
    assert not any("虚报" in w for w in result.warnings)


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
