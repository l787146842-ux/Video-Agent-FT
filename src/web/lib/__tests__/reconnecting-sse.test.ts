import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createReconnectingSSE } from '../reconnecting-sse';
import { setGlobalApiKey } from '@/api/client';

/**
 * reconnecting-sse 传输测试（任务7/P0：EventSource → fetch + ReadableStream）。
 * 覆盖：鉴权头携带、帧解析投递、HTTP 失败指数退避重连、成功重置退避、
 * close() 断根、服务端关流自动重连。
 */

const fetchMock = vi.fn();

/** 构造 SSE 响应假件：按帧推送后自然关流（pumpSseBody 只消费 body.getReader） */
function sseResponse(frames: string[], status = 200): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(enc.encode(f));
      controller.close();
    },
  });
  return { ok: status >= 200 && status < 300, status, body } as unknown as Response;
}

/** 永不关流的响应（订阅保持打开用） */
function openStreamResponse(): Response {
  const body = new ReadableStream<Uint8Array>({ start() { /* 不 close：保持读挂起 */ } });
  return { ok: true, status: 200, body } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  vi.useFakeTimers();
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('createReconnectingSSE（fetch 传输）', () => {
  it('创建时立即 fetch 订阅；携带 X-API-Key（生产鉴权闭环）', async () => {
    setGlobalApiKey('sk-prod-456');
    fetchMock.mockReturnValue(new Promise(() => {})); // 保持挂起，不触发重连
    const sse = createReconnectingSSE('/api/generate/events', () => {});
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/generate/events');
    expect(init.headers['X-API-Key']).toBe('sk-prod-456');
    sse.close();
  });

  it('未配置 Key 时不注入 X-API-Key（开发模式后端不校验，头缺省无害）', () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    const sse = createReconnectingSSE('/api/test', () => {});
    expect(fetchMock.mock.calls[0][1].headers['X-API-Key']).toBeUndefined();
    sse.close();
  });

  it('data 帧投递 onMessage；注释帧（心跳）与非 data 行忽略', async () => {
    fetchMock.mockResolvedValueOnce(sseResponse([
      ': heartbeat\n\n',
      'event: noise\n\n',
      'data: {"status":"started"}\n\n',
    ]));
    // 首流结束后会排重连定时器：给个长 initialDelay 避免干扰断言
    const messages: string[] = [];
    const sse = createReconnectingSSE('/api/test', (d) => messages.push(d), { initialDelay: 60000 });
    await vi.advanceTimersByTimeAsync(0); // 冲刷 fetch/pump 微任务
    expect(messages).toEqual(['{"status":"started"}']);
    sse.close();
  });

  it('HTTP 失败后指数退避重连（1s → 2s）', async () => {
    fetchMock.mockImplementation(async () => sseResponse([], 401));
    const sse = createReconnectingSSE('/api/test', () => {}, { initialDelay: 1000, backoffFactor: 2 });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // 第二次失败：退避翻倍到 2s
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    sse.close();
  });

  it('连接成功且流内收到数据帧后重置退避延迟', async () => {
    // 响应队列：首次 500 → 1s 后重连；第二次成功（退避重置）→ 关流后又 1s 重连
    fetchMock.mockResolvedValueOnce(sseResponse([], 500))
      .mockResolvedValueOnce(sseResponse(['data: 1\n\n']))
      .mockImplementation(async () => sseResponse([], 500));
    const sse = createReconnectingSSE('/api/test', () => {}, { initialDelay: 1000, backoffFactor: 2 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // 第二次连接成功且流内有数据帧（流打开后立即关闭 → 又排重连）：退避应重置回 1s 而非 2s
    await vi.advanceTimersByTimeAsync(999);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    sse.close();
  });

  it('连接成功但流内无数据帧：不重置退避（收紧，防服务端瞬断洗白退避）', async () => {
    fetchMock.mockResolvedValueOnce(sseResponse([], 500))
      .mockResolvedValueOnce(sseResponse([])) // HTTP 200 但无任何 data 帧
      .mockImplementation(async () => sseResponse([], 500));
    const sse = createReconnectingSSE('/api/test', () => {}, { initialDelay: 1000, backoffFactor: 2 });
    await vi.advanceTimersByTimeAsync(0); // #1 失败
    await vi.advanceTimersByTimeAsync(1000); // #2 成功无数据帧（退避已翻倍到 2s，不重置）
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // 下次重连按 2s 而非 1s
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    sse.close();
  });

  it('服务端正常关流 → 自动重连（订阅不得静默死亡）', async () => {
    fetchMock.mockImplementation(async () => sseResponse(['data: {"a":1}\n\n']));
    const sse = createReconnectingSSE('/api/test', () => {}, { initialDelay: 500 });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(500);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    sse.close();
  });

  it('close() 后不再重连（定时器与在途连接一并断根）', async () => {
    fetchMock.mockImplementation(async () => sseResponse([], 500));
    const sse = createReconnectingSSE('/api/test', () => {}, { initialDelay: 100 });
    await vi.advanceTimersByTimeAsync(0);
    sse.close();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('退避上限硬 cap 15s（传 30000 也被钳到 15000）', async () => {
    fetchMock.mockImplementation(async () => sseResponse([], 500));
    // 无 cap 时退避序列 1+2+4+8+16=31s 才第 6 次；钳到 15s 后第 5 段 15s，30s 即达
    const sse = createReconnectingSSE('/api/test', () => {}, {
      initialDelay: 1000, backoffFactor: 2, maxDelay: 30000,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(30000);
    expect(fetchMock).toHaveBeenCalledTimes(6);
    sse.close();
  });
});
