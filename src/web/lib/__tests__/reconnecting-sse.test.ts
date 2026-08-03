import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createReconnectingSSE } from '../reconnecting-sse';

/**
 * reconnecting-sse 工具函数测试
 * 覆盖：连接建立、消息接收、断线重连、手动关闭
 */

// Mock EventSource
class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  // 测试辅助：模拟连接成功
  simulateOpen() {
    this.onopen?.();
  }

  // 测试辅助：模拟收到消息
  simulateMessage(data: string) {
    this.onmessage?.({ data });
  }

  // 测试辅助：模拟连接错误
  simulateError() {
    this.onerror?.();
  }
}

describe('createReconnectingSSE', () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal('EventSource', MockEventSource);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('创建时立即建立连接', () => {
    const sse = createReconnectingSSE('/api/test', () => {});
    expect(MockEventSource.instances.length).toBe(1);
    expect(MockEventSource.instances[0].url).toBe('/api/test');
    sse.close();
  });

  it('收到消息时调用 onMessage 回调', () => {
    const messages: string[] = [];
    const sse = createReconnectingSSE('/api/test', (data) => messages.push(data));

    const es = MockEventSource.instances[0];
    es.simulateOpen();
    es.simulateMessage('{"event":"test"}');

    expect(messages).toEqual(['{"event":"test"}']);
    sse.close();
  });

  it('断线后指数退避重连', () => {
    const sse = createReconnectingSSE('/api/test', () => {}, {
      initialDelay: 1000,
      backoffFactor: 2,
      maxDelay: 30000,
    });

    const es1 = MockEventSource.instances[0];
    es1.simulateOpen();
    es1.simulateError();

    // 第一次重连：1000ms 后
    expect(MockEventSource.instances.length).toBe(1);
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances.length).toBe(2);

    // 第二次断线：2000ms 后重连
    const es2 = MockEventSource.instances[1];
    es2.simulateError();
    vi.advanceTimersByTime(1999);
    expect(MockEventSource.instances.length).toBe(2);
    vi.advanceTimersByTime(1);
    expect(MockEventSource.instances.length).toBe(3);

    sse.close();
  });

  it('连接成功后重置退避延迟', () => {
    const sse = createReconnectingSSE('/api/test', () => {}, {
      initialDelay: 1000,
      backoffFactor: 2,
    });

    // 第一次断线 -> 1s 后重连
    MockEventSource.instances[0].simulateError();
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances.length).toBe(2);

    // 第二次连接成功 -> 重置延迟
    MockEventSource.instances[1].simulateOpen();
    MockEventSource.instances[1].simulateError();

    // 应该又是 1s（而非 2s）
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances.length).toBe(3);

    sse.close();
  });

  it('close() 后不再重连', () => {
    const sse = createReconnectingSSE('/api/test', () => {}, { initialDelay: 100 });

    const es = MockEventSource.instances[0];
    sse.close();

    expect(es.closed).toBe(true);
    // 即使触发 error 也不重连
    es.simulateError();
    vi.advanceTimersByTime(5000);
    expect(MockEventSource.instances.length).toBe(1);
  });
});
