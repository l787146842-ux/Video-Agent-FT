import { createEffect } from 'solid-js';
import { useTheme } from '@/hooks/use-theme';

/**
 * API 配置（路由 /settings）
 * 按 Phase 7.4 决策：保持 iframe 嵌入旧设置页，不在本次迁移范围。
 * 主题通过 postMessage 主动推送给 iframe（theme.js 监听 studio-theme 消息）。
 */
export default function SettingsView() {
  const { theme } = useTheme();
  let iframeRef: HTMLIFrameElement | undefined;

  function sendTheme() {
    try {
      iframeRef?.contentWindow?.postMessage({ type: 'studio-theme', theme: theme() }, '*');
    } catch { /* iframe 未就绪时忽略 */ }
  }

  // 主题变更时实时推送到 iframe
  createEffect(() => {
    void theme();
    sendTheme();
  });

  return (
    <div class="settings-view">
      <iframe
        ref={iframeRef}
        src="/static/api-settings.html"
        title="API 配置"
        onLoad={sendTheme}
      />
    </div>
  );
}
