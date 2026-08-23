/* eslint-disable max-lines */ // 对话 store 核心（已登记 FRONTEND_WHITELIST）
import { createStore, produce } from 'solid-js/store';
import type { ChatMessage, SseDonePayload, RichContentPart, PendingDecisionPayload } from '@/types';
import { saveQueue, loadQueue } from '@/lib/chat/queue-storage';
import { t } from '@/lib/locale';
import { actionForKind, type ErrorPayload } from '@/lib/error-payload';
import {
  resetStreamFields, continueLastTaskSuggestion, buildStopMessages,
} from '@/lib/stream-finalize';
import type { StopPhase, StopInflightItem } from '@/lib/stream-finalize';

/** 过程时间线条目（流式期间的工具/操作运行态，完成后从消息 trace 重建） */
export interface TimelineToolEntry {
  id: string;
  name: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  elapsed_ms?: number;
  result_summary?: string;
  /** 规划级执行器标记（capability 注册表下发） */
  planning?: boolean;
  /** 工具输入参数预览（后端裁剪脱敏，详情卡展开区用） */
  args?: Record<string, unknown>;
  /** 运行态走秒计时起点（刷新/重连无起点时以恢复时刻为准） */
  started_at_ms?: number;
}

/** 排队中的引导消息（Agent 推理中用户继续发送，当前任务完成后自动发出） */
export interface QueuedMessage {
  id: string;
  /** 纯文本正文（实际发给后端） */
  text: string;
  /** 展示文本（含附件说明） */
  displayText: string;
  /** 富文本片段（重发时优先用） */
  parts: RichContentPart[];
}

/**
 * 聊天状态管理
 * 管理消息列表、流式输出、Agent 忙碌状态
 */
export interface ChatState {
  messages: ChatMessage[];
  /** 流式累积文本 */
  streamingText: string;
  /** 流式状态提示（如 “正在思考…”） */
  streamingStatus: string;
  isStreaming: boolean;
  inputText: string;
  /** 当前流式回复对应的模型名称 */
  streamingModel: string;
  /** 流式深度思考（reasoning）累积文本（仅 UI 展示，不进下次上下文） */
  streamingReasoning: string;
  /** 流式过程时间线条目（tool_started/tool_finished 实时追加） */
  streamingTools: TimelineToolEntry[];
  /** 深度思考开始时刻（首条 reasoning 增量到达时记录，用于完成后的耗时角标） */
  streamingReasoningStartMs: number;
  /** 深度思考结束时刻（末条 reasoning 增量）；耗时角标 = 末-首，不混入工具执行时间 */
  streamingReasoningEndMs: number;
  /** 排队中的引导消息（推理中发送 → 当前任务完成后自动发出） */
  queuedMessages: QueuedMessage[];
  /** 本轮流已渲染过文档卡片的名称（doc_written 即显与 done 全量清单去重用） */
  renderedDocCards: string[];
  /** 推理轮次进度（status 事件 {step,max} 结构化捕获；0 = 未收到） */
  roundStep: number;
  roundMax: number;
}

const defaultChatState: ChatState = {
  messages: [],
  streamingText: '',
  streamingStatus: '',
  isStreaming: false,
  inputText: '',
  streamingModel: '',
  streamingReasoning: '',
  streamingTools: [],
  streamingReasoningStartMs: 0,
  streamingReasoningEndMs: 0,
  queuedMessages: [],
  renderedDocCards: [],
  roundStep: 0,
  roundMax: 0,
};

const [chatState, setChatState] = createStore<ChatState>(defaultChatState);

// 流式收尾重置/继续建议派生/停止气泡构造抽至 lib/stream-finalize.ts，
// 供 done/错误/停止/重连四处收尾复用同一语义（控制本文件行数）

export const chatActions = {
  addMessage(msg: ChatMessage) {
    setChatState('messages', (prev) => [...prev, { ...msg, ts: msg.ts ?? Date.now() }]);
  },

  /** 截断重答本地同步（与后端 truncate_chat_tail 同语义）：丢弃最后一条
   * 非系统动作用户消息之后的全部消息；text 非空时替换该消息正文。
   * 仅在 /chat/truncate-resend 成功后调用（旧回复消失，新任务流式接续）。 */
  truncateTailForResend(newText?: string) {
    setChatState('messages', (prev) => {
      let idx = -1;
      for (let i = prev.length - 1; i >= 0; i -= 1) {
        const m = prev[i];
        if (m.sender === 'user' && m.kind !== 'system_action') { idx = i; break; }
      }
      if (idx < 0) return prev;
      const next = prev.slice(0, idx + 1);
      const body = (newText || '').trim();
      // 替换正文时同步清 parts（与后端替换语义对齐：旧图文排版随重写作废）；
      // 纯重答路径（无 newText）不动
      if (body) next[idx] = { ...next[idx], text: body, parts: undefined };
      return next;
    });
  },

  setInput(text: string) {
    setChatState('inputText', text);
  },

  /** 流式开始 */
  startStream(modelName?: string) {
    setChatState(produce((s) => {
      s.isStreaming = true;
      s.streamingText = '';
      s.streamingStatus = t('rp.streaming.connecting');
      s.streamingModel = modelName || '';
      s.streamingReasoning = '';
      s.streamingTools = [];
      s.streamingReasoningStartMs = 0;
      s.streamingReasoningEndMs = 0;
      s.renderedDocCards = [];
      s.roundStep = 0;
      s.roundMax = 0;
    }));
  },

  /** 推理轮次进度更新（status 事件结构化参数；阶段进度条唯一数据源） */
  setRoundProgress(step: number, max: number) {
    setChatState(produce((s) => {
      s.roundStep = step;
      s.roundMax = max;
    }));
  },

  /** 追加深度思考（reasoning）增量 */
  appendReasoning(text: string) {
    setChatState(produce((s) => {
      if (!s.streamingReasoningStartMs) s.streamingReasoningStartMs = Date.now();
      // 结束时刻随每条增量推进（思考与工具执行交错，角标只算思考区间）
      s.streamingReasoningEndMs = Date.now();
      s.streamingReasoning += text;
      s.streamingStatus = t('rp.streaming.reasoning');
    }));
  },

  /** 过程时间线：工具/操作开始（运行态条目；args 为后端裁剪脱敏后的输入预览） */
  toolStarted(id: string, name: string, summary: string, args?: Record<string, unknown>) {
    setChatState(produce((s) => {
      s.streamingTools.push({
        id, name, summary, status: 'running', started_at_ms: Date.now(), args,
      });
      // 状态文案走 i18n 键，不硬编码中文
      s.streamingStatus = t('rp.streaming.executing', {
        n: s.streamingTools.length,
        summary: summary || name,
      });
    }));
  },

  /** 过程时间线：工具/操作完成（对勾/失败态；planning=规划级执行器标记） */
  toolFinished(id: string, ok: boolean, elapsedMs: number, resultSummary?: string, planning?: boolean) {
    setChatState(produce((s) => {
      // 参数名避开 i18n 惯用名 t，防止遮蔽外层 t 函数
      const entry = s.streamingTools.find((item) => item.id === id);
      if (entry) {
        entry.status = ok ? 'done' : 'failed';
        entry.elapsed_ms = elapsedMs;
        if (planning) entry.planning = true;
        entry.result_summary = resultSummary;
      }
    }));
  },

  /** 追加流式文本片段 */
  appendDelta(text: string) {
    setChatState('streamingText', (prev) => prev + text);
    setChatState('streamingStatus', t('rp.streaming.replying'));
  },

  /** 设置状态提示 */
  setStatus(text: string) {
    setChatState('streamingStatus', text);
  },

  /** 流式完成：将结果写入消息列表 */
  finishStream(payload: SseDonePayload) {
    const elapsed = ((payload.elapsed_ms || 0) / 1000).toFixed(1);
    // meta 文案全部走 locale 字典，不硬编码中文
    const metaParts = [t('rp.msg.metaTime', { s: elapsed })];
    // 轮次 token 账单（后端 usage 有值才展示；缺失保 0 不显示）
    const totalTokens = (payload.trace?.steps || [])
      .reduce((sum, st) => sum + (st.token_usage || 0), 0);
    if (totalTokens > 0) metaParts.push(t('rp.msg.metaTokens', { n: totalTokens }));
    if (payload.steps > 1) metaParts.push(t('rp.msg.metaRounds', { n: payload.steps }));
    if (payload.applied_actions > 0) metaParts.push(t('rp.msg.metaUpdated', { n: payload.applied_actions }));

    // 深度思考耗时角标（末条 reasoning - 首条 reasoning；无思考时 0）
    const startMs = chatState.streamingReasoningStartMs;
    const endMs = chatState.streamingReasoningEndMs;
    const thinkingMs = startMs && endMs && endMs >= startMs ? endMs - startMs : 0;

    setChatState(produce((s) => {
      // 同轮消息共用 turnId（渲染层聚合为轮次容器，消除碎片化）
      const turnId = payload.turn_id || undefined;
      s.messages.push({
        sender: 'agent',
        ts: Date.now(),
        text: (payload.text || '').trim() || t('rp.msg.emptyReply'),
        meta: metaParts.join(' · '),
        // 类型收窄：confirm 唯一形态 = 问句文本（无暂停 = undefined）
        confirm: payload.confirmation || undefined,
        appliedActions: payload.applied_actions || 0,
        actionLog: (payload.action_log || []).length ? payload.action_log : undefined,
        // 确认卡片的候选选项（单选卡片，点击即把 label 作为回复发送）
        confirmOptions: (payload.confirmation_options || []).length ? payload.confirmation_options : undefined,
        // 主模型故障 fallback 时标注实际生效的模型
        modelName: payload.fallback_model || s.streamingModel || undefined,
        trace: payload.trace && (payload.trace.steps || []).length ? payload.trace : undefined,
        // 闸机拦截/降级等警告：随消息常驻展示，拦截类附「本次放行」按钮
        warnings: (payload.warnings || []).length ? payload.warnings : undefined,
        thinkingMs: thinkingMs || undefined,
        turnId,
        // 暂停卡语义种类：前端卡标题按 kind 渲染（remind=待补原料 /
        // collect=规格交互 / 其余=阶段完成）；
        // 白名单收窄，未知值不入库（防类型退化）
        kind: (['remind', 'collect', 'stage_done', 'confirm'].includes(payload.pause_kind || '')
          ? (payload.pause_kind as ChatMessage['kind'])
          : undefined),
        // 暂停卡结构化标识（用户点选回应时经 pause_response 结构化回携，对勾不再靠文本反推）
        pauseId: payload.pause_id || undefined,
        // 任务 #3：结构化决策表单（workflow 投影 pending_decision_payload，
        // schema→表单数据驱动；与确认卡同源同消息，不另起卡片）
        decisionForm: payload.workflow?.pending_decision_payload || undefined,
        // 建议动作按钮（重试/继续，确定性交互；仅最后一条消息渲染）
        suggestedActions: (payload.suggested_actions || []).length
          ? payload.suggested_actions : undefined,
      });
      // 文档卡片（doc_written 事件已即显过的按名称去重，不重复渲染；
      // 服务端持久化仍按 documents_written 全量落盘，刷新后由快照重建）
      (payload.documents_written || []).forEach((name) => {
        if (s.renderedDocCards.includes(name)) return;
        s.renderedDocCards.push(name);
        s.messages.push({ sender: 'agent', docCard: name, text: '', turnId, ts: Date.now() });
      });
      // 生图结果图片卡片
      if (payload.image_urls && payload.image_urls.length > 0) {
        s.messages.push({
          sender: 'agent',
          text: '',
          ts: Date.now(),
          imageCard: { image_urls: payload.image_urls },
          turnId,
        });
      }
      // 视频结果内联预览卡：数据源 = done payload 的 chat_inserts 中 kind=video 项
      //（storyboard_media_to_chat 产出，带首帧 thumb）；输入框插入通道不变（use-sse 侧）
      const videoInserts = (payload.chat_inserts || [])
        .filter((it) => it.kind === 'video' && !!it.url);
      if (videoInserts.length > 0) {
        s.messages.push({
          sender: 'agent',
          text: '',
          ts: Date.now(),
          videoCard: {
            items: videoInserts.map((it) => ({
              url: it.url,
              name: it.name || undefined,
              thumb: it.thumb || undefined,
            })),
          },
          turnId,
        });
      }
      resetStreamFields(s);
    }));
  },

  /** 流式错误：输入为结构化 ErrorPayload，affordance 查 ERROR_ACTION_MAP
   * 单一映射表（不做正则猜文案）；会话中已有用户消息时派生「继续刚才的任务」 */
  streamError(payload: ErrorPayload) {
    const action = actionForKind(payload.kind);
    setChatState(produce((s) => {
      // auth →「检查 API 配置」跳转；quota/network 等 affordance 由映射表集中决定；
      // 上游原始报文折叠展示（人话在气泡，raw 在折叠）
      s.messages.push({
        sender: 'agent', text: `⚠️ ${payload.message}`, modelName: s.streamingModel || undefined,
        ts: Date.now(),
        settingsHint: !!action.settingsHint,
        errorKind: payload.kind,
        errorDetail: payload.raw || undefined,
        suggestedActions: s.messages.some((m) => m.sender === 'user') ? continueLastTaskSuggestion() : undefined,
      });
      resetStreamFields(s);
    }));
  },

  /** 清空流式状态（用户手动停止）。停止后不纯丢弃——
   * 停止气泡本地派生「继续刚才的任务」建议（走既有 suggested_actions 展示通道，
   * 不改 SSE 协议）；kind=retry 即点击走已验收的机械重发（重发最近一条用户消息）。
   * 中断不变式：任何中断都有痕迹、都有出口——
   * 无文本停止同样落轻量系统气泡 + 继续建议；阶段标记影响措辞；
   * 在途外部生成任务登记（inflight）附文案提醒（第一版不撤销）。 */
  cancelStream(opts?: {
    /** 停止阶段（stopped 事件/停止响应下发；缺省按本地流状态推导） */
    phase?: StopPhase;
    /** 在途外部生成任务登记（后端 /stop 响应或 stopped 事件携带） */
    inflight?: StopInflightItem[];
  }) {
    setChatState(produce((s) => {
      // 停止气泡构造归 lib/stream-finalize.buildStopMessages
      // （不变式：无文本停止也落轻量气泡 + 继续建议）
      s.messages.push(...buildStopMessages({
        phase: opts?.phase, inflight: opts?.inflight,
        text: s.streamingText, model: s.streamingModel,
        hasRunningTool: s.streamingTools.some((item) => item.status === 'running'),
      }));
      resetStreamFields(s);
    }));
  },

  /** 恢复流式状态（任务式传输重连：先回放服务端累计状态，再收实时增量） */
  restoreStreamingState(p: {
    reasoning?: string; text?: string; statusText?: string;
    tools?: TimelineToolEntry[]; model?: string;
  }) {
    setChatState(produce((s) => {
      s.isStreaming = true;
      s.streamingReasoning = p.reasoning || '';
      s.streamingText = p.text || '';
      s.streamingStatus = p.statusText || '';
      s.streamingTools = p.tools || [];
      s.streamingModel = p.model || '';
      // 重连无原始思考起点：已有 reasoning 时以恢复时刻
      // 为起点继续计时（角标不再恒 0），同步重置终点防旧值残留
      s.streamingReasoningStartMs = p.reasoning ? Date.now() : 0;
      s.streamingReasoningEndMs = p.reasoning ? Date.now() : 0;
    }));
  },

  /** 清空流式状态（重连后发现任务已完成，直接收尾，不追加「已停止」消息） */
  clearStreaming() {
    setChatState(produce((s) => resetStreamFields(s)));
  },

  /** 任务 #3：结构化决策表单投影（replay 重建通道）。把 pending_decision_payload
   * 挂到最近一条待回应 agent 暂停消息；无载体时派生轻量卡消息。
   * token 幂等守卫：重连/重放 replay 不重复挂卡；不跨用户消息向前附挂
   * （用户已回应后旧决策不再复活）。 */
  applyDecisionForm(payload: PendingDecisionPayload) {
    const hasBody = Boolean(payload.token) || (payload.schema?.fields || []).length > 0;
    if (!hasBody) return;
    setChatState(produce((s) => {
      // 幂等：同 token 已在列表中（重连 replay 同源重建不双挂）
      if (payload.token
        && s.messages.some((m) => m.decisionForm?.token === payload.token)) return;
      for (let i = s.messages.length - 1; i >= 0; i -= 1) {
        const m = s.messages[i];
        if (m.sender === 'user') break;
        if (m.sender === 'agent' && (m.confirm || m.kind) && !m.decisionForm) {
          m.decisionForm = payload;
          return;
        }
      }
      // 无载体：派生独立卡消息（confirm 取决策问句供阶段卡展示；
      // 交互面由 DecisionFormCard 接管，ConfirmActions 遇 decisionForm 让位）
      s.messages.push({
        sender: 'agent', text: '', ts: Date.now(),
        decisionForm: payload,
        confirm: payload.message || t('rp.decision.defaultTitle'),
      });
    }));
  },

  /** 文档写入即显（doc_written 事件）：独立文档卡片立即渲染，
   * 不等整轮 done；同轮重复名称去重（done 全量清单与事件双通道防双显）。
   * 携带后端透传层打戳的 turn_id，即显卡严格归入轮次容器 */
  docWritten(name: string, turnId?: string) {
    if (!name) return;
    setChatState(produce((s) => {
      if (s.renderedDocCards.includes(name)) return;
      s.renderedDocCards.push(name);
      s.messages.push({ sender: 'agent', text: '', docCard: name, turnId, ts: Date.now() });
    }));
  },

  /** 非流式响应 documents_written 即显（与流式通道对齐，不留半截通道）：
   * 后端非流式载荷携带文档清单时前端同样渲染卡片；非流式无流式轮边界，
   * 先重置「本轮已显」去重表（与 startStream 每轮清零同语义）再按清单渲染 */
  applyNonStreamDocs(names: string[]) {
    if (!names || !names.length) return;
    setChatState(produce((s) => {
      s.renderedDocCards = [];
      names.forEach((name) => {
        if (!name || s.renderedDocCards.includes(name)) return;
        s.renderedDocCards.push(name);
        s.messages.push({ sender: 'agent', text: '', docCard: name, ts: Date.now() });
      });
    }));
  },

  /** 从后端加载历史消息 */
  loadMessages(msgs: ChatMessage[]) {
    setChatState('messages', msgs);
    // 历史重建视同新轮次展示，去重表同步清零（防切项目/刷新后残留误去重）
    setChatState('renderedDocCards', []);
    // 按当前项目+对话键恢复排队消息（刷新存活）
    setChatState('queuedMessages', loadQueue());
  },

  // ====== 排队引导消息（推理中继续发送，任务完成后自动发出） ======

  enqueueMessage(msg: QueuedMessage) {
    setChatState('queuedMessages', (prev) => [...prev, msg]);
    saveQueue(chatState.queuedMessages);
  },

  removeQueuedMessage(id: string) {
    setChatState('queuedMessages', (prev) => prev.filter((m) => m.id !== id));
    saveQueue(chatState.queuedMessages);
  },

  /** 移到队首（「引导」：当前任务一结束就优先发送这条） */
  moveQueuedToFront(id: string) {
    setChatState('queuedMessages', (prev) => {
      const target = prev.find((m) => m.id === id);
      if (!target) return prev;
      return [target, ...prev.filter((m) => m.id !== id)];
    });
    saveQueue(chatState.queuedMessages);
  },

  clearQueuedMessages() {
    setChatState('queuedMessages', []);
    saveQueue([]);
  },
};

export { chatState, setChatState };
