import { ErrorBoundary as SolidErrorBoundary, type ParentProps } from 'solid-js';

/**
 * 全局错误边界 — 捕获子组件树的未处理异常，防止白屏。
 * 降级 UI：显示错误摘要 + 重新加载按钮。
 */
export function AppErrorBoundary(props: ParentProps) {
  return (
    <SolidErrorBoundary
      fallback={(err: Error, reset: () => void) => (
        <div class="error-boundary">
          <div class="error-boundary-icon">⚠️</div>
          <h2 class="error-boundary-title">页面出现异常</h2>
          <p class="error-boundary-message">{err?.message || '未知错误'}</p>
          <div class="error-boundary-actions">
            <button
              type="button"
              class="btn-primary"
              onClick={reset}
            >
              重试
            </button>
            <button
              type="button"
              class="btn-secondary"
              onClick={() => window.location.reload()}
            >
              重新加载
            </button>
          </div>
        </div>
      )}
    >
      {props.children}
    </SolidErrorBoundary>
  );
}
