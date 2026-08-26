/** Chat store · 排队域（任务 #11 三分拆）：排队引导消息（推理中继续发送，
 * 任务完成后自动发出）；存储键与持久化归 lib/chat/queue-storage。
 */
import type { RichContentPart } from '@/types';
import { saveQueue, loadQueue } from '@/lib/chat/queue-storage';
import { chatState, setChatState } from '../chat-core';

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

export const queueActions = {
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

  /** 按当前项目+对话键恢复排队消息（loadMessages/刷新存活路径调用） */
  restoreQueue() {
    setChatState('queuedMessages', loadQueue());
  },
};
