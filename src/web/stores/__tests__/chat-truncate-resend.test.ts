/**
 * chat store 本地截断重答测试（任务 #17）。
 *
 * truncateTailForResend 与后端 truncate_chat_tail 同语义：
 * 截断最后一条（非 system_action）用户消息之后的全部消息；
 * newText 非空时替换该用户消息正文（旧回复消失，新任务流式接续）。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { chatState, chatActions } from '../chat';
import type { ChatMessage } from '@/types';

const seed: ChatMessage[] = [
  { sender: 'user', text: '第一问' },
  { sender: 'agent', text: '旧回复1' },
  { sender: 'user', text: '第二问' },
  { sender: 'agent', text: '旧回复2' },
];

describe('chatActions.truncateTailForResend', () => {
  beforeEach(() => chatActions.loadMessages(seed.map((m) => ({ ...m }))));

  it('无 text（重新生成）：截到最后一条用户消息（含），其后回复消失', () => {
    chatActions.truncateTailForResend();
    expect(chatState.messages.length).toBe(3);
    expect(chatState.messages[2].text).toBe('第二问');
  });

  it('带 text（编辑）：截断并替换末条用户消息正文', () => {
    chatActions.truncateTailForResend('改写后的第二问');
    expect(chatState.messages.length).toBe(3);
    expect(chatState.messages[2].text).toBe('改写后的第二问');
  });

  it('空白 text 视为无替换（trim 后不落回空正文）', () => {
    chatActions.truncateTailForResend('   ');
    expect(chatState.messages[2].text).toBe('第二问');
  });

  it('替换正文时同步清 parts（与后端替换语义对齐）；纯重答路径不动', () => {
    chatActions.loadMessages([
      { sender: 'user', text: '看图说话', parts: [{ type: 'text', text: '看图说话' }, { type: 'image', url: '/a.png', name: '图' }] },
      { sender: 'agent', text: '旧回复' },
    ]);
    chatActions.truncateTailForResend('纯文字改写');
    expect(chatState.messages[0].text).toBe('纯文字改写');
    expect(chatState.messages[0].parts).toBeUndefined();
    // 纯重答（无 text）：原消息含 parts 也不动
    chatActions.loadMessages([
      { sender: 'user', text: '看图说话', parts: [{ type: 'text', text: '看图说话' }, { type: 'image', url: '/a.png', name: '图' }] },
      { sender: 'agent', text: '旧回复' },
    ]);
    chatActions.truncateTailForResend();
    expect(chatState.messages[0].parts?.length).toBe(2);
  });

  it('末条是 system_action 时越过它找真实用户消息', () => {
    chatActions.loadMessages([
      { sender: 'user', text: '真问题' },
      { sender: 'agent', text: '回复' },
      { sender: 'user', text: '本次放行', kind: 'system_action' },
    ]);
    chatActions.truncateTailForResend();
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toBe('真问题');
  });

  it('无用户消息时保持原样（后端 400 NO_USER_MESSAGE 的前端兜底）', () => {
    chatActions.loadMessages([{ sender: 'agent', text: '只有回复' }]);
    chatActions.truncateTailForResend();
    expect(chatState.messages.length).toBe(1);
  });
});
