import { For, Show } from 'solid-js';
import { toasts, dismissToast } from '@/stores/toast';

/** Toast 渲染宿主，挂载于 LayoutShell（语义类见 app.css .toast-*） */
export function ToastHost() {
  return (
    <div class="toast-container">
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
