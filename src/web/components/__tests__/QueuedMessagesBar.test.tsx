/**
 * QueuedMessagesBar 交互测试：
 * ① 「在侧边聊天中打开」对旧格式排队条目（localStorage 旧数据无 parts 键）
 *    不抛 TypeError，回落纯文本发送；
 * ② 引导/删除/编辑/关闭排队四类操作与 ⋯ 菜单开合（F0 安全绳扩围）；
 * ③ Agent 忙碌拦截新建对话、新建失败放回队列（消息不丢）；
 * ④ 引导 spinner 在条目出队后终止（防转圈悬挂）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueuedMessagesBar } from '../right-panel/QueuedMessagesBar';
import { chatActions } from '@/stores/chat';
import type { QueuedMessage } from '@/stores/chat';
import { agentActions } from '@/stores/agent-state';

vi.mock('@/lib/submit-message', () => ({
  submitMessage: vi.fn(() => Promise.resolve(true)),
}));
vi.mock('@/stores/conversations', () => ({
  convActions: { create: vi.fn(() => Promise.resolve(true)) },
}));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { submitMessage } from '@/lib/submit-message';
import { convActions } from '@/stores/conversations';
import { showToast } from '@/stores/toast';

function queued(id: string, text: string, parts: QueuedMessage['parts'] = []): QueuedMessage {
  return { id, text, displayText: text, parts };
}

describe('QueuedMessagesBar 在侧边聊天中打开', () => {
  beforeEach(() => {
    chatActions.clearQueuedMessages();
    agentActions.setAgentBusy(false);
    vi.mocked(submitMessage).mockClear();
    vi.mocked(showToast).mockClear();
    vi.mocked(convActions.create).mockClear();
    vi.mocked(convActions.create).mockResolvedValue(true);
  });

  it('旧格式条目（无 parts 键）打开侧边聊天不抛错并回落纯文本', async () => {
    const legacy = { id: 'q-old', text: '旧格式排队', displayText: '旧格式排队' } as unknown as QueuedMessage;
    chatActions.enqueueMessage(legacy);
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    // 打开 ⋯ 菜单后点「在侧边聊天中打开」
    await fireEvent.click(container.querySelector('.queued-more-btn') as HTMLElement);
    const openBtn = Array.from(container.querySelectorAll('.queued-more-menu button'))
      .find((b) => b.textContent?.includes('在侧边聊天中打开'));
    expect(openBtn).toBeTruthy();
    await fireEvent.click(openBtn as HTMLElement);
    // 等 create() promise 链落定
    await new Promise((r) => setTimeout(r, 0));
    expect(submitMessage).toHaveBeenCalledWith('queued', expect.objectContaining({
      input: '旧格式排队',
      queuedEntry: expect.objectContaining({ id: 'q-old' }),
    }));
  });

  it('带 parts 的新格式条目优先用富文本片段发送', async () => {
    const parts: QueuedMessage['parts'] = [{ type: 'text', text: '富文本正文' }];
    chatActions.enqueueMessage(queued('q-rich', '纯文本回退', parts));
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    await fireEvent.click(container.querySelector('.queued-more-btn') as HTMLElement);
    const openBtn = Array.from(container.querySelectorAll('.queued-more-menu button'))
      .find((b) => b.textContent?.includes('在侧边聊天中打开'));
    await fireEvent.click(openBtn as HTMLElement);
    await new Promise((r) => setTimeout(r, 0));
    expect(submitMessage).toHaveBeenCalledWith('queued', expect.objectContaining({ input: parts }));
  });

  it('Agent 忙碌时新建对话已解锁（批 6-2 多会话并行）：照常新建并发出，不拦截', async () => {
    agentActions.setAgentBusy(true);
    chatActions.enqueueMessage(queued('q-busy', '忙碌中排队'));
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    await fireEvent.click(container.querySelector('.queued-more-btn') as HTMLElement);
    const openBtn = Array.from(container.querySelectorAll('.queued-more-menu button'))
      .find((b) => b.textContent?.includes('在侧边聊天中打开'));
    await fireEvent.click(openBtn as HTMLElement);
    await new Promise((r) => setTimeout(r, 0));
    expect(showToast).not.toHaveBeenCalledWith(expect.any(String), 'warning');
    expect(convActions.create).toHaveBeenCalled();
    expect(submitMessage).toHaveBeenCalledWith('queued', expect.objectContaining({ input: '忙碌中排队' }));
  });

  it('新建对话失败时放回队列（消息不丢）', async () => {
    vi.mocked(convActions.create).mockResolvedValueOnce(false);
    chatActions.enqueueMessage(queued('q-fail', '新建失败条目'));
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    await fireEvent.click(container.querySelector('.queued-more-btn') as HTMLElement);
    const openBtn = Array.from(container.querySelectorAll('.queued-more-menu button'))
      .find((b) => b.textContent?.includes('在侧边聊天中打开'));
    await fireEvent.click(openBtn as HTMLElement);
    await new Promise((r) => setTimeout(r, 0));
    expect(submitMessage).not.toHaveBeenCalled();
    // 放回队列：chip 重新渲染
    expect(container.querySelector('.queued-chip-text')?.textContent).toBe('新建失败条目');
  });
});

describe('QueuedMessagesBar 队列操作（引导/删除/编辑/关闭排队）', () => {
  beforeEach(() => {
    chatActions.clearQueuedMessages();
    agentActions.setAgentBusy(false);
    vi.mocked(submitMessage).mockClear();
    vi.mocked(showToast).mockClear();
  });

  it('引导：走 guidance 通道登记轮间注入，条目原位转 spinner；出队后 spinner 终止', async () => {
    chatActions.enqueueMessage(queued('q-guide', '先走写实风'));
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    await fireEvent.click(container.querySelector('.queued-action-guide') as HTMLElement);
    expect(submitMessage).toHaveBeenCalledWith('guidance', expect.objectContaining({
      input: '先走写实风',
      queuedEntry: expect.objectContaining({ id: 'q-guide' }),
    }));
    expect(container.querySelector('.queued-spin')).toBeTruthy();
    // 出队 → spinner 终止（同 id 重新入队不再转圈，防悬挂）
    chatActions.removeQueuedMessage('q-guide');
    chatActions.enqueueMessage(queued('q-guide', '先走写实风'));
    expect(container.querySelector('.queued-spin')).toBeNull();
  });

  it('删除：单条移出队列', async () => {
    chatActions.enqueueMessage(queued('q-del', '待删除'));
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    const delBtn = Array.from(container.querySelectorAll('.queued-chip-actions .queued-action'))
      .find((b) => !b.classList.contains('queued-action-guide') && !b.classList.contains('queued-more-btn'));
    await fireEvent.click(delBtn as HTMLElement);
    expect(container.querySelector('.queued-bar')).toBeNull();
  });

  it('编辑消息：移出队列并回填输入框（onEdit 携带原文本）', async () => {
    const onEdit = vi.fn();
    chatActions.enqueueMessage(queued('q-edit', '要编辑的排队'));
    const { container } = render(() => <QueuedMessagesBar onEdit={onEdit} />);
    await fireEvent.click(container.querySelector('.queued-more-btn') as HTMLElement);
    const editBtn = Array.from(container.querySelectorAll('.queued-more-menu button'))
      .find((b) => b.textContent?.includes('编辑消息'));
    await fireEvent.click(editBtn as HTMLElement);
    expect(onEdit).toHaveBeenCalledWith('要编辑的排队');
    expect(container.querySelector('.queued-bar')).toBeNull();
  });

  it('⋯ 菜单再点即收起（开合互逆）', async () => {
    chatActions.enqueueMessage(queued('q-menu', '菜单开合'));
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    const more = container.querySelector('.queued-more-btn') as HTMLElement;
    await fireEvent.click(more);
    expect(container.querySelector('.queued-more-menu')).toBeTruthy();
    await fireEvent.click(more);
    expect(container.querySelector('.queued-more-menu')).toBeNull();
  });

  it('关闭排队：清空全部条目并 toast（头部按钮与菜单入口同语义）', async () => {
    chatActions.enqueueMessage(queued('q-a', '条目一'));
    chatActions.enqueueMessage(queued('q-b', '条目二'));
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    await fireEvent.click(container.querySelector('.queued-bar-clear') as HTMLElement);
    expect(showToast).toHaveBeenCalledWith(expect.any(String), 'info');
    expect(container.querySelector('.queued-bar')).toBeNull();
  });

  it('队列为空时整体不渲染', () => {
    const { container } = render(() => <QueuedMessagesBar onEdit={vi.fn()} />);
    expect(container.querySelector('.queued-bar')).toBeNull();
  });
});
