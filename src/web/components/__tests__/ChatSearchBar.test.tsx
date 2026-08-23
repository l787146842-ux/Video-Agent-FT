/**
 * 消息搜索与轮次跳转条测试：
 * ① 无查询词 → 轮次跳转列表（问/答标签 + 组首摘录），点击即跳转并收起；
 * ② 有查询词 → 全文搜索命中列表，无命中展示空态文案；
 * ③ Enter 跳首条、Esc 收起（跳转经 chat-scroll-bridge 委托 ChatFeed）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const scrollMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/chat/chat-scroll-bridge', () => ({ requestScrollToMessage: scrollMock }));

import { ChatSearchBar } from '../right-panel/ChatSearchBar';
import { chatActions } from '@/stores/chat';
import { t } from '@/lib/locale';
import type { ChatMessage } from '@/types';

const user = (text: string): ChatMessage => ({ sender: 'user', text });
const agent = (text: string, extra?: Partial<ChatMessage>): ChatMessage =>
  ({ sender: 'agent', text, ...extra });

const SEED: ChatMessage[] = [
  user('帮我写一段开场白'),
  agent('好的，开场白如下', { turnId: 't1' }),
  user('把分镜脚本也整理一下'),
  agent('', { docCard: '分镜脚本.md', turnId: 't2' }),
];

describe('ChatSearchBar 搜索与轮次跳转条', () => {
  beforeEach(() => {
    scrollMock.mockClear();
    chatActions.loadMessages(SEED);
    chatActions.clearStreaming();
  });

  function items(container: HTMLElement) {
    return Array.from(container.querySelectorAll('.chat-search-item')) as HTMLButtonElement[];
  }

  it('无查询词：列出全部轮次（问/答交替），点击跳转组首并收起', async () => {
    const onClose = vi.fn();
    const { container } = render(() => <ChatSearchBar onClose={onClose} />);
    const list = items(container);
    expect(list.length).toBe(4);
    expect(list[0].querySelector('.chat-search-tag')?.textContent).toBe(t('rp.search.ask'));
    expect(list[1].querySelector('.chat-search-tag')?.textContent).toBe(t('rp.search.answer'));
    await fireEvent.click(list[2]);
    expect(scrollMock).toHaveBeenCalledWith(2);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('有查询词：只展示命中条目，点击跳转命中原消息下标', async () => {
    const onClose = vi.fn();
    const { container } = render(() => <ChatSearchBar onClose={onClose} />);
    const input = container.querySelector('.chat-search-input') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '开场白' } });
    const list = items(container);
    expect(list.length).toBe(2);
    await fireEvent.click(list[1]);
    expect(scrollMock).toHaveBeenCalledWith(1);
    expect(onClose).toHaveBeenCalled();
  });

  it('查询无命中 → 空态文案；Enter 跳首条命中', async () => {
    const { container } = render(() => <ChatSearchBar onClose={() => {}} />);
    const input = container.querySelector('.chat-search-input') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '完全不存在的词' } });
    expect(container.querySelector('.chat-search-empty')?.textContent).toBe(t('rp.search.noResult'));

    fireEvent.input(input, { target: { value: '分镜' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    // 命中：用户消息正文 + 文档卡名各一条，Enter 跳首条（下标 2）
    expect(scrollMock).toHaveBeenCalledWith(2);
  });

  it('Esc 收起搜索条', () => {
    const onClose = vi.fn();
    const { container } = render(() => <ChatSearchBar onClose={onClose} />);
    const input = container.querySelector('.chat-search-input') as HTMLInputElement;
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
