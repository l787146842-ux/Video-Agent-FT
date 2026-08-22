/**
 * 空状态引导卡测试：
 * ① 能力提示 + 标题 + 4 个示例指令 chips 全量渲染（文案均走 locale 词条）；
 * ② 点击示例 chip 以词条文案为输入走统一发送入口 submitMessage('new')。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { EmptyStateCard } from '../right-panel/EmptyStateCard';
import { t } from '@/lib/locale';

const submitMock = vi.fn(async (_intent: string, _opts?: { input?: string }) => true);
vi.mock('@/lib/submit-message', () => ({
  submitMessage: (intent: string, opts?: { input?: string }) => submitMock(intent, opts),
}));

describe('EmptyStateCard 空状态引导卡', () => {
  beforeEach(() => submitMock.mockClear());

  it('渲染能力提示、标题、尝试引导与 4 个示例 chips', () => {
    const { container } = render(() => <EmptyStateCard />);
    expect(container.querySelector('.chat-feed-hint')?.textContent).toBe(t('rp.feed.hint'));
    expect(container.querySelector('.empty-state-title')?.textContent).toBe(t('rp.empty.title'));
    expect(container.querySelector('.empty-state-try')?.textContent).toBe(t('rp.empty.try'));
    const chips = container.querySelectorAll('.empty-state-example');
    expect(chips.length).toBe(4);
    expect(chips[0].textContent).toBe(t('rp.empty.example1'));
    expect(chips[3].textContent).toBe(t('rp.empty.example4'));
  });

  it('点击示例 chip → submitMessage(\'new\', { input: 示例文案 })', async () => {
    const { container } = render(() => <EmptyStateCard />);
    const chip = container.querySelectorAll('.empty-state-example')[1] as HTMLButtonElement;
    await fireEvent.click(chip);
    expect(submitMock).toHaveBeenCalledTimes(1);
    expect(submitMock).toHaveBeenCalledWith('new', { input: t('rp.empty.example2') });
  });
});
