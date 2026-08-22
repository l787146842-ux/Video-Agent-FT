/**
 * ChatMessageItem 交互控制点组件测试。
 *
 * 钉死契约：
 * ① 编辑控制点：editable 挂载位渲染「编辑」按钮，点击走编辑分支
 *    通道（edit-branch：快照派生新对话 + 原文回填），原对话不变；
 *    未挂 editable 的消息不渲染按钮。
 * ② 继续控制点：retry 建议按钮优先显示后端/本地派生的显式
 *    label（如「继续刚才的任务」），无 label 回落「重试」。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ChatMessageItem } from '../right-panel/ChatMessageItem';
import type { ChatMessage } from '@/types';

// 本测试不触路由：useNavigate 以空跳转桩替代（避免 Router 上下文依赖）
vi.mock('@solidjs/router', () => ({ useNavigate: () => () => {} }));

const editBranchMock = vi.fn(async (_text: string) => true);
vi.mock('@/lib/edit-branch', () => ({
  editMessageInBranch: (text: string) => editBranchMock(text),
}));

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: () => Promise.resolve(true),
}));

describe('用户气泡编辑控制点（编辑即分支）', () => {
  beforeEach(() => editBranchMock.mockClear());

  it('editable 挂载位渲染「编辑」按钮；点击以原文走编辑分支通道', async () => {
    const msg: ChatMessage = { sender: 'user', text: '写一段开场白' };
    const { container } = render(() => <ChatMessageItem message={msg} isLast editable />);
    const btn = container.querySelector('.msg-edit-btn') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await fireEvent.click(btn);
    expect(editBranchMock).toHaveBeenCalledTimes(1);
    expect(editBranchMock).toHaveBeenCalledWith('写一段开场白');
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

describe('停止后继续建议按钮文案', () => {
  it('retry 带显式 label 时按钮显示「继续刚才的任务」', () => {
    const msg: ChatMessage = {
      sender: 'agent',
      text: '（已停止）',
      suggestedActions: [{ kind: 'retry', label: '继续刚才的任务', value: '' }],
    };
    const { container } = render(() => <ChatMessageItem message={msg} isLast isSuggestedTarget />);
    const btn = container.querySelector('.suggested-action-btn') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    expect(btn.textContent).toBe('继续刚才的任务');
  });

  it('retry 无 label 时回落「重试」（机械重发语义不变）', () => {
    const msg: ChatMessage = {
      sender: 'agent',
      text: '（已停止）',
      suggestedActions: [{ kind: 'retry', label: '', value: '' }],
    };
    const { container } = render(() => <ChatMessageItem message={msg} isLast isSuggestedTarget />);
    const btn = container.querySelector('.suggested-action-btn') as HTMLButtonElement;
    expect(btn.textContent).toBe('重试');
  });
});
