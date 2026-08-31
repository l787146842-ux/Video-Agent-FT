"""
TurnExecutor — 单轮 LLM 调用 + FC 响应消费 + 回喂治理。

职责边界（内聚三件）：
- 单轮执行 llm_call：流式/非流式主模型调用、协作式停止检查点、
  FC tool_calls 响应处理（经入口层 _handle_fc_response 委托执行）
- 回喂治理（会话压缩触发点）：read_* 全文回喂入库前的惰性压缩、
  旧轮图片剥离（vision token 治理）、Skill 流程提醒追加
- 上下文预算装配：tool-result 消化 → token 预算截断 → 降级保险丝
  （context_window 按模型名查表，缺省回落全局配置）

依赖方向：planner → turn_executor 单向；本模块不 import planner
（避免循环依赖），持入口层实例引用，轮级属性（_excluded_tools/
_system_degrader/_chat_thinking_level 等）在 handle_message 重置后
调用时读取。架构红线：本模块零 video_agent.web 导入；web 能力一律
由 planner 入口层经 core/ports.py 端口装配后透传。
"""
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from src.video_agent.adapters.base_chat import ChatResponse, StreamChunk
from src.video_agent.config import settings
from src.video_agent.core.fc_tool_runner import (
    compress_prior_feedback,
    digest_projected_tool_results,
    format_tool_results,
    should_compress_feedback,
    strip_prior_feedback_images,
)
from src.video_agent.core.live_metrics import record_cache_usage, record_live_context
from src.video_agent.core.live_metrics import record_budget_breakdown
from src.video_agent.core import round_compact
from src.video_agent.core.sse_events import SSE_REASONING_DELTA, SSE_STATUS, status_event
from src.video_agent.core.stop_signal import (
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
        self._skill_reminder: str = ""
        self._tracer: Optional[AgentTracer] = None

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
        skill_reminder: str,
    ) -> None:
        """装配本轮状态（handle_message 每轮调用一次；收集器跨多步共享，
        轮末由 assemble_response 统一合并）。"""
        self._context = context
        self._gate_override_scope = gate_override_scope
        self._collectors = collectors
        self._on_event = on_event
        self._skill_reminder = skill_reminder
        self._tracer = AgentTracer.get_instance()

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
        （context-usage 端点暴露，状态注入占比纳入监控）。只记不阻。"""
        try:
            record_budget_breakdown(
                getattr(getattr(self.planner, "state_manager", None),
                        "active_project_id", "") or "",
                {
                    "system": estimate_tokens(system or ""),
                    "history": estimate_messages_tokens(history_msgs),
                    "state": estimate_tokens(state_tail or ""),
                    "tools": estimate_tokens(
                        json.dumps(tools_schema, ensure_ascii=False)) if tools_schema else 0,
                    "total": estimate_messages_tokens(full_messages),
                    "budget": max_tokens,
                },
            )
        except Exception as _e:
            logger.debug(f"[TurnExecutor] 预算分配账记录忽略: {_e}")

    def _raise_if_context_overflow(
        self, full_messages: List[Dict[str, Any]], max_tokens: int,
    ) -> None:
        """第 5 批（Q7）：超预算不裸放行——四级保险丝
        （轮组压缩→轮组截断→状态降级→system 降级）用尽仍超预算时，
        policy=error（默认）明确报错不发请求，替代旧版 warning 照发；
        policy=warn 回拨旧行为（回滚开关）。"""
        if str(settings.context_overflow_policy).strip().lower() != "error":
            return
        final = estimate_messages_tokens(full_messages)
        if final <= max_tokens:
            return
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
        # 指针（最近 2 轮回喂保留原文；TOOL_RESULT_DIGEST_CHARS=0 一键关）
        digest_projected_tool_results(
            full_messages, int(settings.tool_result_digest_chars))
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

        tools_schema = (
            p.tool_manager.get_all_tool_schemas(exclude=p._excluded_tools)
            if p.llm_adapter.supports_function_calling else None
        )
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
        # tool-result 消化：同 call_llm（已投影结果超阈值行换指针）
        digest_projected_tool_results(
            full_messages, int(settings.tool_result_digest_chars))
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

        tools_schema = None
        if p.llm_adapter.supports_function_calling:
            tools_schema = p.tool_manager.get_all_tool_schemas(exclude=p._excluded_tools)
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
                    tracer.record_reasoning(chunk.text)
                    if self._on_event is not None:
                        await self._on_event({"type": SSE_REASONING_DELTA, "text": chunk.text})
                elif chunk.type == "tool_call":
                    stream_tool_calls.append({
                        "id": f"call_stream_{len(stream_tool_calls)}",
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
                                    cached_tokens=_stream_cached_tokens)
            plan_ms = (time.monotonic() - _t_plan) * 1000
        else:
            response = await self.call_llm(system_prompt, messages)
            plan_ms = (time.monotonic() - _t_plan) * 1000

        # P2-1 KV-cache 遥测：本轮命中样本入滚动窗口（汇聚命中率由
        # live_metrics 承担，context-usage 端点暴露）；无 usage 时静默不入样
        record_cache_usage(
            getattr(getattr(self.planner, "state_manager", None), "active_project_id", "") or "",
            getattr(response, "prompt_tokens", 0),
            getattr(response, "cached_tokens", 0),
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
        # 渐进式披露的回路关键：read_* 工具读回的全文必须回喂进 messages，
        # 否则模型「读了个寂寞」，Skill 流程/规格约束根本不进上下文
        if tool_results:
            feedback = format_tool_results(tool_results)
            if feedback:
                if context.skill_name:
                    reminder = "\n" + self._skill_reminder
                    if isinstance(feedback, list):
                        feedback = feedback + [{"type": "text", "text": reminder}]
                    else:
                        feedback += reminder
                # token 治理：新轮次回喂入库前，把更早轮次的 read_* 全文
                # 回喂压缩为一句话占位，避免多份全文在 messages 里叠加计费。
                # 惰性压缩（质量优化）：仅当消息总量逼近 token 预算时才压，
                # 短对话保留全文；选中 Skill 正文经 read_* 回喂，同样落入压缩面（轻量状态块在 system 不受影响）
                if should_compress_feedback(messages, self.context_window()):
                    compress_prior_feedback(messages)
                # 按需调图：新回喂带图片时，先剥离旧轮已加载的图片，
                # 上下文始终只保留最新轮次的画面（vision token 治理）
                if isinstance(feedback, list):
                    strip_prior_feedback_images(messages)
                messages.append({"role": "user", "content": feedback})
        _extra: Dict[str, Any] = {}
        # 透明度兑现：本轮 token 用量随 5 元组上抛（agent_loop 入账 trace）
        _extra["token_usage"] = int(getattr(response, "token_usage", 0) or 0)
        # P2-1 KV-cache 遥测：缓存命中同随 5 元组上抛（agent_loop 入账 trace step）
        _extra["cached_tokens"] = int(getattr(response, "cached_tokens", 0) or 0)
        if _confirm_holder.get("message") or _confirm_holder.get("pause_id"):
            _extra.update({
                "confirmation": _confirm_holder.get("message") or "",
                "confirmation_options": _confirm_holder.get("options") or [],
                # 三通道分离 B：超长 pause message 原文随正文下发
                "pause_overflow": _confirm_holder.get("overflow") or "",
                # 问即停（ADR-0006）：发行点签发的 pause_id 随 5 元组上抛，
                # 供 agent_loop 带回前端与 _issue_pause 幂等登记
                "pause_id": _confirm_holder.get("pause_id") or "",
            })
        return content, finish, fc_applied, plan_ms, _extra
