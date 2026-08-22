import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@solidjs/testing-library';
import { HealthBanner } from '@/components/shared/HealthBanner';
import { fetchBackendHealth } from '@/api/health';
import { resumeAgentTasks } from '@/hooks/use-sse';

/**
 * 全局断连横幅端到端状态流：
 * offline → 横幅（网络断开措辞）→ online → 横幅消失 + resumeAgentTasks 被调用。
 * 横幅与消息流气泡无关：挂载在 app 根层，文案走 t() 字典。
 */

// 隔离重组件链与真实网络：probe 与 resume 全走桩
vi.mock('@/hooks/use-sse', () => ({ resumeAgentTasks: vi.fn() }));
vi.mock('@/api/health', () => ({ fetchBackendHealth: vi.fn() }));
vi.mock('@/stores/studio', () => ({ state: { projectId: 'p-1' } }));

const probe = fetchBackendHealth as ReturnType<typeof vi.fn>;
const resume = resumeAgentTasks as ReturnType<typeof vi.fn>;

function setNavigatorOnLine(v: boolean) {
  Object.defineProperty(navigator, 'onLine', { value: v, configurable: true });
}

async function flush(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe('HealthBanner', () => {
  beforeEach(() => {
    probe.mockReset();
    resume.mockReset();
    probe.mockResolvedValue({ ok: true });
    setNavigatorOnLine(true);
  });
  afterEach(() => setNavigatorOnLine(true));

  it('后端健康：无横幅', async () => {
    const { unmount } = render(() => <HealthBanner />);
    await flush();
    expect(document.querySelector('.health-banner')).toBeNull();
    unmount();
  });

  it('浏览器断网：出现「网络已断开」横幅（offline 措辞）', async () => {
    const { unmount } = render(() => <HealthBanner />);
    await flush();
    setNavigatorOnLine(false);
    window.dispatchEvent(new Event('offline'));
    await flush();
    const banner = document.querySelector('.health-banner.offline');
    expect(banner).not.toBeNull();
    expect(banner!.textContent).toContain('网络已断开');
    unmount();
  });

  it('offline → online → resume：横幅消失并触发任务恢复', async () => {
    const { unmount } = render(() => <HealthBanner />);
    await flush();

    setNavigatorOnLine(false);
    window.dispatchEvent(new Event('offline'));
    await flush();
    expect(document.querySelector('.health-banner')).not.toBeNull();

    setNavigatorOnLine(true);
    window.dispatchEvent(new Event('online'));
    await flush();
    expect(document.querySelector('.health-banner')).toBeNull();
    expect(resume).toHaveBeenCalledTimes(1);
    expect(resume).toHaveBeenCalledWith('p-1');
    unmount();
  });

  it('后端失联（网络正常）：出现「后端服务失联」横幅；恢复后消失并 resume', async () => {
    probe.mockResolvedValue({ ok: false });
    const { unmount } = render(() => <HealthBanner />);
    await flush();
    const banner = document.querySelector('.health-banner.backend-down');
    expect(banner).not.toBeNull();
    expect(banner!.textContent).toContain('后端服务失联');

    probe.mockResolvedValue({ ok: true });
    window.dispatchEvent(new Event('online')); // 即时探测一次
    await flush();
    expect(document.querySelector('.health-banner')).toBeNull();
    expect(resume).toHaveBeenCalledWith('p-1');
    unmount();
  });
});
