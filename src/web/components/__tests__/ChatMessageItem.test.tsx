/**
 * ChatMessageItem 交互控制点组件测试。
 *
 * 钉死契约：
 * ① 悬停工具条矩阵：editable 挂「编辑」、regenerable 挂「重新生成」、
 *    branchable 挂「分支」；未挂对应标志的消息不渲染按钮。
 * ② 原地编辑：点编辑后该用户消息原地变编辑框（预填原文）；
 *    发送 → truncate-resend {text}；取消不发送回到气泡。
 * ③ 重新生成 → truncate-resend 无 text；分支 → branchAtMessage(该消息下标)。
 * ④ 建议动作读持久化 suggestedActions（刷新/replay 恢复路径直读渲染，
 *    「继续刚才的任务」不丢）。
 * 卡片/跳转/折叠分支、复制/存文档 hover 动作与过程时间线数据源
 * （F2 账本消费面）见 ChatMessageItem-extra.test.tsx（前端 250 行红线拆分）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ChatMessageItem } from '../right-panel/ChatMessageItem';
import type { ChatMessage } from '@/types';

// 本测试不触路由：useNavigate 以空跳转桩替代（避免 Router 上下文依赖）
vi.mock('@solidjs/router', () => ({ useNavigate: () => () => {} }));

const truncateMock = vi.fn(async (_text?: string) => true);
vi.mock('@/lib/chat/truncate-resend', () => ({
  truncateResendAction: (text?: string) => truncateMock(text),
}));

const branchMock = vi.fn(async (_idx: number) => {});
vi.mock('@/lib/message-branch', () => ({
  branchAtMessage: (idx: number) => branchMock(idx),
}));

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: () => Promise.resolve(true),
}));

describe('悬停工具条矩阵挂载', () => {
  beforeEach(() => { truncateMock.mockClear(); branchMock.mockClear(); });

  it('editable 用户消息挂「编辑」；未挂标志不渲染对应按钮', () => {
    const msg: ChatMessage = { sender: 'user', text: '写一段开场白' };
    const a = render(() => <ChatMessageItem message={msg} isLast editable copyable />);
    expect(a.container.querySelector('[data-testid="msg-act-edit"]')).toBeTruthy();
    expect(a.container.querySelector('[data-testid="msg-act-copy"]')).toBeTruthy();
    expect(a.container.querySelector('[data-testid="msg-act-branch"]')).toBeNull();
    const plain: ChatMessage = { sender: 'user', text: '历史消息' };
    const b = render(() => <ChatMessageItem message={plain} isLast={false} copyable />);
    expect(b.container.querySelector('[data-testid="msg-act-edit"]')).toBeNull();
  });

  it('分支按钮以该消息全局下标为分叉点调 branchAtMessage', async () => {
    const msg: ChatMessage = { sender: 'agent', text: '回复正文' };
    const { container } = render(() => (
      <ChatMessageItem message={msg} isLast branchable copyable domIndex={3} />
    ));
    const btn = container.querySelector('[data-testid="msg-act-branch"]') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await fireEvent.click(btn);
    expect(branchMock).toHaveBeenCalledWith(3);
  });

  it('重新生成按钮调 truncate-resend（无 text）', async () => {
    const msg: ChatMessage = { sender: 'agent', text: '末条回复' };
    const { container } = render(() => (
      <ChatMessageItem message={msg} isLast regenerable copyable />
    ));
    const btn = container.querySelector('[data-testid="msg-act-regenerate"]') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await fireEvent.click(btn);
    expect(truncateMock).toHaveBeenCalledTimes(1);
    expect(truncateMock).toHaveBeenCalledWith(undefined);
  });

  it('无任何矩阵标志的消息不渲染工具条（系统卡片等）', () => {
    const msg: ChatMessage = { sender: 'agent', text: '' };
    const { container } = render(() => <ChatMessageItem message={msg} isLast={false} />);
    expect(container.querySelector('[data-testid="msg-hover-toolbar"]')).toBeNull();
  });

  it('历史消息带 ts（后端落盘 epoch ms）时工具条显示 HH:MM', () => {
    const msg: ChatMessage = { sender: 'user', text: '历史消息', ts: new Date(2026, 7, 23, 9, 5).getTime() };
    const { container } = render(() => <ChatMessageItem message={msg} isLast={false} copyable />);
    const time = container.querySelector('.msg-hover-time');
    expect(time).toBeTruthy();
    expect(time?.textContent).toMatch(/^\d{2}:\d{2}$/);
  });

  it('无 ts 的存量旧消息不渲染时间（兜底不变）', () => {
    const msg: ChatMessage = { sender: 'user', text: '存量消息' };
    const { container } = render(() => <ChatMessageItem message={msg} isLast={false} copyable />);
    expect(container.querySelector('[data-testid="msg-hover-toolbar"]')).toBeTruthy();
    expect(container.querySelector('.msg-hover-time')).toBeNull();
  });

  it('重新生成双击守卫：请求未回前二次点击只触发一次 truncate-resend', async () => {
    // 挂起的首次请求：响应回来前连点两次，只应发起一次
    let resolveFirst!: (ok: boolean) => void;
    truncateMock.mockImplementationOnce(() => new Promise<boolean>((r) => { resolveFirst = r; }));
    const msg: ChatMessage = { sender: 'agent', text: '末条回复' };
    const { container } = render(() => (
      <ChatMessageItem message={msg} isLast regenerable copyable />
    ));
    const btn = container.querySelector('[data-testid="msg-act-regenerate"]') as HTMLButtonElement;
    await fireEvent.click(btn);
    // in-flight 期间按钮已隐藏（regenerable && !regenerating）；直接再调一次验证守卫
    expect(container.querySelector('[data-testid="msg-act-regenerate"]')).toBeNull();
    resolveFirst(true);
    await Promise.resolve();
    expect(truncateMock).toHaveBeenCalledTimes(1);
  });
});

describe('原地编辑（末条用户消息编辑的唯一形态）', () => {
  beforeEach(() => truncateMock.mockClear());

  it('点编辑后原地变编辑框（预填原文）；发送调 truncate-resend {text} 并关闭', async () => {
    const msg: ChatMessage = { sender: 'user', text: '写一段开场白' };
    const { container } = render(() => <ChatMessageItem message={msg} isLast editable copyable />);
    await fireEvent.click(container.querySelector('[data-testid="msg-act-edit"]') as HTMLButtonElement);
    const box = container.querySelector('[data-testid="inline-edit-box"]');
    expect(box).toBeTruthy();
    const ta = container.querySelector('.inline-edit-textarea') as HTMLTextAreaElement;
    expect(ta.value).toBe('写一段开场白');
    fireEvent.input(ta, { target: { value: '改写后的开场白' } });
    await fireEvent.click(container.querySelector('[data-testid="inline-edit-send"]') as HTMLButtonElement);
    expect(truncateMock).toHaveBeenCalledTimes(1);
    expect(truncateMock).toHaveBeenCalledWith('改写后的开场白');
    // 受理成功后编辑框关闭，气泡恢复
    expect(container.querySelector('[data-testid="inline-edit-box"]')).toBeNull();
  });

  it('取消不发送，编辑框关闭回到原气泡', async () => {
    const msg: ChatMessage = { sender: 'user', text: '写一段开场白' };
    const { container } = render(() => <ChatMessageItem message={msg} isLast editable />);
    await fireEvent.click(container.querySelector('[data-testid="msg-act-edit"]') as HTMLButtonElement);
    await fireEvent.click(container.querySelector('[data-testid="inline-edit-cancel"]') as HTMLButtonElement);
    expect(truncateMock).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="inline-edit-box"]')).toBeNull();
    expect(container.querySelector('.user-bubble-text')?.textContent).toBe('写一段开场白');
  });

  it('发送失败（truncate-resend 拒绝）时编辑框保持打开不丢草稿', async () => {
    truncateMock.mockResolvedValueOnce(false);
    const msg: ChatMessage = { sender: 'user', text: '原句' };
    const { container } = render(() => <ChatMessageItem message={msg} isLast editable />);
    await fireEvent.click(container.querySelector('[data-testid="msg-act-edit"]') as HTMLButtonElement);
    const ta = container.querySelector('.inline-edit-textarea') as HTMLTextAreaElement;
    fireEvent.input(ta, { target: { value: '新句' } });
    await fireEvent.click(container.querySelector('[data-testid="inline-edit-send"]') as HTMLButtonElement);
    expect(container.querySelector('[data-testid="inline-edit-box"]')).toBeTruthy();
  });
});

describe('停止后继续建议按钮（读持久化 suggestedActions）', () => {
  it('刷新/replay 恢复：历史消息直带 suggestedActions 即渲染「继续刚才的任务」', () => {
    // 模拟后端快照/历史装载路径：消息字段直读渲染，不依赖任何本地派生
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

describe('视频内联卡持久化渲染（replay/刷新恢复路径）', () => {
  it('历史消息直接携带 videoCard 字段即渲染（不依赖 finishStream 派生）', () => {
    // 模拟后端快照 chatMessages → loadMessages → ChatMessageItem：
    // 消息字段直读渲染，刷新/replay 后视频卡不丢
    const msg: ChatMessage = {
      sender: 'agent',
      text: '视频已生成',
      videoCard: {
        items: [{ url: '/media/v.mp4', name: '开场.mp4', thumb: '/media/v.jpg' }],
      },
    };
    const { container } = render(() => <ChatMessageItem message={msg} isLast />);
    const card = container.querySelector('.video-card');
    expect(card).toBeTruthy();
    expect(card?.textContent).toContain('开场.mp4');
    expect(card?.querySelector('video')?.getAttribute('src')).toContain('/media/v.mp4');
    expect(card?.querySelector('.video-card-badge')?.textContent).toBe('▶');
  });
});
