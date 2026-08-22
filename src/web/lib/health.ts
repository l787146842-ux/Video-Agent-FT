/**
 * 全局健康层状态机：浏览器网络 + 后端 /health 双通道感知。
 *
 * 状态机：online ⇄ offline（navigator.onLine 事件驱动）
 *         online ⇄ backend-down（/health 心跳轮询驱动）
 * - 健康时间隔长（30s），断连后缩短（5s）加速恢复感知；
 * - offline 期间不轮询（省电/无意义），由 online 事件触发即时探测；
 * - 断连 → 恢复的翻转瞬间触发 onRecover（接线 resumeAgentTasks，
 *   不重复造重连：SSE 自身的指数退避只管传输层瞬断，任务级恢复走既有 resume）；
 * - 探测竞态防护：stale 响应（stop 后/被新探测取代）丢弃。
 *
 * 依赖全部注入（probe/事件订阅/计时回调），便于 vitest 假定时器钉死状态迁移。
 */
import { createSignal } from 'solid-js';
import { fetchBackendHealth } from '@/api/health';
import { resumeAgentTasks } from '@/hooks/use-sse';
import { state } from '@/stores/studio';

export type HealthStatus = 'online' | 'offline' | 'backend-down';

export interface HealthMonitorOptions {
  /** 后端探测（默认 fetchBackendHealth） */
  probe?: () => Promise<{ ok: boolean }>;
  /** 浏览器网络状态读取（默认 navigator.onLine） */
  isOnline?: () => boolean;
  /** online/offline 事件订阅器（默认 window 事件），返回退订函数 */
  subscribeOnline?: (cb: () => void) => () => void;
  subscribeOffline?: (cb: () => void) => () => void;
  /** 健康时心跳间隔（默认 30s） */
  healthyIntervalMs?: number;
  /** 断连后心跳间隔（默认 5s） */
  downIntervalMs?: number;
  /** 断连 → 恢复 翻转回调（接 resumeAgentTasks；每次翻转只触发一次） */
  onRecover?: () => void;
}

export interface HealthMonitor {
  status: () => HealthStatus;
  start: () => void;
  stop: () => void;
  checkNow: () => Promise<void>;
}

export function createHealthMonitor(opts: HealthMonitorOptions = {}): HealthMonitor {
  const probe = opts.probe ?? (() => fetchBackendHealth());
  const isOnline = opts.isOnline ?? (() => navigator.onLine);
  const healthyMs = opts.healthyIntervalMs ?? 30_000;
  const downMs = opts.downIntervalMs ?? 5_000;

  const [status, setStatus] = createSignal<HealthStatus>('online');
  let running = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let probeToken = 0;
  let unsubOnline: (() => void) | undefined;
  let unsubOffline: (() => void) | undefined;

  function schedule(): void {
    if (timer !== undefined) { clearTimeout(timer); timer = undefined; }
    if (!running || status() === 'offline') return; // offline 只等 online 事件
    timer = setTimeout(() => { void checkNow(); }, status() === 'online' ? healthyMs : downMs);
  }

  async function checkNow(): Promise<void> {
    if (!running) return;
    const token = (probeToken += 1);
    if (!isOnline()) {
      setStatus('offline');
      schedule();
      return;
    }
    let ok = false;
    try { ok = (await probe()).ok; } catch { ok = false; }
    if (!running || token !== probeToken) return; // 已停止或被新探测取代
    const prev = status();
    if (ok) {
      setStatus('online');
      if (prev !== 'online') opts.onRecover?.(); // 翻转瞬间一次（横幅消失 + resume）
    } else {
      setStatus('backend-down');
    }
    schedule();
  }

  function start(): void {
    if (running) return;
    running = true;
    const onUp = () => { void checkNow(); };
    const onDown = () => {
      probeToken += 1; // 作废在途探测，防止断网期间的 stale 响应翻转状态
      setStatus('offline');
      schedule();
    };
    unsubOnline = (opts.subscribeOnline ?? defaultSubscribe('online'))(onUp);
    unsubOffline = (opts.subscribeOffline ?? defaultSubscribe('offline'))(onDown);
    void checkNow();
  }

  function stop(): void {
    running = false;
    probeToken += 1;
    if (timer !== undefined) { clearTimeout(timer); timer = undefined; }
    unsubOnline?.(); unsubOnline = undefined;
    unsubOffline?.(); unsubOffline = undefined;
  }

  return { status, start, stop, checkNow };
}

function defaultSubscribe(type: 'online' | 'offline') {
  return (cb: () => void): (() => void) => {
    window.addEventListener(type, cb);
    return () => window.removeEventListener(type, cb);
  };
}

// ---------- 全局单例（HealthBanner 挂载时启动） ----------
let globalMonitor: HealthMonitor | undefined;

/** 恢复钩子：衔接既有 resumeAgentTasks（任务级重连），SSE 传输层重连不重复造 */
function recoverAgentTasks(): void {
  const pid = state.projectId || '';
  if (pid) void resumeAgentTasks(pid);
}

export function startGlobalHealthMonitor(): HealthMonitor {
  if (!globalMonitor) {
    globalMonitor = createHealthMonitor({ onRecover: recoverAgentTasks });
    globalMonitor.start();
  }
  return globalMonitor;
}

export function stopGlobalHealthMonitor(): void {
  globalMonitor?.stop();
  globalMonitor = undefined;
}
