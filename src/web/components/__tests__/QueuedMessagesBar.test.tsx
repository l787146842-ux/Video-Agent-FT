/**
 * QueuedMessagesBar 交互测试：「在侧边聊天中打开」对旧格式排队条目
 * （localStorage 旧数据无 parts 键）不抛 TypeError，回落纯文本发送。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueuedMessagesBar } from '../right-panel/QueuedMessagesBar';
import { chatActions } from '@/stores/chat';
import type { QueuedMessage } from '@/stores/chat';
import { studioActions } from '@/stores/studio';

vi.mock('@/lib/submit-message', () => ({
  submitMessage: vi.fn(() => Promise.resolve(true)),
}));
vi.mock('@/stores/conversations', () => ({
  convActions: { create: vi.fn(() => Promise.resolve(true)) },
}));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { submitMessage } from '@/lib/submit-message';

describe('QueuedMessagesBar 在侧边聊天中打开', () => {
  beforeEach(() => {
    chatActions.clearQueuedMessages();
    studioActions.setAgentBusy(false);
    vi.mocked(submitMessage).mockClear();
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
});
