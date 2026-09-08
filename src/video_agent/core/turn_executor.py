"""
TurnExecutor — 单轮 LLM 调用 + FC 响应消费 + 回喂治理。

职责边界（内聚三件）：
- 单轮执行 llm_call：流式/非流式主模型调用、协作式停止检查点、
  FC tool_calls 响应处理（经入口层 _handle_fc_response 委托执行）
- 回喂治理（会话压缩触发点）：read_* 全文回喂入库前的惰性压缩、
  旧轮图片剥离（vision token 治理）
- 上下文预算装配：tool-result 消化 → token 预算截断 → 降级保险丝
  （context_window 按模型名查表，缺省回落全局配置）

依赖方向：planner → turn_executor 单向；本模块不 import planner
（避免循环依赖），持入口层实例引用，轮级属性（_excluded_tools/
_system_degrader/_chat_thinking_level 等）在 handle_message 重置后
调用时读取。架构红线：本模块零 video_agent.web 导入；web 能力一律
由 planner 入口层经 core/ports.py 端口装配后透传。
"""
import hashlib
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from src.video_agent.core.chat_port import ChatResponse, StreamChunk
from src.video_agent.config import settings
from src.video_agent.core.fc_feedback import (
    compress_prior_feedback,
    digest_projected_tool_args,
    digest_projected_tool_results,
    format_tool_result_messages,
    format_tool_results,
    should_compress_feedback,
    strip_prior_feedback_images,
)
from src.video_agent.utils.live_metrics import (
    get_budget_breakdown,
    record_cache_usage,
    record_live_context,
)
from src.video_agent.utils.live_metrics import record_budget_breakdown
from src.video_agent.core import round_compact
from src.video_agent.core import session_log
from src.video_agent.core.sse_events import SSE_REASONING_DELTA, SSE_STATUS, status_event
from src.video_agent.utils.stop_signal import (
    STOP_PHASE_TOOL_EXECUTING,
    AgentStoppedError,
    current_stop_id,
    is_stop_requested,
)
from src.video_agent.core.token_budget import (
    context_window_for_model,
    estimate_messages_tokens,
    estimate_tokens,
    truncate_messages,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.core.agent_loop import current_max_steps
from src.video_agent.exceptions import GenerationError


class TurnExecutor:
    """单轮执行器（职责边界见模块 docstring）。

    构造时持 Planner 实例引用；每轮 handle_message 先重置轮级属性，
    再 bind_turn 装配本轮收集器后把 llm_call 委托进 run_agent_loop。
    记忆摘要路径复用 call_llm（预算管线与主调用同一实现）。
    直驱自洽：未经 bind_turn 直接调 llm_call（测试/工具）时，
    tracer 现场回落 get_instance()、收集器回落构造期默认空列表
    （仅 _context 需调用方提供）。
    """

    def __init__(self, planner: Any):
        self.planner = planner
        # 轮级装配位（bind_turn 写入；未装配时回落下方默认值，直驱不抛异常）
        self._context: Any = None
        self._gate_override_scope: Any = False
        self._collectors: Dict[str, List[Any]] = self._default_collectors()
        self._on_event: Optional[Any] = None
        self._tracer: Optional[AgentTracer] = None
        # turn_budget 客观步数计数器（每次 llm_call 自增，经 context.step_info 注入状态尾部）
        self._step_count: int = 0

    @staticmethod
    def _default_collectors() -> Dict[str, List[Any]]:
        """收集器默认空列表（未 bind_turn 直驱时的自洽回落；生产路径
        每轮由 bind_turn 换装 handle_message 定义的跨步共享列表）"""
        return {
            "image_urls": [],
            "chat_inserts": [],
            "action_log": [],
            "confirmation_options": [],
            "docs_written": [],
            "fc_warnings": [],
        }

    def bind_turn(
        self,
        *,
        context: Any,
        gate_override_scope: Any,
        collectors: Dict[str, List[Any]],
        on_event: Optional[Any],
    ) -> None:
        """装配本轮状态（handle_message 每轮调用一次；收集器跨多步共享，
        轮末由 assemble_response 统一合并）。"""
        self._context = context
        self._gate_override_scope = gate_override_scope
        self._collectors = collectors
        self._on_event = on_event
        self._tracer = AgentTracer.get_instance()
        self._step_count = 0

    # ---------- 上下文预算 ----------

    def context_window(self) -> int:
        """当前模型的上下文窗口（按模型名查表，缺省回落全局配置）"""
        p = self.planner
        model = getattr(p.llm_adapter, "model", "") if p.llm_adapter else ""
        return context_window_for_model(model, provider_id=getattr(p, "chat_provider", "") or "")

    def _state_tail_message(self) -> str:
        """状态上下文 history 尾部消息（user 通道；单一事实源 = prompt_builder）。

        状态 JSON/工具边界说明/故事板进度已移出 system 段，改在每次调用时
        作为 history 最后一条消息注入：system（含 Skill 块）成为跨步稳定前缀
        （供应商 KV-cache 友好）；消息只存在于当次请求，不入持久化历史，
        也不进会话压缩采样面。context 缺失（直驱/独立）时不组装 → 零增量。"""
        ctx = self._context
        pb = getattr(self.planner, "_prompt_builder", None)
        if ctx is None or pb is None:
            return ""
        try:
            return pb.build_state_tail_message(ctx)
        except Exception:
            return ""

    def _degrade_state_tail(
        self,
        full_messages: List[Dict[str, Any]],
        max_tokens: int,
        state_tail: str,
    ) -> List[Dict[str, Any]]:
        """预算保险丝：截断后仍超预算时用降级状态（只留组标题/计数）
        重建尾部状态消息。状态上下文移出 system 段后，降级重建点同步迁移：
        原 system_degrader 只负责 system 本体。只记录不阻断主链。"""
        if not state_tail or not full_messages:
            return full_messages
        if estimate_messages_tokens(full_messages) <= max_tokens:
            return full_messages
        ctx = self._context
        deg_builder = getattr(ctx, "degraded_state_builder", None) if ctx is not None else None
        pb = getattr(self.planner, "_prompt_builder", None)
        if deg_builder is None or pb is None:
            return full_messages
        try:
            degraded = pb.build_state_tail_message(ctx, state_builder_override=deg_builder)
        except Exception:
            return full_messages
        if degraded and degraded != state_tail and full_messages[-1].get("content") == state_tail:
            full_messages[-1] = {"role": "user", "content": degraded}
            logger.warning(
                f"[TurnExecutor] 状态尾部消息超预算，已降级重建（预算 {max_tokens} tokens）")
            try:
                (self._tracer or AgentTracer.get_instance()).record_context_event(
                    "degrade", f"history 尾部状态消息降级重建（预算 {max_tokens} tokens）")
            except Exception:
                pass
        return full_messages

    def _record_budget_breakdown(
        self, system: str, history_msgs: List[Dict[str, Any]], state_tail: str,
        tools_schema: Any, full_messages: List[Dict[str, Any]], max_tokens: int,
    ) -> None:
        """第 5 批（Q6）：每轮 token 分配账记入 live 注册表
        （context-usage 端点暴露，状态注入占比纳入监控）。只记不阻。
        批 D：同步记录工具清单数量与指纹（sha1 前 16 位）入 budget 与
        trace——跨步 tools_fp 变化 = 工具集漂移 = KV 前缀击穿点观测。"""
        try:
            tools_json = json.dumps(tools_schema, ensure_ascii=False) if tools_schema else ""
            tools_fp = (
                hashlib.sha1(tools_json.encode("utf-8")).hexdigest()[:16]
                if tools_json else ""
            )
            record_budget_breakdown(
                getattr(getattr(self.planner, "state_manager", None),
                        "active_project_id", "") or "",
                {
                    "system": estimate_tokens(system or ""),
                    "history": estimate_messages_tokens(history_msgs),
                    "state": estimate_tokens(state_tail or ""),
                    "tools": estimate_tokens(tools_json) if tools_json else 0,
                    "tools_count": len(tools_schema) if tools_schema else 0,
                    "tools_fp": tools_fp,
                    "total": estimate_messages_tokens(full_messages),
                    "budget": max_tokens,
                },
            )
            if tools_fp:
                (self._tracer or AgentTracer.get_instance()).record_tools_fp(tools_fp)
        except Exception as _e:
            logger.debug(f"[TurnExecutor] 预算分配账记录忽略: {_e}")

    def _raise_if_context_overflow(
        self, full_messages: List[Dict[str, Any]], max_tokens: int,
    ) -> None:
        """第 5 批（Q7）/ 用户裁决 2026-09-01：保留四级保险丝（轮组压缩→
        轮组截断→状态降级→system 降级），拆除「超预算拦发」末级——
        默认（policy=warn）四级用尽仍超预算时记 warning 后照发，
        上游报上下文超长错误经 AdapterError 通道原样透传；
        policy=error 回拨开关（明确报错不发请求）。"""
        final = estimate_messages_tokens(full_messages)
        if final <= max_tokens:
            return
        policy = str(settings.context_overflow_policy).strip().lower()
        if policy == "error":
            try:
                (self._tracer or AgentTracer.get_instance()).record_context_event(
                    "overflow",
                    f"四级保险丝用尽仍超预算 {final}>{max_tokens} tokens，报错不发",
                )
            except Exception:
                pass
            raise GenerationError(
                f"上下文经压缩/截断/降级后仍超模型窗口（{final} > {max_tokens} tokens）。"
                "请清理草稿/规格文档、缩短上传素材，或换用更大窗口的模型后重试。"
            )
        # 默认：不拦发——记 warning + trace 后照发，上游报错原样透传
        logger.warning(
            f"[TurnExecutor] 四级保险丝用尽仍超预算 {final}>{max_tokens} tokens，"
            "照发（policy=warn，上游超长报错原样透传）")
        try:
            (self._tracer or AgentTracer.get_instance()).record_context_event(
                "overflow",
                f"四级保险丝用尽仍超预算 {final}>{max_tokens} tokens，警告后照发",
            )
        except Exception:
            pass

    async def call_llm(self, system: str, messages: List[Dict[str, Any]]) -> ChatResponse:
        """
        LLM 调用（§2.2）：支持 function calling 的 adapter 传入 tool schemas；
        不支持的供应商走纯文本调用。
        """
        p = self.planner
        full_messages = [{"role": "system", "content": system}] + messages
        # 状态上下文出 system：每次调用以 history 尾部消息（user 通道）注入，
        # system（含 Skill 块）成跨步稳定前缀；不入持久化历史/压缩采样面
        state_tail = self._state_tail_message()
        if state_tail:
            full_messages.append({"role": "user", "content": state_tail})
        # tool-result 消化：已投影进状态 JSON 的写类工具结果超阈值行替换为
        # 指针（最近 2 轮回喂保留原文；TOOL_RESULT_DIGEST_CHARS=0 一键关）；
        # B2：assistant tool_calls 大参数（report_markdown 等已落账全文）同口径消化
        digest_projected_tool_results(
            full_messages, int(settings.tool_result_digest_chars))
        digest_projected_tool_args(
            full_messages, int(settings.tool_result_digest_chars))
        # 工具结果修剪 pass（v4 批 E2，细案 §七）：压力命中（≥0.8×窗口）时
        # 双面修剪——内存面就地改写（本轮后续请求立即收益）+ 日志面替换事件
        # （下轮回放直接见修剪版，原文永留日志）；低于压力零动作（dsh 口径）
        _sess_cid = str(getattr(self._context, "session_conversation_id", "") or "")
        if _sess_cid:
            session_log.prune_pass(
                p.state_manager, _sess_cid, full_messages, self.context_window())
        # Token 预算截断：窗口按模型查表；system 自身超预算时走降级保险丝，
        # 尾部状态消息的降级重建见 _degrade_state_tail
        max_tokens = int(self.context_window() * settings.token_budget_ratio)
        # 第 5 批保险丝阶梯①（Q6/Q7）：截断前先对最旧轮组语义压缩
        # （消灭有损截断主触发源；失败静默回落截断链，零干扰主链）
        try:
            await round_compact.compact_oldest_round(
                full_messages, p.llm_adapter, max_tokens)
        except Exception as e:
            logger.debug(f"[TurnExecutor] 循环内压缩异常（忽略）: {e}")
        full_messages = truncate_messages(full_messages, max_tokens, system_degrader=p._system_degrader)
        full_messages = self._degrade_state_tail(full_messages, max_tokens, state_tail)
        self._raise_if_context_overflow(full_messages, max_tokens)
        # 实时上下文度量：截断后的真实消息记入 live 注册表，
        # context-usage 接口推理中即可看到用量随轮次增长
        record_live_context(p.state_manager.active_project_id, full_messages)
        # P2-6 可见指纹链：截断后的最终消息 = 模型实际所见，链式指纹入 trace；
        # 断言口径「凡入 llm_call 必入 trace」（无在场 trace 时告警，不中断）
        (self._tracer or AgentTracer.get_instance()).record_prompt_fingerprint(full_messages)

        if p.llm_adapter is None:
            # 无 adapter 时返回空响应
            return ChatResponse(content="", finish_reason="stop")

        tools_schema = p.tools_schema()
        self._record_budget_breakdown(
            system, messages, state_tail, tools_schema, full_messages, max_tokens)
        if tools_schema is not None:
            # 模式 A：标准 function calling（工具集按上下文裁剪）
            return await p.llm_adapter.chat(
                full_messages, tools=tools_schema, timeout=settings.llm_timeout,
                thinking_level=getattr(p, "_chat_thinking_level", "") or "",
            )
        # 模式 B：纯文本对话（adapter 不支持 function calling 的保底通道；
        # 不携带工具调用，文本轨不产生动作——动作通道唯一 = 工具调用）
        return await p.llm_adapter.chat(
            full_messages, timeout=settings.llm_timeout,
            thinking_level=getattr(p, "_chat_thinking_level", "") or "",
        )

    async def call_llm_stream(self, system: str, messages: List[Dict[str, Any]]) -> AsyncGenerator[StreamChunk, None]:
        """流式 LLM 调用"""
        p = self.planner
        full_messages = [{"role": "system", "content": system}] + messages
        # 状态上下文出 system：同 call_llm（流式/非流式两通道同口径）
        state_tail = self._state_tail_message()
        if state_tail:
            full_messages.append({"role": "user", "content": state_tail})
        # tool-result 消化：同 call_llm（已投影结果超阈值行换指针）；
        # B2：assistant tool_calls 大参数同口径消化
        digest_projected_tool_results(
            full_messages, int(settings.tool_result_digest_chars))
        digest_projected_tool_args(
            full_messages, int(settings.tool_result_digest_chars))
        # 工具结果修剪 pass：同 call_llm（流式/非流式同口径，v4 批 E2）
        _sess_cid_s = str(getattr(self._context, "session_conversation_id", "") or "")
        if _sess_cid_s:
            session_log.prune_pass(
                p.state_manager, _sess_cid_s, full_messages, self.context_window())
        # Token 预算截断：同 call_llm（含尾部状态消息降级重建）
        max_tokens = int(self.context_window() * settings.token_budget_ratio)
        # 第 5 批保险丝阶梯①：同 call_llm（流式/非流式同口径）
        try:
            await round_compact.compact_oldest_round(
                full_messages, p.llm_adapter, max_tokens)
        except Exception as e:
            logger.debug(f"[TurnExecutor] 循环内压缩异常（忽略）: {e}")
        full_messages = truncate_messages(full_messages, max_tokens, system_degrader=p._system_degrader)
        full_messages = self._degrade_state_tail(full_messages, max_tokens, state_tail)
        self._raise_if_context_overflow(full_messages, max_tokens)
        # 实时上下文度量：同 call_llm，推理中用量可见
        record_live_context(p.state_manager.active_project_id, full_messages)
        # P2-6 可见指纹链：同 call_llm（流式/非流式两通道同口径）
        (self._tracer or AgentTracer.get_instance()).record_prompt_fingerprint(full_messages)

        if p.llm_adapter is None:
            return

        tools_schema = p.tools_schema()
        self._record_budget_breakdown(
            system, messages, state_tail, tools_schema, full_messages, max_tokens)

        async for chunk in p.llm_adapter.chat_stream(
            full_messages, tools=tools_schema, timeout=settings.llm_stream_timeout,
            thinking_level=getattr(p, "_chat_thinking_level", "") or "",
        ):
            yield chunk

    # ---------- 状态事件发射 ----------

    async def _emit_status(self, text: str, key: str = "", params: Optional[Dict[str, Any]] = None) -> None:
        """推理过程可视化：把 FC 工具执行进度实时推给前端状态栏。
        固定文案携带 key+params（前端按 locale 翻译，text 兜底）。"""
        if self._on_event is not None:
            if key:
                await self._on_event(status_event(key, text, params))
            else:
                await self._on_event({"type": SSE_STATUS, "text": text})

    async def _emit_event(self, event: Dict[str, Any]) -> None:
        """过程时间线事件透传（tool_started/tool_finished）"""
        if self._on_event is not None:
            await self._on_event(event)

    # ---------- 单轮执行（run_agent_loop 的 llm_call 委托体） ----------

    async def llm_call(self, system_prompt: str, messages: List[Dict[str, Any]], hook=None) -> tuple:
        # 主模型调用计数（成本看板平均耗时口径）；未 bind_turn 直驱时
        # 现场回落单例
        tracer = self._tracer or AgentTracer.get_instance()
        tracer.record_llm_call()
        context = self._context
        # turn_budget 客观步数：每步自增，经 context.step_info 注入状态尾部（P3 纯数据）
        self._step_count += 1
        if context is not None:
            context.step_info = (self._step_count, current_max_steps())
        # 确认信号结构化直通——本轮 FC 批的暂停确认由
        # _handle_fc_response 写入本 holder，随 5 元组上抛 agent_loop，
        # 不再合成 studio-actions 文本块回绕解析（对齐 AskUserQuestion 范式）
        _confirm_holder: Dict[str, Any] = {}
        # 纯规划计时：只量模型流/调用本身，FC 工具执行时间
        # 不计入规划条目，避免规划行虚高掩盖工具耗时
        _t_plan = time.monotonic()
        # 流式路径：使用 chat_stream + hook 回调
        if hook:
            content_parts: List[str] = []
            finish = ""
            stream_tool_calls: List[Dict[str, Any]] = []
            # 推理模型思考内容累积（五项修法批 4）：思考回传的数据源之一
            reasoning_parts: List[str] = []
            # 透明度兑现：流内 usage 机会性收集（中继未下发则 0）
            _stream_usage_tokens = 0
            # P2-1 KV-cache 遥测：流内 prompt/缓存命中 token 同机会性收集
            _stream_prompt_tokens = 0
            _stream_cached_tokens = 0
            async for chunk in self.call_llm_stream(system_prompt, messages):
                # 协作式停止：流式消费中命中停止标志即提前断流，
                # 不再继续烧 token；后续阶段判定/收尾归 agent_loop 检查点
                if is_stop_requested(context.stop_scope):
                    break
                if chunk.type == "text_delta" and chunk.text:
                    content_parts.append(chunk.text)
                    # 确认走结构化 workflow_pause 工具——
                    # 正文原样透传，流式抑制器同批下账
                    await hook(chunk.text)
                elif chunk.type == "reasoning_delta" and chunk.text:
                    # 深度思考：记入 trace（持久化展示）+ 实时推给前端，不进 LLM 上下文
                    reasoning_parts.append(chunk.text)
                    tracer.record_reasoning(chunk.text)
                    if self._on_event is not None:
                        await self._on_event({"type": SSE_REASONING_DELTA, "text": chunk.text})
                elif chunk.type == "tool_call":
                    # C1：优先用供应商真实 tool_call id（tool role 结果配对用；
                    # 端点未下发时空串，回落合成 id 保持唯一性）
                    stream_tool_calls.append({
                        "id": chunk.tool_call_id or f"call_stream_{len(stream_tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": chunk.tool_name,
                            "arguments": json.dumps(chunk.tool_args, ensure_ascii=False),
                        },
                    })
                elif chunk.type == "done":
                    finish = chunk.finish_reason or "stop"
                    _stream_usage_tokens = int(getattr(chunk, "usage_tokens", 0) or 0)
                    _stream_prompt_tokens = int(getattr(chunk, "prompt_tokens", 0) or 0)
                    _stream_cached_tokens = int(getattr(chunk, "cached_tokens", 0) or 0)
            content = "".join(content_parts)
            response = ChatResponse(content=content, finish_reason=finish,
                                    tool_calls=stream_tool_calls,
                                    token_usage=_stream_usage_tokens,
                                    prompt_tokens=_stream_prompt_tokens,
                                    cached_tokens=_stream_cached_tokens,
                                    reasoning_content="".join(reasoning_parts))
            plan_ms = (time.monotonic() - _t_plan) * 1000
        else:
            response = await self.call_llm(system_prompt, messages)
            plan_ms = (time.monotonic() - _t_plan) * 1000

        # P2-1 KV-cache 遥测：本轮命中样本入滚动窗口（汇聚命中率由
        # live_metrics 承担，context-usage 端点暴露）；无 usage 时静默不入样。
        # v4-3：随样本快照 breakdown 分配账（70K 构成随 cache_metrics 落盘）
        _proj_id = getattr(getattr(self.planner, "state_manager", None),
                           "active_project_id", "") or ""
        record_cache_usage(
            _proj_id,
            getattr(response, "prompt_tokens", 0),
            getattr(response, "cached_tokens", 0),
            breakdown=get_budget_breakdown(_proj_id),
        )
        # 会话事件流镜像（v4 主刀批 E1，细案 §五）：每步 assistant 响应落流
        # （含 tool_calls/reasoning/usage）；reasoning 附着与 agent_loop 同闸门
        # （settings.llm_reasoning_passthrough）；绑定缺失（测试/非 studio）不落流
        _sess_cid = str(getattr(self._context, "session_conversation_id", "") or "")
        if _sess_cid:
            session_log.append_assistant_message(
                self.planner.state_manager, _sess_cid, step=self._step_count,
                content=str(getattr(response, "content", "") or ""),
                tool_calls=[
                    dict(tc) for tc in (getattr(response, "tool_calls", None) or [])
                    if isinstance(tc, dict)],
                reasoning_content=(
                    str(getattr(response, "reasoning_content", "") or "")
                    if settings.llm_reasoning_passthrough else ""),
                usage={
                    "prompt_tokens": int(getattr(response, "prompt_tokens", 0) or 0),
                    "cached_tokens": int(getattr(response, "cached_tokens", 0) or 0),
                    "completion_tokens": int(getattr(response, "token_usage", 0) or 0),
                },
            )

        # 检查点（工具批执行前）：模型已返回 tool_calls 但尚未执行，
        # 命中停止标志即抛 AgentStoppedError（agent_loop 捕获后干净收尾）；
        # 停止信号不经 fc_tool_runner 闸机传递，只在循环边界拦截
        if response.tool_calls and is_stop_requested(context.stop_scope):
            raise AgentStoppedError(STOP_PHASE_TOOL_EXECUTING,
                                    stop_id=current_stop_id(context.stop_scope))

        c = self._collectors
        content, finish, fc_applied, tool_results, fc_warnings = await self.planner._handle_fc_response(
            response,
            image_urls_collector=c["image_urls"],
            chat_inserts_collector=c["chat_inserts"],
            action_log_collector=c["action_log"],
            confirmation_options_collector=c["confirmation_options"],
            docs_written_collector=c["docs_written"],
            fc_warnings_collector=c["fc_warnings"],
            image_provider=context.image_generation_provider,
            image_aspect_ratio=context.image_generation_aspect_ratio,
            on_status=self._emit_status,
            on_event=self._emit_event,
            injected_skill=context.skill_name,
            selected_draft_id=context.selected_draft_id,
            selected_type=context.selected_type,
            gate_override=self._gate_override_scope,
            confirmation_collector=_confirm_holder,
        )
        # C2 标准 tool role 回喂（渐进式披露的回路关键）：工具结果不再伪装
        # user 消息，改为逐调用 {"role": "tool", "tool_call_id": ...} 消息，
        # 与 assistant.tool_calls 的 id 一一配对（对齐 Codex/DSH 格式）。
        # 组装后挂 _extra 由 agent_loop 轮末按标准顺序统一 append：
        # assistant(tool_calls) → tool 结果们 → [图片 user 消息] → STEP_FEEDBACK
        # （assistant(tool_calls) 必须先于 tool 消息，OpenAI 语义硬约束）。
        _extra: Dict[str, Any] = {}
        if tool_results:
            # token 治理：新轮次回喂组装前，把更早轮次的 read_* 全文
            # 回喂压缩为一句话占位，避免多份全文在 messages 里叠加计费。
            # 惰性压缩（质量优化）：仅当消息总量逼近 token 预算时才压，
            # 短对话保留全文；选中 Skill 正文经 read_* 回喂，同样落入压缩面（轻量状态块在 system 不受影响）
            if should_compress_feedback(messages, self.context_window()):
                compress_prior_feedback(messages)
            _tool_msgs, _image_msg = format_tool_result_messages(
                tool_results, messages=messages)
            _pending: List[Dict[str, Any]] = list(_tool_msgs)
            if _image_msg is not None:
                # 按需调图：新回喂带图片时，先剥离旧轮已加载的图片，
                # 上下文始终只保留最新轮次的画面（vision token 治理）
                strip_prior_feedback_images(messages)
                _pending.append(_image_msg)
            _extra["_pending_feedback_msgs"] = _pending
        # 透明度兑现：本轮 token 用量随 5 元组上抛（agent_loop 入账 trace）
        _extra["token_usage"] = int(getattr(response, "token_usage", 0) or 0)
        # P2-1 KV-cache 遥测：缓存命中同随 5 元组上抛（agent_loop 入账 step trace）
        _extra["cached_tokens"] = int(getattr(response, "cached_tokens", 0) or 0)
        # 推理模型思考内容（五项修法批 4）：流式累积 / 非流式捕获统一随
        # 5 元组上抛；是否回传进后续请求由 settings.llm_reasoning_passthrough
        # 统一闸门控制（agent_loop 附着点 + adapter 下发闸门）
        _extra["reasoning_content"] = str(getattr(response, "reasoning_content", "") or "")
        # 批 9 · 回合终止盲区修复：上抛"本轮模型是否发起过工具调用"。
        # 全拒收轮（发起过但 fc_applied=0）不能落进纯文本轮收尾——
        # 拒因回喂已在 messages 里，循环必须再走一轮让模型看到指引。
        _extra["had_fc_calls"] = bool(getattr(response, "tool_calls", None))
        # C2：本轮 tool_calls 原样上抛（agent_loop 轮末组 assistant.tool_calls
        # 消息，与 _pending_feedback_msgs 的 tool 消息按 id 配对）
        _extra["_fc_tool_calls"] = [
            dict(tc) for tc in (getattr(response, "tool_calls", None) or [])
            if isinstance(tc, dict)]
        # 批 12 · 1000 正向修复：本轮失败/被拒的「产出类」工具清单（按工具
        # 声明推导：detail_tier=expand 产出类 或 risk≥medium 结构写入，
        # workflow_pause 属关键交互非产物，排除；未注册工具 deny-by-default
        # 保守计入）。产出没落账而正文自称完成同样不可信——agent_loop 据此
        # 不按纯文本轮提前终止，让拒因被下一轮消费（自纠：发暂停卡/改参）。
        _rejected_productive: List[str] = []
        for _tr in tool_results or []:
            _n = str(( _tr or {}).get("name") or "")
            if not _n or _tr.get("ok") or _n == "workflow_pause":
                continue
            try:
                _tool = self.planner.tool_manager.get_tool(_n)
                _tier = str(getattr(_tool, "detail_tier", "") or "")
                _risk = str(getattr(_tool, "risk", "") or "")
            except Exception:
                _tier, _risk = "", "high"
            if _tier == "expand" or _risk in ("medium", "high"):
                if _n not in _rejected_productive:
                    _rejected_productive.append(_n)
        if _rejected_productive:
            _extra["rejected_productive_tools"] = _rejected_productive
        if _confirm_holder.get("message") or _confirm_holder.get("pause_id"):
            _extra.update({
                "confirmation": _confirm_holder.get("message") or "",
                "confirmation_options": _confirm_holder.get("options") or [],
                # 三通道分离 B：超长 pause message 原文随正文下发
                "pause_overflow": _confirm_holder.get("overflow") or "",
                # 问即停（决策史见 git tag adr-archive-20260901）：发行点签发的 pause_id 随 5 元组上抛，
                # 供 agent_loop 带回前端与 _issue_pause 幂等登记
                "pause_id": _confirm_holder.get("pause_id") or "",
            })
        return content, finish, fc_applied, plan_ms, _extra
