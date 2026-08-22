import { createSignal, Show } from 'solid-js';
import { Portal } from 'solid-js/web';
import { FiAlertTriangle } from 'solid-icons/fi';
import { useFocusTrap } from '@/lib/focus-trap';

/**
 * 全局确认对话框（替代 window.confirm，与整体视觉统一）。
 * 任意位置调用：const ok = await confirmDialog({ title: '删除草稿', message: '...' });
 */

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  /** 危险操作（确认按钮红色） */
  danger?: boolean;
}

interface ConfirmRequest extends ConfirmOptions {
  resolve: (v: boolean) => void;
}

const [request, setRequest] = createSignal<ConfirmRequest | null>(null);

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  // 已有弹窗时新请求直接覆盖（旧 Promise 按"取消"结算，避免悬挂）
  request()?.resolve(false);
  return new Promise<boolean>((resolve) => {
    setRequest({ ...options, resolve });
  });
}

function settle(value: boolean) {
  request()?.resolve(value);
  setRequest(null);
}

/** 宿主组件，挂载于 LayoutShell（Portal 渲染到 body） */
export function ConfirmDialogHost() {
  // 焦点圈闭：打开圈闭、Esc 取消、关闭还原焦点
  const [modalEl, setModalEl] = createSignal<HTMLElement>();
  useFocusTrap(() => (request() ? modalEl() : undefined), { onEscape: () => settle(false) });

  function onKeyDown(e: KeyboardEvent) {
    if (!request()) return;
    if (e.key === 'Escape') { e.preventDefault(); settle(false); }
    if (e.key === 'Enter') { e.preventDefault(); settle(true); }
  }

  return (
    <Show when={request()}>
      {(req) => (
        <Portal>
          <div
            class="confirm-overlay"
            onClick={(e) => { if (e.target === e.currentTarget) settle(false); }}
            onKeyDown={onKeyDown}
          >
            <div class="confirm-modal" ref={setModalEl} role="alertdialog" aria-modal="true" aria-label={req().title}>
              <div class="confirm-title">
                <Show when={req().danger}>
                  <FiAlertTriangle size={16} class="confirm-danger-icon" />
                </Show>
                <span>{req().title}</span>
              </div>
              <Show when={req().message}>
                <p class="confirm-message">{req().message}</p>
              </Show>
              <div class="confirm-actions">
                <button
                  type="button"
                  class="btn-secondary"
                  onClick={() => settle(false)}
                >
                  {req().cancelText || '取消'}
                </button>
                <button
                  type="button"
                  class={`btn-primary ${req().danger ? 'btn-danger' : ''}`}
                  ref={(el) => setTimeout(() => el.focus())}
                  onClick={() => settle(true)}
                >
                  {req().confirmText || '确定'}
                </button>
              </div>
            </div>
          </div>
        </Portal>
      )}
    </Show>
  );
}
