import { createStore, produce } from 'solid-js/store';
import type { ChatMessage, SseDonePayload } from '@/types';

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
}

const defaultChatState: ChatState = {
  messages: [],
  streamingText: '',
  streamingStatus: '',
  isStreaming: false,
  inputText: '',
  streamingModel: '',
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

    setChatState(produce((s) => {
      s.messages.push({
        sender: 'agent',
        text: (payload.text || '').trim() || '（空回复）',
        meta: metaParts.join(' · '),
        confirm: payload.confirmation || '',
        appliedActions: payload.applied_actions || 0,
        actionLog: (payload.action_log || []).length ? payload.action_log : undefined,
        // 主模型故障 fallback 时标注实际生效的模型
        modelName: payload.fallback_model || s.streamingModel || undefined,
        trace: payload.trace && (payload.trace.steps || []).length ? payload.trace : undefined,
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
    }));
  },

  /** 从后端加载历史消息 */
  loadMessages(msgs: ChatMessage[]) {
    setChatState('messages', msgs);
  },
};

export { chatState, setChatState };
