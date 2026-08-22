import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createHealthMonitor } from '@/lib/health';

// 状态机只测注入依赖：隔离重组件链（use-sse → stores）与真实网络探测
vi.mock('@/hooks/use-sse', () => ({ resumeAgentTasks: vi.fn() }));
vi.mock('@/api/health', () => ({ fetchBackendHealth: vi.fn() }));

/**
 * 全局健康层状态机：
 * offline → banner → online → resume（onRecover 断言）；
 * backend-down 心跳缩短；offline 期间不轮询；stale 探测丢弃。
 */

interface FakeEvent { cbs: Array<() => void>; }

function fakeChannel(): FakeEvent & { fire: () => void; sub: (cb: () => void) => () => void } {
  const ch: FakeEvent = { cbs: [] };
  return {
    ...ch,
    fire: () => [...ch.cbs].forEach((cb) => cb()),
    sub: (cb) => { ch.cbs.push(cb); return () => { ch.cbs = ch.cbs.filter((x) => x !== cb); }; },
  };
}

async function flush(): Promise<void> {
  // 冲刷微任务，让 checkNow 的 await probe() 落地
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

type MockFn = ReturnType<typeof vi.fn>;

function setup(overrides: Partial<Parameters<typeof createHealthMonitor>[0]> = {}) {
  let online = true;
  const onRecover = vi.fn();
  const onlineCh = fakeChannel();
  const offlineCh = fakeChannel();
  const opts = {
    probe: vi.fn().mockResolvedValue({ ok: true }),
    isOnline: () => online,
    subscribeOnline: onlineCh.sub,
    subscribeOffline: offlineCh.sub,
    healthyIntervalMs: 30_000,
    downIntervalMs: 5_000,
    onRecover,
    ...overrides,
  } as Parameters<typeof createHealthMonitor>[0] & { probe: MockFn };
  const monitor = createHealthMonitor(opts);
  return {
    monitor, probe: opts.probe, onRecover, onlineCh, offlineCh,
    setOnline: (v: boolean) => { online = v; },
  };
}

describe('createHealthMonitor 状态机', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('启动即探测：后端健康 → online，健康间隔轮询', async () => {
    const { monitor, probe } = setup();
    monitor.start();
    await flush();
    expect(monitor.status()).toBe('online');
    expect(probe).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(30_000);
    await flush();
    expect(probe).toHaveBeenCalledTimes(2);
    monitor.stop();
  });

  it('探测失败 → backend-down，心跳缩短到 downInterval', async () => {
    const { monitor, probe } = setup({ probe: vi.fn().mockResolvedValue({ ok: false }) });
    monitor.start();
    await flush();
    expect(monitor.status()).toBe('backend-down');
    // 健康间隔内不该提前探测；断连间隔（5s）到点即探
    vi.advanceTimersByTime(4_999);
    await flush();
    expect(probe).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    await flush();
    expect(probe).toHaveBeenCalledTimes(2);
    monitor.stop();
  });

  it('backend-down → 恢复：翻转为 online 且 onRecover 仅触发一次', async () => {
    const probe = vi.fn().mockResolvedValue({ ok: false });
    const { monitor, onRecover } = setup({ probe });
    monitor.start();
    await flush();
    expect(monitor.status()).toBe('backend-down');
    probe.mockResolvedValue({ ok: true });
    vi.advanceTimersByTime(5_000);
    await flush();
    expect(monitor.status()).toBe('online');
    expect(onRecover).toHaveBeenCalledTimes(1);
    // 后续健康轮询不重复触发 resume
    vi.advanceTimersByTime(60_000);
    await flush();
    expect(onRecover).toHaveBeenCalledTimes(1);
    monitor.stop();
  });

  it('offline → 横幅状态，期间不轮询；online 事件触发即时探测并 resume', async () => {
    const { monitor, probe, onRecover, setOnline, onlineCh, offlineCh } = setup();
    monitor.start();
    await flush();
    expect(monitor.status()).toBe('online');

    setOnline(false);
    offlineCh.fire();
    await flush();
    expect(monitor.status()).toBe('offline');

    // offline 期间即使时间流逝也不探测（省电/无意义）
    const callsBefore = probe.mock.calls.length;
    vi.advanceTimersByTime(120_000);
    await flush();
    expect(probe.mock.calls.length).toBe(callsBefore);

    // 网络恢复：online 事件 → 即时探测 → 翻转 + onRecover
    setOnline(true);
    onlineCh.fire();
    await flush();
    expect(monitor.status()).toBe('online');
    expect(onRecover).toHaveBeenCalledTimes(1);
    monitor.stop();
  });

  it('探测抛错视为后端失联', async () => {
    const { monitor } = setup({ probe: vi.fn().mockRejectedValue(new Error('network')) });
    monitor.start();
    await flush();
    expect(monitor.status()).toBe('backend-down');
    monitor.stop();
  });

  it('断网作废在途探测：stale 成功响应不得把 offline 翻回 online', async () => {
    let resolveProbe: (v: { ok: boolean }) => void = () => {};
    const probe = vi.fn(() => new Promise<{ ok: boolean }>((r) => { resolveProbe = r; }));
    const { monitor, setOnline, offlineCh } = setup({ probe });
    monitor.start();
    // 探测在途时断网
    setOnline(false);
    offlineCh.fire();
    await flush();
    expect(monitor.status()).toBe('offline');
    // 断网前的探测姗姗来迟且成功：状态保持 offline
    resolveProbe({ ok: true });
    await flush();
    expect(monitor.status()).toBe('offline');
    monitor.stop();
  });

  it('stop 后不再轮询、不再触发 onRecover', async () => {
    const { monitor, probe, onRecover } = setup({ probe: vi.fn().mockResolvedValue({ ok: false }) });
    monitor.start();
    await flush();
    monitor.stop();
    vi.advanceTimersByTime(600_000);
    await flush();
    expect(probe).toHaveBeenCalledTimes(1);
    expect(onRecover).not.toHaveBeenCalled();
  });
});
