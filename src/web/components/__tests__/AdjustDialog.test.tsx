/**
 * 微调浮动子对话浮窗组件测试（批 S4）。
 *
 * 钉死契约：
 * ① 浮窗开合：任一线程 open 才渲染；关闭仅隐藏（登记与历史存活）；
 * ② 历史装载：openThread 装载的历史消息渲染为用户/agent 气泡；
 * ③ 多轮推进：appendEvent 后流式块与终态气泡即时更新（工具步骤进折叠面板数据面）；
 * ④ delta 不进 chatState（scope fx 结构性分流的组件侧断言）；
 * ⑤ 运行中显示停止按钮（按 taskId 走既有停止通道）；打开浮窗惰性订阅。
 */
import { render, fireEvent, waitFor } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/conversations', () => ({ getOrCreateAdjustThread: vi.fn() }));
vi.mock('@/hooks/use-sse', () => ({
  streamAgentChat: vi.fn(async () => {}),
  subscribeScopeThread: vi.fn(),
}));
vi.mock('@/api/sse', () => ({ stopAgentTask: vi.fn(async () => ({ ok: true, cancelled: 1 })) }));
vi.mock('@/stores/agent-prefs', () => ({ agentProvider: () => 'provA', agentModel: () => 'model-A' }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));
// 渲染件桩化：本测试钉浮窗数据面接线，子件自身契约归各自测试
vi.mock('@/components/right-panel/MarkdownBubble', () => ({
  MarkdownBubble: (props: { text: string }) => <div class="chat-markdown-stub">{props.text}</div>,
}));
vi.mock('@/components/right-panel/ImageResultCard', () => ({
  ImageResultCard: (props: { card: { image_urls?: string[] } }) => (
    <div class="image-card-stub">{(props.card.image_urls || []).join('|')}</div>
  ),
}));
vi.mock('@/components/right-panel/VideoResultCard', () => ({
  VideoResultCard: () => <div class="video-card-stub" />,
}));
vi.mock('@/components/right-panel/AgentTimeline', () => ({
  AgentTimeline: (props: { items: unknown[] }) => (
    <div class="agent-timeline-stub" data-items={String(props.items.length)} />
  ),
}));

import { AdjustDialog } from '../left-panel/AdjustDialog';
import {
  adjustScopes, adjustScopeActions, type AdjustScopeTarget,
} from '@/stores/adjust-scopes';
import { chatState } from '@/stores/chat';
import { getOrCreateAdjustThread } from '@/api/conversations';
import { stopAgentTask } from '@/api/sse';
import { streamAgentChat, subscribeScopeThread } from '@/hooks/use-sse';

const target: AdjustScopeTarget = {
  kind: 'adjust', cat: 'keyElement', group_id: 'g1', draft_id: 'd1', label: '月球 第 1-1 卡',
};

beforeEach(() => {
  adjustScopeActions.reset();
  vi.mocked(getOrCreateAdjustThread).mockReset();
  vi.mocked(streamAgentChat).mockReset().mockResolvedValue(undefined);
  vi.mocked(subscribeScopeThread).mockReset();
  vi.mocked(stopAgentTask).mockClear();
});

describe('浮窗开合', () => {
  it('无线程不渲染；open 后渲染标题「微调 | <label>」', async () => {
    const empty = render(() => <AdjustDialog />);
    expect(empty.container.querySelector('.adjust-dialog')).toBeNull();
    empty.unmount();

    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
    const { container } = render(() => <AdjustDialog />);
    expect(container.querySelector('.adjust-dialog')).toBeTruthy();
    expect(container.querySelector('.adjust-dialog-title')?.textContent).toBe('微调 | 月球 第 1-1 卡');
    // 底部区惰性装载：输入行异步到位（占位文案引导说明素材用途）
    await waitFor(() => expect(container.querySelector('.adjust-dialog-input')).toBeTruthy());
    expect(container.querySelector('.adjust-dialog-input')?.getAttribute('placeholder'))
      .toBe('输入调整要求，可附参考素材并说明用途（风格/内容/结构参考）');
  });

  it('关闭仅隐藏：浮窗收起但线程登记与历史存活（可再开）', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({
      conversation_id: 'convT', messages: [{ sender: 'user', text: '改亮一点' }],
    });
    await adjustScopeActions.openThread(target);
    const { container } = render(() => <AdjustDialog />);
    expect(container.querySelector('.adjust-dialog')).toBeTruthy();

    await fireEvent.click(container.querySelector('.adjust-dialog-close') as HTMLElement);
    expect(container.querySelector('.adjust-dialog')).toBeNull();
    // 仅隐藏：登记、对话、历史全部存活
    expect(adjustScopes['d1']).toBeTruthy();
    expect(adjustScopes['d1'].open).toBe(false);
    expect(adjustScopes['d1'].messages).toHaveLength(1);
    // 再点入口（=再次 openThread 装载成功）浮窗重新渲染，历史仍在
    await adjustScopeActions.openThread(target);
    expect(container.querySelector('.adjust-dialog')).toBeTruthy();
    expect(container.querySelector('.adjust-bubble-user')?.textContent).toBe('改亮一点');
  });
});

describe('历史装载与多轮推进', () => {
  beforeEach(() => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({
      conversation_id: 'convT',
      messages: [
        { sender: 'user', text: '改亮一点' },
        { sender: 'agent', text: '已调整画面亮度' },
      ],
    });
  });

  it('openThread 装载的历史渲染为用户气泡与 agent 气泡（含图卡派生位）', async () => {
    await adjustScopeActions.openThread(target);
    const { container } = render(() => <AdjustDialog />);
    expect(container.querySelector('.adjust-bubble-user')?.textContent).toBe('改亮一点');
    expect(container.querySelector('.chat-markdown-stub')?.textContent).toBe('已调整画面亮度');
  });

  it('appendEvent 多轮推进：delta 流式气泡 → 工具步骤进折叠面板 → done 落终态气泡', async () => {
    await adjustScopeActions.openThread(target);
    adjustScopeActions.registerTask('d1', 'tX');
    const { container } = render(() => <AdjustDialog />);

    adjustScopeActions.appendEvent('d1', { kind: 'delta', text: '正在' });
    adjustScopeActions.appendEvent('d1', { kind: 'delta', text: '修改…' });
    const bubbles = () => Array.from(container.querySelectorAll('.chat-markdown-stub'))
      .map((e) => e.textContent);
    expect(bubbles()).toContain('正在修改…');
    // 工具步骤进折叠面板数据面（复用 AgentTimeline）
    adjustScopeActions.appendEvent('d1', { kind: 'tool_started', id: 'tl1', name: 'patch', summary: '改卡' });
    expect(container.querySelector('.agent-timeline-stub')?.getAttribute('data-items')).toBe('1');

    // done 终态：流式块收起，终态气泡（含图卡）落消息流
    adjustScopeActions.appendEvent('d1', {
      kind: 'done',
      payload: {
        text: '微调完成', elapsed_ms: 100, steps: 1, applied_actions: 1,
        chat_inserts: [{ kind: 'image', url: '/workspace/assets/a.png', name: 'a.png' }],
      },
    });
    expect(container.querySelector('.agent-timeline-stub')).toBeNull();
    const stubs = Array.from(container.querySelectorAll('.chat-markdown-stub')).map((e) => e.textContent);
    expect(stubs).toContain('微调完成');
    expect(container.querySelector('.image-card-stub')?.textContent).toBe('/workspace/assets/a.png');
  });

  it('delta 全程不进 chatState（主聊天区零痕迹的组件侧断言）', async () => {
    await adjustScopeActions.openThread(target);
    adjustScopeActions.registerTask('d1', 'tX');
    render(() => <AdjustDialog />);
    adjustScopeActions.appendEvent('d1', { kind: 'delta', text: '浮窗正文' });
    adjustScopeActions.appendEvent('d1', { kind: 'status', text: '正在处理…' });
    expect(chatState.messages.length).toBe(0);
    expect(chatState.streamingText).toBe('');
    expect(chatState.isStreaming).toBe(false);
  });
});

describe('输入续聊与停止', () => {
  it('运行中显示停止按钮：点击按 taskId 走既有停止通道；浮窗打开惰性订阅', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
    adjustScopeActions.registerTask('d1', 'tX');
    const { container } = render(() => <AdjustDialog />);

    expect(subscribeScopeThread).toHaveBeenCalledWith('d1');
    await waitFor(() => expect(container.querySelector('.adjust-dialog-stop')).toBeTruthy());
    expect(container.querySelector('.adjust-dialog-send')).toBeNull();
    await fireEvent.click(container.querySelector('.adjust-dialog-stop') as HTMLElement);
    expect(stopAgentTask).toHaveBeenCalledWith('tX');
  });

  it('空闲显示发送按钮：输入后 Enter 走 sendAdjust 续聊并清空输入', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
    const { container } = render(() => <AdjustDialog />);

    await waitFor(() => expect(container.querySelector('.adjust-dialog-input')).toBeTruthy());
    const input = container.querySelector('.adjust-dialog-input') as HTMLInputElement;
    expect(container.querySelector('.adjust-dialog-send')).toBeTruthy();
    await fireEvent.input(input, { target: { value: '再暗一点' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(streamAgentChat).toHaveBeenCalledTimes(1);
    const [req, opts] = vi.mocked(streamAgentChat).mock.calls[0];
    expect(opts).toMatchObject({ scope: true });
    expect(req).toMatchObject({ message: '再暗一点', conversation_id: 'convT' });
    expect(input.value).toBe('');
    expect(adjustScopes['d1'].messages.some((m) => m.sender === 'user' && m.text === '再暗一点')).toBe(true);
  });
});
