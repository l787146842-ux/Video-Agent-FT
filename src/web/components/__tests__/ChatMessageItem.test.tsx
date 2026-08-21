/**
 * ChatMessageItem 交互控制点组件测试（P4-20）。
 *
 * 钉死契约：
 * ① 编辑控制点（P4-20）：editable 挂载位渲染「编辑」按钮，点击经
 *    chat-input-bridge 回填通道发出原文（排队消息编辑同款通道）；
 *    未挂 editable 的消息不渲染按钮。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ChatMessageItem } from '../right-panel/ChatMessageItem';
import type { ChatMessage } from '@/types';

// 本测试不触路由：useNavigate 以空跳转桩替代（避免 Router 上下文依赖）
vi.mock('@solidjs/router', () => ({ useNavigate: () => () => {} }));

const backfillMock = vi.fn();
vi.mock('@/lib/chat-input-bridge', () => ({
  requestEditBackfill: (text: string) => backfillMock(text),
}));

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: () => Promise.resolve(true),
}));

describe('P4-20 用户气泡编辑控制点', () => {
  beforeEach(() => backfillMock.mockClear());

  it('editable 挂载位渲染「编辑」按钮；点击以原文经回填通道发出', async () => {
    const msg: ChatMessage = { sender: 'user', text: '写一段开场白' };
    const { container } = render(() => <ChatMessageItem message={msg} isLast editable />);
    const btn = container.querySelector('.msg-edit-btn') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await fireEvent.click(btn);
    expect(backfillMock).toHaveBeenCalledTimes(1);
    expect(backfillMock).toHaveBeenCalledWith('写一段开场白');
  });

  it('未挂 editable 的用户消息与 agent 消息均不渲染编辑按钮', () => {
    const userMsg: ChatMessage = { sender: 'user', text: '你好' };
    const agentMsg: ChatMessage = { sender: 'agent', text: '你好，我在' };
    const a = render(() => <ChatMessageItem message={userMsg} isLast />);
    expect(a.container.querySelector('.msg-edit-btn')).toBeNull();
    const b = render(() => <ChatMessageItem message={agentMsg} isLast />);
    expect(b.container.querySelector('.msg-edit-btn')).toBeNull();
  });
});
