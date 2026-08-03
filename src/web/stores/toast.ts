import { createStore } from 'solid-js/store';
import { uid } from '@/lib/utils';

/** 全局 Toast 通知（替代旧 window.showToast） */
export type ToastLevel = 'success' | 'warning' | 'error' | 'info';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastItem {
  id: string;
  message: string;
  level: ToastLevel;
  action?: ToastAction;
}

const [toasts, setToasts] = createStore<ToastItem[]>([]);

export function showToast(
  message: string,
  level: ToastLevel = 'info',
  durationMs = 3000,
  action?: ToastAction,
) {
  const id = uid('toast');
  setToasts((prev) => [...prev, { id, message, level, action }]);
  if (durationMs > 0) {
    setTimeout(() => dismissToast(id), durationMs);
  }
}

export function dismissToast(id: string) {
  setToasts((prev) => prev.filter((t) => t.id !== id));
}

export { toasts };
