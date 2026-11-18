import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fetchCanvasList } from '@/api/canvas';
import {
  canvasError, setCanvasError, probeCanvasOnline, stopCanvasProbe,
} from '@/stores/canvas';

/**
 * 画布加载探测（“画布加载失败”误报回归）：
 * - 口径分离：canvas_reachable 才决定“能否加载”，canvas_online（画布页已连 agent）不参与；
 * - 单次探测不再是终局：1s 一轮轮询，连续两轮不可达才亮覆盖层，任一轮可达即自动收起；
 * - 卸载/重试可中止在途轮次，防旧轮次回写状态。
 */

vi.mock('@/api/canvas', () => ({
  fetchCanvasList: vi.fn(),
  fetchCanvasSelection: vi.fn(),
}));
vi.mock('@/stores/studio', () => ({ state: { canvasUrl: 'http://127.0.0.1:3000' } }));

const list = fetchCanvasList as ReturnType<typeof vi.fn>;

function listResult(over: Record<string, unknown> = {}) {
  return { canvases: [], canvas_online: true, canvas_reachable: true, ...over };
}

describe('probeCanvasOnline', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    list.mockReset();
    stopCanvasProbe();
    setCanvasError(false);
  });
  afterEach(() => {
    stopCanvasProbe();
    vi.useRealTimers();
  });

  it('服务可达但画布页未连 agent → 不报加载失败', async () => {
    list.mockResolvedValue(listResult({ canvas_online: false, canvas_reachable: true }));
    const pending = probeCanvasOnline();
    await vi.advanceTimersByTimeAsync(0);
    expect(canvasError()).toBe(false);
    await expect(pending).resolves.toBe(true);
  });

  it('连续两轮不可达才亮覆盖层，随后可达自动收起', async () => {
    list
      .mockResolvedValueOnce(listResult({ canvas_reachable: false }))
      .mockResolvedValueOnce(listResult({ canvas_reachable: false }))
      .mockResolvedValueOnce(listResult({ canvas_reachable: true }));
    const pending = probeCanvasOnline();
    await vi.advanceTimersByTimeAsync(0);
    expect(canvasError()).toBe(false); // 首轮失败：冷启动窗口，不闪报
    await vi.advanceTimersByTimeAsync(1000);
    expect(canvasError()).toBe(true); // 第二轮仍失败 → 提示
    await vi.advanceTimersByTimeAsync(1000);
    expect(canvasError()).toBe(false); // 第三轮可达 → 自愈
    await expect(pending).resolves.toBe(true);
  });

  it('老后端无 canvas_reachable 时回落 canvas_online 口径', async () => {
    list.mockResolvedValue({ canvases: [], canvas_online: false });
    const pending = probeCanvasOnline();
    await vi.advanceTimersByTimeAsync(1000);
    expect(canvasError()).toBe(true);
    stopCanvasProbe();
    await vi.advanceTimersByTimeAsync(1000);
    await expect(pending).resolves.toBe(false);
  });

  it('stopCanvasProbe 中止在途轮询（不再发请求）', async () => {
    list.mockResolvedValue(listResult({ canvas_reachable: false }));
    const pending = probeCanvasOnline();
    await vi.advanceTimersByTimeAsync(0);
    expect(list).toHaveBeenCalledTimes(1);
    stopCanvasProbe();
    await vi.advanceTimersByTimeAsync(20000);
    expect(list).toHaveBeenCalledTimes(1);
    await expect(pending).resolves.toBe(false);
  });
});
