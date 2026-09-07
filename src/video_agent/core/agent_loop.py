"""
Agent 多步执行循环（Rule2: 唯一实现）。

位于 core 层（编排骨架属核心层，不放 web/）。

有界循环（最多 max_steps 步）：FC 工具步（tool_calls 在 llm_call 内执行，
finish 非 stop 或无可见正文时继续下一步）与纯文本收尾步（
暂停确认经 llm_call 第 5 元组结构化上抛，不经文本块）。

llm_call / context_builder 以 callable 注入，便于单元测试。
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

import time

from loguru import logger

from src.video_agent.config import MAX_STEPS_RANGE, settings
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_STATUS,
    SSE_STEP_STARTED,
    SSE_STOPPED,
    SSE_TOOL_FINISHED,
    SSE_TOOL_STARTED,
    status_event,
)
# 协作式停止（端到端中断协议）：检查点只读标志注册表，
# 停止信号不经闸机/工具执行器传递
from src.video_agent.utils.stop_signal import (
    STOP_PHASE_STREAMING,
    STOP_PHASE_THINKING,
    STOP_PHASE_TOOL_EXECUTING,
    AgentStoppedError,
    clear_stop,
    current_stop_id,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.core.turn_frame import emit_prelude_events
from src.video_agent.utils.prompts import load_prompt_section
from src.video_agent.skill_runtime.registry import fallback_skill_from_state
# 轮末闸机分支收敛为声明式策略表（层 9 唯一落点）
from src.video_agent.core.round_end_policies import (
    RoundEndContext,
    claims_unbacked_products,  # 批 12 对账扩展：产物族宣称 ↔ 账本对账
    run_round_end_policies,
)
from src.video_agent.utils import live_metrics
from src.video_agent.core import prompt_gates
from src.video_agent.exceptions import AdapterError
# 失败恢复分级：循环骨架不再硬编码恢复语义，重试预算与处置动作
# 全部来自恢复策略分派表（policy-as-data，与闸机哲学一致）
from src.video_agent.core.recovery_policy import (
    FAILURE_ADAPTER,
    FAILURE_PRODUCTIVE_REJECT,
    classify_step_failure,
    recovery_for,
)
# 取消令牌贯穿：循环开始绑定 context-scoped 令牌（scope=stop_scope），
# FC 工具批 → adapters 长任务经 contextvars 免传参观察同一令牌
from src.video_agent.utils.cancel_token import (
    CancellationToken,
    GenerationCancelled,
    bind_cancel_token,
    unbind_cancel_token,
)
from src.video_agent.skill_runtime.progress import (
    bind_progress_emitter,
    unbind_progress_emitter,
)

# 执行器已下沉 core：顶层导入替代旧 TYPE_CHECKING 下的 web 延迟引用
from src.video_agent.core.action_executor import StateOperationExecutor


def current_max_steps() -> int:
    """多步上限实时读取口（Q3 裁决 2026-09-01：不再 import 期冻结）。

    循环每步实时调用，前端全局设置页经 runtime_settings 通道热更新后
    即刻生效（运行中任务调高上限可继续推进）；脏值/非法值钳制回落。
    显式传入 max_steps 的调用方（测试/特殊编排）优先于本实时值。
    """
    lo, hi = MAX_STEPS_RANGE
    try:
        value = int(settings.max_steps)
    except (TypeError, ValueError):
        value = 6
    return max(lo, min(value, hi))

# llm_call(system_prompt, messages, stream_hook?) -> 5 元组
# (content, finish_reason, fc_applied, plan_ms, extra)
# fc_applied: FC 路径已执行的 tool 数量
# plan_ms: 纯模型规划耗时
# extra: dict：{confirmation, confirmation_options}——
# 本轮 FC 批经 workflow_pause 产生的结构化暂停确认（不经文本块）
# stream_hook: 可选流式增量回调，每段文本 await stream_hook(text)
LlmCall = Callable[..., Awaitable[Tuple[str, str, int, float, Dict[str, Any]]]]
# context_builder -> 最新的 system prompt（协议 + 实时状态）
ContextBuilder = Callable[[], str]


# _bad_output_nudge 已随批 2 物理删除（nudge 重试退役，判空 = 正常收轮）；
# 退役记录见 core/recovery_policy.py 模块头。


@dataclass
class AgentLoopResult:
    text: str = ""
    applied_actions: int = 0
    steps: int = 0
    warnings: List[str] = field(default_factory=list)
    # LLM 通过 workflow_pause 工具请求用户确认时的说明文字（非空表示等待确认）
    confirmation: str = ""
    # 确认卡片的候选选项（每项 {label, description}，前端渲染为单选卡片）
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    # 执行轨迹（每轮 step/耗时/操作数/finish_reason），前端「执行轨迹」折叠区展示
    trace: Dict[str, Any] = field(default_factory=dict)
    # 建议动作按钮（确定性交互， 三问全中收归系统）：
    # retry=机械重发上一条用户消息（value 空，前端取历史原文）；
    # continue=发送固定文本推进新一步
    suggested_actions: List[Dict[str, str]] = field(default_factory=list)
    # 协作式停止标记（端到端中断协议）：
    # stopped=True 表示本循环经检查点命中用户停止信号干净退出；
    # stop_phase=thinking/tool_executing/streaming（前端气泡措辞依据）；
    # 问即停复用同一通道（决策史见 git tag adr-archive-20260901）：暂停发行成功置
    # stopped=True/stop_phase="pause"（web 层对 pause 相位豁免照常发 done）
    stopped: bool = False
    stop_phase: str = ""
    # 问即停：发行点签发的暂停卡标识（随 done payload 下发）
    pause_id: str = ""
    # 推理模型思考内容（五项修法批 4）：本循环最后一轮的 reasoning（数据源
    # = llm_call 第 5 元组 extra.reasoning_content）。回传/持久化由
    # settings.llm_reasoning_passthrough 统一闸门控制，默认关不外流
    reasoning_content: str = ""


# 防虚报检测（_STRUCTURE_CLAIM_RE/_claims_structure_done）归
# round_end_policies；测试导入路径已直连实现体（批次E 壳清偿）。


async def run_agent_loop(
    user_text: Union[str, List[Dict[str, Any]]],
    *,
    llm_call: LlmCall,
    context_builder: ContextBuilder,
    executor: "StateOperationExecutor",
    history: List[Dict[str, Any]],
    max_steps: Optional[int] = None,
    on_event=None,
    stream_hook: Optional[Callable[[str], Awaitable[None]]] = None,
    prelude_notes: Optional[List[tuple]] = None,
    pending_injector: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    user_id: str = "",
    stop_scope: str = "chat",
) -> AgentLoopResult:
    """on_event（可选）：async callable，接收 {"type": "step_started"/"actions_applied", ...}
    stream_hook（可选）：流式文本增量回调，每收到一段 LLM 文本就 await stream_hook(text)。
    user_text 可以是纯文本 str，也可以是多模态 content parts 列表（含 image_url）。
    stop_scope（端到端中断协议）：协作式停止标志作用域
    （SSE 直连="chat"；任务式传输=task_id），每步检查点读取，命中即干净收尾。
    max_steps（Q3）：None = 每步实时读 settings（前端可热调）；显式值钉死口径（测试）。
    """

    async def emit(event: Dict[str, Any]) -> None:
        if on_event:
            try:
                await on_event(event)
            except Exception as _e:
                # 承重接线遥测：事件通道静默降级不再只进 debug 日志，
                # 断线经 /api/agent/degradations 可见
                live_metrics.record_degradation("agent_loop.event_emit")
                logger.debug("[agent_loop] 忽略异常: {}", _e)

    result = AgentLoopResult()
    # Q3：显式传参钉死口径（测试/特殊编排）；None = 循环内每步实时读 settings
    explicit_max_steps = max_steps
    messages: List[Dict[str, Any]] = list(history) + [{"role": "user", "content": user_text}]

    # 协作式停止：循环开始无条件清除残留标志（上一任务被停止后
    # 未及清理时，不得误杀新任务；带代际的收尾清理见 _finalize_stop）；
    # 包装 stream_hook 跟踪是否已产生流式正文（阶段判定用）
    clear_stop(stop_scope)
    # 取消令牌贯穿 adapters：绑定上下文作用域令牌，长工具调用（视频生成
    # 轮询等）在检查点观察同一令牌协作退出；cancelled 判定内置同 scope
    # 停止标志观察，停止端点置标志即生效。inflight 登记保留为兜底
    # （已提交供应商侧的不可撤销任务），不再是唯一中断手段
    cancel_token = CancellationToken(scope=stop_scope)
    _cancel_bind = bind_cancel_token(cancel_token)
    _progress_token = None
    # 统一解绑：bind 之后主逻辑全部包在 try/finally 内，任何出口
    #（正常/stopped/异常/取消穿透）都经 finally 幂等解绑，不再分散收尾
    try:
        _streamed = {"on": False}
        if stream_hook is not None:
            async def _stream_hook_tracked(text: str) -> None:
                _streamed["on"] = True
                await stream_hook(text)
            _hook_use: Optional[Callable[[str], Awaitable[None]]] = _stream_hook_tracked
        else:
            _hook_use = None

        # Skill 解析唯一口径：项目 usedSkills 末位（单一实现）。
        #（原 executor.skill_name 恒空字段已随 2026-09-03 兼容层根除批删除：
        #  生产路径从未写入，恒走本兜底。）
        skill = fallback_skill_from_state(getattr(executor, "state", None) or {})

        # 链路追踪：记录本次对话执行过程
        tracer = AgentTracer.get_instance()
        user_preview = user_text if isinstance(user_text, str) else str(user_text)[:80]
        tracer.start_trace(user_preview, user_id=user_id)

        # 执行器进度通道双轨接线（统一循环级绑定，FC/文本轨同覆盖）。
        # 执行器内部批次边界（emit_timeline_note/emit_state_refresh/emit_progress）
        # 经此通道实时推时间线子项与故事板刷新——卡片一张张流式亮，不再结束才一把出现。
        # 解绑统一在 finally（幂等），异常路径也不再泄漏绑定。
        _progress_token = bind_progress_emitter(emit)

        def _stop_if_requested(phase: str) -> Optional[AgentStoppedError]:
            """检查点：读停止标志，命中返回携带阶段标记与代际 token 的异常对象
            （由调用方收尾；收尾清理按代匹配，不误清快速重连后的新停止请求）"""
            sid = current_stop_id(stop_scope)
            if sid:
                return AgentStoppedError(phase, result.steps, stop_id=sid)
            return None

        async def _finalize_stop(err: AgentStoppedError) -> AgentLoopResult:
            """用户停止的干净收尾：trace 步人账、发明确终态事件、清标志。
            不变式：任何中断都有痕迹（stopped 事件 + result.stopped）、都有出口
            （前端据终态事件落停止气泡并挂「继续刚才的任务」）；
            进度通道/取消令牌解绑统一在 finally。"""
            # 取消令牌先行触发：尚在执行中的 adapters 长任务（轮询/下载）
            # 在下一检查点协作退出，不等 task.cancel() 硬取消先落
            cancel_token.cancel()
            result.stopped = True
            result.stop_phase = err.phase
            _step_no = err.step or result.steps
            tracer.end_step(
                _step_no, actions_applied=0,
                finish_reason="stopped_by_user", token_usage=0,
            )
            logger.info(f"[AgentLoop] 已被用户停止：phase={err.phase} step={_step_no}")
            await emit({"type": SSE_STOPPED, "phase": err.phase, "step": _step_no})
            # 代际匹配清理：收尾期间若已有新停止请求（快速重连场景），不清
            if err.stop_id:
                clear_stop(stop_scope, err.stop_id)
            else:
                clear_stop(stop_scope)
            result.trace = tracer.finish_trace(total_actions=result.applied_actions)
            return result

        async def _await_llm_with_stop_guard(phase_when_streamed: str, extra_messages: Optional[List[Dict[str, Any]]] = None):
            """llm_call 调用统一守门：
            - AgentStoppedError（planner 层工具批执行前检查点抛出）→ 干净收尾；
            - CancelledError 硬取消落地：有停止标志 = 用户停止 → 收敛为干净收尾
              （阶段按已产生流式正文与否判定），无标志 = 异常取消原样上抛。
            返回 (None, 收尾结果) 表示已被停止（调用方直接返回），否则 (5 元组, None)。"""
            # 无附加消息时直传原列表引用：llm_call 内的回喂 append（read_* 全文
            # 渐进式披露回路）与惰性压缩都靠原地修改生效，拼新副本会丢回喂；
            # 带 extra_messages（坏输出重试 nudge）才拼副本，nudge 不持久化
            _msgs = messages if not extra_messages else messages + list(extra_messages)
            try:
                content, finish, fc_applied, plan_ms, extra = await llm_call(
                    system_prompt, _msgs, _hook_use)
                return (content, finish, fc_applied, plan_ms, extra), None
            except AgentStoppedError as _stop_err:
                return None, await _finalize_stop(_stop_err)
            except asyncio.CancelledError:
                sid = current_stop_id(stop_scope)
                if sid:
                    _ph = phase_when_streamed if _streamed["on"] else STOP_PHASE_THINKING
                    return None, await _finalize_stop(
                        AgentStoppedError(_ph, result.steps, stop_id=sid))
                cancel_token.cancel()
                raise
            except AdapterError as _adapter_err:
                # 恢复分派表 adapter_error 分支（action=escalate）：供应商错误
                # 到达此处时，要么 transient 重试已在适配层
                # （dispatch_chat_request/with_retry）耗尽，要么是 permanent
                # （鉴权/参数/拒答）——两类都不具循环内重试价值：
                # nudge 只用于模型侧空/畸形输出，循环侧不再对同一 transient
                # 反复 nudge。解绑由 finally 统一完成，此处原样上抛，
                # 由上层统一错误路径承接。
                _adapter_pol = recovery_for(
                    classify_step_failure(adapter_error=_adapter_err))
                cancel_token.cancel()
                logger.warning(
                    f"[AgentLoop] llm_call 供应商错误（kind={getattr(_adapter_err, 'kind', '')} "
                    f"retryable={getattr(_adapter_err, 'retryable', None)}）："
                    f"恢复策略={_adapter_pol.action}，不 nudge，直接上抛"
                )
                raise

        step = 0
        # 批 12：产出类被拒/失败的混合轮续轮已用预算（recovery_policy
        # productive_reject.max_retries；防「被拒-口播-续轮」打转烧满 max_steps）
        productive_reject_rounds = 0
        while True:
            # Q3：多步上限每步实时读 settings（前端全局设置页热更新即刻生效，
            # 运行中任务调高上限可继续推进）；显式传参钉死口径优先。
            max_steps = explicit_max_steps if explicit_max_steps is not None else current_max_steps()
            step += 1
            if step > max_steps:
                # 防御性出口：正常路径在步内 break（达上限时已发警告与「继续完成」按钮）
                break
            result.steps = step
            tracer.start_step()
            # 检查点 1（模型调用前）：上轮工具批已完成、本轮思考未开始，
            # 命中即思考阶段停止；不改变正常路径行为（无标志时零开销）
            _stop_err = _stop_if_requested(STOP_PHASE_THINKING)
            if _stop_err is not None:
                return await _finalize_stop(_stop_err)
            if step == 1:
                # 前奏明细：读 Skill/文档等准备动作记入第一步时间线
                # （live 与持久化同条目；唯一消费方 = 本循环）
                await emit_prelude_events(
                    prelude_notes,
                    lambda name, summary, ms, ok: tracer.record_action(name, summary, ms, ok),
                    emit,
                )
            await emit({"type": SSE_STEP_STARTED, "step": step, "max_steps": max_steps})
            if step > 1:
                # 多步循环"静默期"提示：上一步工具执行完到本步首 token 之间可能耗时数十秒，
                # 前端状态栏需明确告知正在进行第几轮思考（status 事件全链路已透传）
                await emit(status_event(
                    "agent.roundThinking",
                    f"第 {step - 1} 轮操作已完成，继续思考中（第 {step}/{max_steps} 轮）…",
                    {"prev": step - 1, "step": step, "max": max_steps},
                ))
            # 步间注入：任务执行期间收到的用户引导消息在上一步操作完成、
            # 本步 LLM 调用之前送达；首步尚无操作可打断，一律不注入
            if step > 1 and pending_injector is not None:
                try:
                    pending_items = pending_injector() or []
                except Exception:
                    pending_items = []
                for item in pending_items:
                    gid = str(item.get("id") or "")
                    gtext = str(item.get("text") or "").strip()
                    if not gtext:
                        continue
                    messages.append({
                        "role": "user",
                        "content": (
                            f"（任务执行期间收到您的指令：{gtext}）"
                            "请优先处理；若为提问先回答，处理完继续原任务。"
                        ),
                    })
                    await emit({
                        "type": "guidance_injected",
                        "id": gid,
                        "text": gtext,
                    })
            system_prompt = context_builder()  # 每步刷新，让 LLM 看到上一步执行后的最新状态

            # 过程时间线：模型推理轮本身也作为操作条目可见（仅创作型
            # 交接轮进入本循环，文案为节点内创作语义，非确定性阶段规划）
            await emit({
                "type": SSE_TOOL_STARTED,
                "id": f"llm-s{step}",
                "name": "model_reasoning",
                "summary": f"模型创作规划（节点内第 {step} 轮）",
            })
            # 规划条目先占位入 trace（保证持久化顺序 = live 顺序：规划→工具），
            # 耗时在 llm_call 返回后补填
            _plan_rec = tracer.record_action(
                "model_reasoning", f"模型创作规划（节点内第 {step} 轮）", 0.0, True,
            )
            content, finish_reason, fc_applied, plan_ms, fc_extra = (None, "", 0, 0.0, {})
            _unpacked, _stopped_result = await _await_llm_with_stop_guard(STOP_PHASE_STREAMING)
            if _stopped_result is not None:
                return _stopped_result
            content, finish_reason, fc_applied, plan_ms, fc_extra = _unpacked
            plan_total = float(plan_ms or 0.0)
            # 透明度兑现：本轮 token 用量入账 trace（轮次账单数据源）
            step_tokens = int((fc_extra or {}).get("token_usage") or 0)
            # P2-1 KV-cache 遥测：本轮前缀缓存命中 token 同步入账 step trace
            step_cached = int((fc_extra or {}).get("cached_tokens") or 0)
            # 推理模型思考内容（五项修法批 4）：末轮胜出，随结果上抛
            result.reasoning_content = str((fc_extra or {}).get("reasoning_content") or "")
            # 检查点 2（模型调用返回后）：FC 工具批已在 llm_call 内执行完毕，
            # 此时命中按刚经历的阶段标记（工具批/流式输出/思考）干净退出
            _stop_err = _stop_if_requested(
                STOP_PHASE_TOOL_EXECUTING if fc_applied > 0
                else (STOP_PHASE_STREAMING if _streamed["on"] else STOP_PHASE_THINKING)
            )
            if _stop_err is not None:
                return await _finalize_stop(_stop_err)

            # 规划耗时只算纯模型规划：FC 工具执行时间由各工具条目独立展示，
            # 不再把工具耗时叠进规划行导致「规划很慢」的错觉
            await emit({
                "type": SSE_TOOL_FINISHED,
                "id": f"llm-s{step}",
                "ok": True,
                "elapsed_ms": round(plan_total, 1),
                "result_summary": f"Agent 规划完成（第 {step} 轮）",
            })
            _plan_rec["elapsed_ms"] = round(plan_total, 1)
            # 撞帽/判空收轮语义（五项修法批 2，用户裁决「判空 = 正常收轮」）：
            # 空响应经恢复分派表按 finish_reason 分流两键
            # （output_truncated=输出预算截断 / bad_output=真空响应），统一动作
            # end_with_notice——收轮 + 用户可见提示 + retry 芯片，绝不原样重试
            # （同输入重跑无信息增益必现同结局，4444 事故根因②③；dsh 同语义）。
            # recovery_for 即分派表承接点：键未登记显式 KeyError（禁静默兜底）。
            # 守卫语义：fc_applied>0 的工具轮、暂停确认轮（workflow_pause 自身
            # 计入 fc_applied 且正文有确认文案）、发起过调用的全拒收轮
            # （had_fc_calls，批 9：拒因回喂必须被下一轮消费）均不入本分支。
            _had_fc_calls = bool((fc_extra or {}).get("had_fc_calls"))
            if not str(content or "").strip() and fc_applied == 0 and not _had_fc_calls:
                _kind = classify_step_failure(
                    content=content, fc_applied=fc_applied, finish_reason=finish_reason)
                recovery_for(_kind)
                if finish_reason == "length":
                    result.text = (
                        "本轮生成在输出预算处被截断（思考与正文共用同一额度），"
                        "未产出可见回复；请重试，若反复出现可降低本步任务规模。"
                    )
                    result.warnings.append(
                        f"第 {step} 轮生成在输出预算处被截断（finish_reason=length），已收轮")
                    _bad_finish = "output_truncated"
                else:
                    result.text = (
                        "输出异常：模型返回空响应且无工具调用；请重试或检查模型配置。"
                    )
                    result.warnings.append(
                        f"第 {step} 轮模型返回空响应（无正文无工具调用），已收轮")
                    _bad_finish = "bad_output"
                # 一键重试按钮（机械重发上一条用户消息，零模型猜测）
                result.suggested_actions.append({"kind": "retry", "label": "重试", "value": ""})
                tracer.end_step(step, actions_applied=0, finish_reason=_bad_finish,
                                token_usage=step_tokens, cached_tokens=step_cached)
                break

            if finish_reason == "length":
                result.warnings.append(
                    f"第 {step} 轮回复被 max_tokens 截断，工具调用/正文可能不完整"
                )

            # 结构化暂停确认：本轮 FC 批经 workflow_pause 产生
            fc_confirmation = str((fc_extra or {}).get("confirmation") or "")
            fc_confirmation_options = list((fc_extra or {}).get("confirmation_options") or [])
            fc_pause_id = str((fc_extra or {}).get("pause_id") or "")
            # 批 9 · 回合终止盲区修复：模型本轮是否发起过工具调用
            #（全拒收轮 fc_applied=0 但调用发生过，不能按纯文本轮收尾）
            had_fc_calls = _had_fc_calls

            # FC 路径：tool_calls 已在 llm_call 内部执行；正文原样可见（无需清洗）。
            # 批 9：发起过调用的轮（含全被闸拒收）一律走 FC 回喂继续——
            # 拒因（含"先 workflow_pause 请求确认"指引）已在 messages 里，
            # 终止回合会让指引永远到不了模型（9999 死锁根因）。
            if fc_applied > 0 or fc_confirmation or fc_pause_id or had_fc_calls:
                result.applied_actions += fc_applied
                if fc_applied:
                    await emit({"type": SSE_ACTIONS_APPLIED, "step": step, "count": fc_applied})
                visible = (content or "").strip()
                if visible:
                    result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible
                logger.info(
                    f"[AgentLoop] step={step} fc_applied={fc_applied} "
                    f"confirm={bool(fc_confirmation)} finish={finish_reason or '-'}"
                )
                if fc_confirmation or fc_pause_id:
                    # 虚报审计：FC 确认轮同样承重——声称完成但产物为空 →
                    # 只附警告不拦人（系统不没收模型暂停）。
                    # 批 12 对账扩展：产物族由 _PRODUCT_AUDIT 声明（结构/规格），
                    # 1000 实证「口播已写入制片规格而规格未落盘」同样要抓。
                    _unbacked = claims_unbacked_products(
                        visible, fc_confirmation, state=executor.state)
                    if _unbacked:
                        result.warnings.append(
                            "检测到虚报：正文声称已完成" + "、".join(_unbacked)
                            + "，但项目状态中对应产物实际缺失；"
                            "已按用户确认语义保留当前暂停（系统不没收模型暂停）。"
                        )
                    # 暂停等待用户确认：终止循环，把确认请求（含候选选项）带回给前端
                    result.confirmation = fc_confirmation
                    result.confirmation_options = fc_confirmation_options
                    result.pause_id = fc_pause_id
                    # 问即停：暂停发行成功 = 本轮结束、控制流冻结；
                    # 复用协作式停止通道标记（stop_phase="pause"，非用户停止；
                    # web 层对 pause 相位豁免，照常走成功路径发 done）
                    result.stopped = True
                    result.stop_phase = "pause"
                    # 三通道分离 B：超长 pause message 原文进正文通道
                    # （成果展示归正文；判重内置，防与模型 prose 重复）
                    _pause_overflow = str((fc_extra or {}).get("pause_overflow") or "").strip()
                    if _pause_overflow and _pause_overflow not in (result.text or ""):
                        result.text = (
                            f"{result.text}\n\n{_pause_overflow}".strip()
                            if result.text else _pause_overflow
                        )
                    tracer.end_step(
                        step, actions_applied=fc_applied,
                        finish_reason=finish_reason or "confirmation",
                        token_usage=step_tokens, cached_tokens=step_cached,
                    )
                    break
                # 6 提前终止：模型明确 stop 且已产出可见文本 → 任务已完成，
                # 不再固定追加 LLM 总结调用（finish=tool_calls 或无文本时保留多步链）。
                # 批 9：全拒收轮例外——"自称完成"不可信（9999 实证：模型口播
                # "现在生成…"而调用全被闸拦下），拒因回喂必须被下一轮消费，
                # 让模型按指引自纠（发暂停卡/改参），max_steps 仍封顶。
                # 批 12 · 1000 正向修复：例外扩为「产出类调用被拒/失败的混合轮」
                # ——部分调用成功不代表产出落账（1000 实证：read_skill 成功 +
                # 写规格被拒，模型口播"已写入制片规格"假完成收尾）；续轮预算 =
                # recovery_policy productive_reject.max_retries（防打转），
                # 预算内续轮计数递增，超限走轮末收尾 + 警告 + 继续按钮。
                _all_rejected = had_fc_calls and fc_applied == 0
                _rejected_productive = bool(
                    (fc_extra or {}).get("rejected_productive_tools"))
                _productive_budget = recovery_for(
                    FAILURE_PRODUCTIVE_REJECT).max_retries
                _keep_alive = _all_rejected or (
                    _rejected_productive
                    and productive_reject_rounds < _productive_budget
                )
                if finish_reason in ("stop", "end_turn") and visible and not _keep_alive:
                    if _rejected_productive:
                        # 批 12：续轮预算耗尽仍自称完成——明确告知用户哪些
                        # 产出没落账（正文完成说法不可信，以工作台实际为准）
                        result.warnings.append(
                            "部分产出类操作未能执行（被拦截或失败）："
                            + "、".join(
                                (fc_extra or {}).get("rejected_productive_tools") or [])
                            + "；相关产物未落账，正文中的完成说法请以工作台实际产物为准。"
                        )
                    tracer.end_step(step, actions_applied=fc_applied, finish_reason="fc_done",
                                    token_usage=step_tokens, cached_tokens=step_cached)
                    break
                if (finish_reason in ("stop", "end_turn") and visible
                        and _keep_alive and _rejected_productive
                        and not _all_rejected):
                    # 例外续轮真正行使时才计预算（finish=tool_calls 的多步链轮
                    # 本就续轮，不消费 productive_reject 预算）
                    productive_reject_rounds += 1
                if step == max_steps:
                    result.warnings.append(f"已达到多步上限（{max_steps} 轮），循环终止")
                    result.suggested_actions.append(
                        {"kind": "continue", "label": "继续完成", "value": "继续完成"})
                    tracer.end_step(step, actions_applied=fc_applied, finish_reason="max_steps",
                                    token_usage=step_tokens, cached_tokens=step_cached)
                    break
                tracer.end_step(step, actions_applied=fc_applied,
                                finish_reason=finish_reason or "fc_continue",
                                token_usage=step_tokens, cached_tokens=step_cached)
                # C2 标准工具消息顺序（对齐 Codex/DSH）：
                # assistant(tool_calls) → tool 结果们 → [图片 user] → STEP_FEEDBACK
                # assistant 消息携带本轮 tool_calls 原样（id 与 tool 消息配对；
                # content 为空在 tool_calls 形态下合法，占位文案退役）；
                # 问即停的悬挂调用（无 tool 结果）补「未执行」tool 消息，
                # 满足 OpenAI 语义「每个 tool_call 必须有对应 tool 消息」。
                _fc_calls = list((fc_extra or {}).get("_fc_tool_calls") or [])
                _asst: Dict[str, Any] = {"role": "assistant",
                                         "content": content or "",
                                         "tool_calls": _fc_calls}
                if settings.llm_reasoning_passthrough \
                        and str((fc_extra or {}).get("reasoning_content") or "").strip():
                    _asst["reasoning_content"] = str((fc_extra or {}).get("reasoning_content") or "")
                messages.append(_asst)
                _pending = list((fc_extra or {}).get("_pending_feedback_msgs") or [])
                if _fc_calls:
                    _answered = {str(m.get("tool_call_id") or "")
                                 for m in _pending if m.get("role") == "tool"}
                    for _tc in _fc_calls:
                        _cid = str((_tc or {}).get("id") or "")
                        if _cid and _cid not in _answered:
                            _pending.append({
                                "role": "tool", "tool_call_id": _cid,
                                "content": "（本批问即停，该调用未执行；等待用户回应后按其裁决处理）"})
                messages.extend(_pending)
                _step_fb = load_prompt_section("planner/feedback.md", "STEP_FEEDBACK")
                if _step_fb:
                    _step_content = _step_fb.replace("{{step}}", str(step)).replace("{{count}}", str(fc_applied))
                else:
                    logger.warning("[agent_loop] prompts/planner/feedback.md::STEP_FEEDBACK 分节缺失，使用最小占位")
                    _step_content = f"（系统）第 {step} 轮工具已执行，请继续。"
                messages.append({"role": "user", "content": _step_content})
                continue

            # 纯文本轮：模型本轮未发出工具调用，即本轮为面向用户的回复，
            # 循环进入收尾。正文拼接收纳由轮末策略 false_claim_audit 单一执行
            # （虚报/假停兜底等机械闸机同一策略表）。
            # I-1 收敛（2026-09-03）：工具成败回喂归 FC 轨逐步闭环
            # （fc_feedback.compose_failure_feedback），轮末失败汇总策略
            # 同批退役（生产唯一构造点即此处，FC 批轮在上方分支
            # 已 continue/break，永不到轮末；退役记录见 round_end_policies.py）。
            # 闸机拦截恢复已由 FC 轨 fc_gates reject_message 回喂闭环，
            # 循环层不再承载拦截列表通道（恢复分派表闸机分支同批退役）。
            _re_ctx = RoundEndContext(
                step=step,
                executor=executor,
                content=content,
                skill=skill,
                confirmation="",
                confirmation_options=[],
                wants_continue=False,
                # 可达性修复（2026-09-03）：纯文本收尾轮的 fc_applied 恒 0
                # （FC 批轮在上方分支已 continue/break），填真实累计工具数，
                # 假停判定「本回合确曾做过操作」才可达（不再写死死值）
                applied=result.applied_actions,
                result_text=result.text,
            )
            await run_round_end_policies(_re_ctx, emit, tracer=tracer)
            if _re_ctx.result_warnings:
                result.warnings.extend(_re_ctx.result_warnings)
            result.text = _re_ctx.result_text
            # fakestop：轮末策略机械追加的建议动作（仅当无既有建议时生效）
            if _re_ctx.suggested_actions and not result.suggested_actions:
                result.suggested_actions.extend(_re_ctx.suggested_actions)
            if _re_ctx.confirmation or _re_ctx.hard_break:
                # 轮末策略注入的暂停卡（规格审阅/规格收集等）：带回前端
                result.confirmation = _re_ctx.confirmation
                result.confirmation_options = _re_ctx.confirmation_options
                tracer.end_step(
                    step, actions_applied=0,
                    finish_reason=_re_ctx.hard_break_finish or "confirmation",
                    token_usage=step_tokens, cached_tokens=step_cached,
                )
                break
            # 正常收尾（批 3 · B4：状态驱动的"下一步建议"已退役，
            # "下一步"由模型聊天自述；建议动作只剩失败重试/假停继续）
            tracer.end_step(step, actions_applied=0, finish_reason=finish_reason or "stop",
                            token_usage=step_tokens, cached_tokens=step_cached)
            break
    except GenerationCancelled:
        # 取消穿透闭环：工具/adapters 检查点协作退出（GenerationCancelled）
        # 收敛 _finalize_stop 同款收尾：end_step + stopped 事件 + finish_trace；
        # 解绑统一在 finally
        # 代际快照：收尾期间若已有新停止请求（快速重连场景），不误清
        sid = current_stop_id(stop_scope)
        cancel_token.cancel()
        result.stopped = True
        result.stop_phase = STOP_PHASE_TOOL_EXECUTING
        _step_no = result.steps
        AgentTracer.get_instance().end_step(
            _step_no, actions_applied=0,
            finish_reason="cancelled_by_user", token_usage=0,
        )
        logger.info(f"[AgentLoop] 生成任务已被取消：step={_step_no}")
        await emit({"type": SSE_STOPPED, "phase": STOP_PHASE_TOOL_EXECUTING, "step": _step_no})
        clear_stop(stop_scope, sid)
        result.trace = AgentTracer.get_instance().finish_trace(
            total_actions=result.applied_actions)
        # 与 _finalize_stop 同语义直接返回：不再落空文本兜底文案
        return result
    except Exception as _failure_exc:
        # 失败现场 trace 归档（审计 §2.5 闭环）：异常上抛前把已完成步与
        # 失败摘要落账，重试带上下文续跑（web/chat_retry_context）据此
        # 还原进度；归档失败不掩盖原异常，原样上抛由上层错误路径承接。
        try:
            _t = AgentTracer.get_instance()
            _t.record_error(str(_failure_exc))
            # 循环内已完成过该 step 的 end_step（如异常发生在归档之后）时，
            # 不重复记同一 step 号（末条相等即跳过），只落失败摘要与归档。
            _cur = _t._current
            _last_done = _cur.steps[-1].step if (_cur and _cur.steps) else 0
            if _last_done != (result.steps or 1):
                _t.end_step(
                    result.steps or 1, actions_applied=0, finish_reason="error",
                )
            result.trace = _t.finish_trace(total_actions=result.applied_actions)
        except Exception as _archive_e:
            logger.debug("[agent_loop] 失败现场 trace 归档失败（忽略）: {}", _archive_e)
        raise
    finally:
        # 统一解绑（幂等）：任何出口都经此收尾，不再有分散解绑点
        unbind_progress_emitter(_progress_token)
        unbind_cancel_token(_cancel_bind)
    if not result.text:
        if result.confirmation:
            # 暂停轮无正文兜底：用暂停说明作为可见回复，
            # 永远不向用户展示「模型返回了空内容」这类误导文案
            result.text = result.confirmation
        elif result.applied_actions:
            # 操作已在各轮实时写入工作台，只是模型没输出总结文字：
            # 明确告知操作数量，避免用户误以为什么都没发生。
            result.text = (
                f"已执行 {result.applied_actions} 个操作，故事板与当前预览已更新（模型未输出总结文字）。"
            )
        else:
            # 用户腔兜底（空响应不是用户的错，给出明确下一步）；
            # 文案外置 feedback.md::EMPTY_RESPONSE_FALLBACK（指令收敛，Rule6）
            # M-2：外置分节缺失时不内联正式文案，仅 warning + 最小占位
            _fallback_text = load_prompt_section(
                "planner/feedback.md", "EMPTY_RESPONSE_FALLBACK")
            if not _fallback_text:
                logger.warning("[agent_loop] prompts/planner/feedback.md::EMPTY_RESPONSE_FALLBACK 分节缺失，使用最小占位")
                _fallback_text = "（本步无输出）"
            result.text = _fallback_text
            # 一键重试按钮替代手打「重试」（机械重发上一条用户消息）
            result.suggested_actions.append({"kind": "retry", "label": "重试", "value": ""})
    result.trace = tracer.finish_trace(total_actions=result.applied_actions)
    return result
