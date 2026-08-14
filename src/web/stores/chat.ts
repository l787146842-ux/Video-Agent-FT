import { createStore, produce } from 'solid-js/store';
import type { ChatMessage, SseDonePayload, RichContentPart } from '@/types';

/** 过程时间线条目（流式期间的工具/操作运行态，完成后从消息 trace 重建） */
export interface TimelineToolEntry {
  id: string;
  name: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  elapsed_ms?: number;
  result_summary?: string;
  /** 814G2：运行态走秒计时起点（刷新/重连无起点时以恢复时刻为准） */
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
  /** 排队中的引导消息（推理中发送 → 当前任务完成后自动发出） */
  queuedMessages: QueuedMessage[];
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
  queuedMessages: [],
};

const [chatState, setChatState] = createStore<ChatState>(defaultChatState);

export const chatActions = {
  addMessage(msg: ChatMessage) {
    setChatState('messages', (prev) => [...prev, msg]);
  },

  setInput(text: string) {
    setChatState('inputText', text);
  },

  /** 流式开始 */
  startStream(modelName?: string) {
    setChatState(produce((s) => {
      s.isStreaming = true;
      s.streamingText = '';
      s.streamingStatus = '正在连接…';
      s.streamingModel = modelName || '';
      s.streamingReasoning = '';
      s.streamingTools = [];
      s.streamingReasoningStartMs = 0;
    }));
  },

  /** 追加深度思考（reasoning）增量 */
  appendReasoning(text: string) {
    setChatState(produce((s) => {
      if (!s.streamingReasoningStartMs) s.streamingReasoningStartMs = Date.now();
      s.streamingReasoning += text;
      s.streamingStatus = '深度思考中…';
    }));
  },

  /** 过程时间线：工具/操作开始（运行态条目） */
  toolStarted(id: string, name: string, summary: string) {
    setChatState(produce((s) => {
      s.streamingTools.push({ id, name, summary, status: 'running', started_at_ms: Date.now() });
      s.streamingStatus = `正在执行第 ${s.streamingTools.length} 项操作：${summary || name}`;
    }));
  },

  /** 过程时间线：工具/操作完成（对勾/失败态） */
  toolFinished(id: string, ok: boolean, elapsedMs: number, resultSummary?: string) {
    setChatState(produce((s) => {
      const entry = s.streamingTools.find((t) => t.id === id);
      if (entry) {
        entry.status = ok ? 'done' : 'failed';
        entry.elapsed_ms = elapsedMs;
        entry.result_summary = resultSummary;
      }
    }));
  },

  /** 追加流式文本片段 */
  appendDelta(text: string) {
    setChatState('streamingText', (prev) => prev + text);
    setChatState('streamingStatus', '正在回复…');
  },

  /** 设置状态提示 */
  setStatus(text: string) {
    setChatState('streamingStatus', text);
  },

  /** 流式完成：将结果写入消息列表 */
  finishStream(payload: SseDonePayload) {
    const elapsed = ((payload.elapsed_ms || 0) / 1000).toFixed(1);
    const metaParts = [`耗时 ${elapsed}s`];
    if (payload.steps > 1) metaParts.push(`${payload.steps} 轮`);
    if (payload.applied_actions > 0) metaParts.push(`更新 ${payload.applied_actions} 项`);

    // 深度思考耗时角标：首条 reasoning 增量 → 完成时刻（无思考时 0）
    const startMs = chatState.streamingReasoningStartMs;
    const thinkingMs = startMs ? Date.now() - startMs : 0;

    setChatState(produce((s) => {
      s.messages.push({
        sender: 'agent',
        text: (payload.text || '').trim() || '（空回复）',
        meta: metaParts.join(' · '),
        confirm: payload.confirmation || '',
        appliedActions: payload.applied_actions || 0,
        actionLog: (payload.action_log || []).length ? payload.action_log : undefined,
        // 确认卡片的候选选项（单选卡片，点击即把 label 作为回复发送）
        confirmOptions: (payload.confirmation_options || []).length ? payload.confirmation_options : undefined,
        // 主模型故障 fallback 时标注实际生效的模型
        modelName: payload.fallback_model || s.streamingModel || undefined,
        trace: payload.trace && (payload.trace.steps || []).length ? payload.trace : undefined,
        // 闸机拦截/降级等警告（814F7）：随消息常驻展示，拦截类附「本次放行」按钮
        warnings: (payload.warnings || []).length ? payload.warnings : undefined,
        // 记忆命中可视化（4.7）：随 done payload 下发
        memoryHits: (payload.memory_hits || []).length ? payload.memory_hits : undefined,
        thinkingMs: thinkingMs || undefined,
      });
      // 文档卡片
      (payload.documents_written || []).forEach((name) => {
        s.messages.push({ sender: 'agent', docCard: name, text: '' });
      });
      // 生图结果图片卡片
      if (payload.image_urls && payload.image_urls.length > 0) {
        s.messages.push({
          sender: 'agent',
          text: '',
          imageCard: { image_urls: payload.image_urls },
        });
      }
      s.isStreaming = false;
      s.streamingText = '';
      s.streamingStatus = '';
      s.streamingModel = '';
      s.streamingReasoning = '';
      s.streamingTools = [];
      s.streamingReasoningStartMs = 0;
    }));
  },

  /** 流式错误 */
  streamError(message: string) {
    setChatState(produce((s) => {
      s.messages.push({ sender: 'agent', text: `⚠️ ${message}`, modelName: s.streamingModel || undefined });
      s.isStreaming = false;
      s.streamingText = '';
      s.streamingStatus = '';
      s.streamingModel = '';
      s.streamingReasoning = '';
      s.streamingTools = [];
      s.streamingReasoningStartMs = 0;
    }));
  },

  /** 清空流式状态（用户手动停止） */
  cancelStream() {
    setChatState(produce((s) => {
      if (s.streamingText) {
        s.messages.push({ sender: 'agent', text: s.streamingText, meta: '已停止', modelName: s.streamingModel || undefined });
      }
      s.isStreaming = false;
      s.streamingText = '';
      s.streamingStatus = '';
      s.streamingModel = '';
      s.streamingReasoning = '';
      s.streamingTools = [];
      s.streamingReasoningStartMs = 0;
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
      s.streamingReasoningStartMs = 0;
    }));
  },

  /** 清空流式状态（重连后发现任务已完成，直接收尾，不追加「已停止」消息） */
  clearStreaming() {
    setChatState(produce((s) => {
      s.isStreaming = false;
      s.streamingText = '';
      s.streamingStatus = '';
      s.streamingModel = '';
      s.streamingReasoning = '';
      s.streamingTools = [];
      s.streamingReasoningStartMs = 0;
    }));
  },

  /** 文档写入即显（doc_written 事件）：独立文档卡片立即渲染，不等整轮 done */
  docWritten(name: string) {
    if (!name) return;
    setChatState(produce((s) => {
      s.messages.push({ sender: 'agent', text: '', docCard: name });
    }));
  },

  /** 从后端加载历史消息 */
  loadMessages(msgs: ChatMessage[]) {
    setChatState('messages', msgs);
  },

  // ====== 排队引导消息（推理中继续发送，任务完成后自动发出） ======

  enqueueMessage(msg: QueuedMessage) {
    setChatState('queuedMessages', (prev) => [...prev, msg]);
  },

  removeQueuedMessage(id: string) {
    setChatState('queuedMessages', (prev) => prev.filter((m) => m.id !== id));
  },

  /** 移到队首（「引导」：当前任务一结束就优先发送这条） */
  moveQueuedToFront(id: string) {
    setChatState('queuedMessages', (prev) => {
      const target = prev.find((m) => m.id === id);
      if (!target) return prev;
      return [target, ...prev.filter((m) => m.id !== id)];
    });
  },

  clearQueuedMessages() {
    setChatState('queuedMessages', []);
  },
};

export { chatState, setChatState };
