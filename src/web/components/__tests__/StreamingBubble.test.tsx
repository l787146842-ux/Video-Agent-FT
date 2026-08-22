/**
 * StreamingBubble 组件测试（覆盖率闸 80% 纳入件）。
 *
 * 钉死契约：
 * ① 非流式/无文本时不挂载气泡；
 * ② 流式文本上屏（markdown 渲染进 .chat-bubble）；
 * ③ 120ms 节流：窗口内的 delta 由尾随定时器兜底渲染（最后一个 delta 必落地）；
 * ④ streamingModel 显示作者行。
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { StreamingBubble } from '../right-panel/StreamingBubble';
import { setChatState } from '@/stores/chat';

function resetStream() {
  setChatState('isStreaming', false);
  setChatState('streamingText', '');
  setChatState('streamingModel', '');
}

describe('StreamingBubble', () => {
  beforeEach(() => {
    resetStream();
    vi.useFakeTimers();
  });

  afterEach(() => {
    resetStream();
    vi.useRealTimers();
  });

  it('非流式或无文本时不渲染气泡', () => {
    const a = render(() => <StreamingBubble />);
    expect(a.container.querySelector('.chat-bubble')).toBeNull();
    a.unmount();
    // 流式中但尚无文本：同样不挂载（占位由别处负责）
    setChatState('isStreaming', true);
    const b = render(() => <StreamingBubble />);
    expect(b.container.querySelector('.chat-bubble')).toBeNull();
    b.unmount();
  });

  it('流式文本渲染进气泡且显示模型作者行', async () => {
    setChatState('isStreaming', true);
    setChatState('streamingModel', 'test-model');
    setChatState('streamingText', '你好世界');
    const { container, unmount } = render(() => <StreamingBubble />);
    // 首次到点即渲（elapsed >= 120ms）
    await vi.advanceTimersByTimeAsync(0);
    expect(container.querySelector('.chat-bubble')?.textContent).toContain('你好世界');
    expect(container.querySelector('.msg-author')?.textContent).toBe('test-model');
    unmount();
  });

  it('节流窗口内的 delta 由尾随定时器兜底渲染', async () => {
    setChatState('isStreaming', true);
    setChatState('streamingText', '第一段');
    const { container, unmount } = render(() => <StreamingBubble />);
    await vi.advanceTimersByTimeAsync(0);
    expect(container.querySelector('.chat-bubble')?.textContent).toContain('第一段');
    // 立即追加 delta（落在 120ms 节流窗口内）→ 挂尾随定时器
    setChatState('streamingText', '第一段第二段');
    await vi.advanceTimersByTimeAsync(150);
    expect(container.querySelector('.chat-bubble')?.textContent).toContain('第二段');
    unmount();
  });

  it('卸载清理尾随定时器不抛异常', async () => {
    setChatState('isStreaming', true);
    setChatState('streamingText', '内容');
    const { unmount } = render(() => <StreamingBubble />);
    setChatState('streamingText', '内容追加');
    unmount();
    expect(() => vi.advanceTimersByTimeAsync(200)).not.toThrow();
  });
});
