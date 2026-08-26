import { describe, it, expect, beforeEach } from 'vitest';

/**
 * chat store 排队消息持久化测试（自 chat.test.ts 拆出：行数门禁清偿，
 * 任务 #21；拆分模式与 chat-continue-suggestion.test.ts 同先例）
 */
import { chatState, chatActions, setChatState } from '../chat';
import { registerQueueStorageKey } from '@/lib/chat/queue-storage';

describe('排队消息持久化', () => {
  const KEY_A = 'ftdyb.queued.p1.conv-a';
  const KEY_B = 'ftdyb.queued.p1.conv-b';
  const q = (id: string, text: string) => ({ id, text, displayText: text, parts: [] });

  beforeEach(() => {
    localStorage.clear();
    registerQueueStorageKey(() => KEY_A);
    chatActions.clearQueuedMessages();
  });

  it('入队即落盘；模拟刷新后 loadMessages 按键恢复', () => {
    chatActions.enqueueMessage(q('q1', '先做关键元素'));
    chatActions.enqueueMessage(q('q2', '再生图'));
    expect(JSON.parse(localStorage.getItem(KEY_A) || '[]').length).toBe(2);
    // 模拟刷新：内存态丢失，存储仍在
    setChatState('queuedMessages', []);
    chatActions.loadMessages([]);
    expect(chatState.queuedMessages.map((m) => m.id)).toEqual(['q1', 'q2']);
  });

  it('删除/清空同步落盘（清空移除键）', () => {
    chatActions.enqueueMessage(q('q1', 'a'));
    chatActions.enqueueMessage(q('q2', 'b'));
    chatActions.removeQueuedMessage('q1');
    expect(JSON.parse(localStorage.getItem(KEY_A) || '[]').map((m: { id: string }) => m.id)).toEqual(['q2']);
    chatActions.clearQueuedMessages();
    expect(localStorage.getItem(KEY_A)).toBeNull();
  });

  it('切换对话键后互不串流（按项目+对话隔离）', () => {
    chatActions.enqueueMessage(q('q1', 'conv-a 的排队'));
    registerQueueStorageKey(() => KEY_B);
    chatActions.loadMessages([]);
    expect(chatState.queuedMessages.length).toBe(0);
    chatActions.enqueueMessage(q('q9', 'conv-b 的排队'));
    registerQueueStorageKey(() => KEY_A);
    chatActions.loadMessages([]);
    expect(chatState.queuedMessages.map((m) => m.id)).toEqual(['q1']);
  });

  it('存储内容损坏时回落空队列不抛异常', () => {
    localStorage.setItem(KEY_A, '{不是合法 JSON');
    expect(() => chatActions.loadMessages([])).not.toThrow();
    expect(chatState.queuedMessages.length).toBe(0);
  });

  it('未注册键时保持纯内存态（旧行为兜底）', () => {
    registerQueueStorageKey(() => '');
    chatActions.enqueueMessage(q('q1', '内存态'));
    expect(chatState.queuedMessages.length).toBe(1);
    expect(localStorage.length).toBe(0);
  });
});
