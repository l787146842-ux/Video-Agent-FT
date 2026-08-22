import { For, Show } from 'solid-js';
import { toasts, dismissToast } from '@/stores/toast';

/** Toast 渲染宿主，挂载于 LayoutShell（语义类见 app.css .toast-*）
 * 无障碍：容器常驻 + aria-live，toast 增删对读屏器可闻 */
export function ToastHost() {
  return (
    <div class="toast-container" aria-live="polite">
      <For each={toasts}>
        {(t) => (
          <div class={`toast ${t.level}`}>
            <button
              type="button"
              class="toast-message"
              onClick={() => dismissToast(t.id)}
            >
              {t.message}
            </button>
            <Show when={t.action}>
              <button
                type="button"
                class="toast-action"
                onClick={() => {
                  t.action?.onClick();
                  dismissToast(t.id);
                }}
              >
                {t.action?.label}
              </button>
            </Show>
          </div>
        )}
      </For>
    </div>
  );
}
