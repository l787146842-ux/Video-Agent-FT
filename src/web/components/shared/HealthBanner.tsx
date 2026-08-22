/**
 * 全局断连横幅：区别于消息流错误气泡的顶层状态提示。
 * - offline（浏览器断网）与 backend-down（后端失联）措辞分因（t() 字典）；
 * - 恢复后自动消失（响应式 status 翻转），无手动关闭（状态非用户可解除）；
 * - 挂载即启动全局健康监听（单例），恢复钩子在 lib/health 内接 resumeAgentTasks。
 */
import { Show, onCleanup } from 'solid-js';
import { t } from '@/lib/locale';
import { startGlobalHealthMonitor, stopGlobalHealthMonitor } from '@/lib/health';

export function HealthBanner() {
  const monitor = startGlobalHealthMonitor();
  onCleanup(() => stopGlobalHealthMonitor());

  return (
    <Show when={monitor.status() !== 'online'}>
      <div
        class={`health-banner ${monitor.status()}`}
        role="status"
        aria-live="polite"
        aria-label={t('health.aria')}
      >
        <span class="health-banner-dot" aria-hidden="true" />
        <span class="health-banner-text">
          {monitor.status() === 'offline' ? t('health.offline') : t('health.backendDown')}
        </span>
      </div>
    </Show>
  );
}
