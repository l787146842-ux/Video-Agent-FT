/**
 * 纯工具函数
 */

/** 聊天历史窗口：发送给 Agent 的最近消息条数 */
export const CHAT_HISTORY_WINDOW = 11;

/** HTML 转义，防止 XSS */
export function escapeHtml(str: string): string {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  };
  return str.replace(/[&<>"']/g, (c) => map[c]);
}

/** 安全 URL 校验（仅允许 http/https/相对路径） */
export function safeUrl(url: string): string {
  if (!url) return '';
  const trimmed = url.trim();
  if (
    trimmed.startsWith('http://') ||
    trimmed.startsWith('https://') ||
    trimmed.startsWith('/') ||
    trimmed.startsWith('./')
  ) {
    return trimmed;
  }
  return '';
}

/** 生成唯一 ID */
export function uid(prefix = ''): string {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 6);
  return prefix ? `${prefix}-${ts}-${rand}` : `${ts}-${rand}`;
}

/** 防抖（带 flush/cancel）：flush 立即执行挂起的调用，供"保存"按钮等场景强制落盘 */
export interface DebouncedFn<T extends (...args: unknown[]) => void> {
  (...args: Parameters<T>): void;
  flush: () => void;
  cancel: () => void;
}

export function debounce<T extends (...args: unknown[]) => void>(
  fn: T,
  ms: number,
): DebouncedFn<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pendingArgs: Parameters<T> | undefined;
  const wrapped = (...args: Parameters<T>) => {
    pendingArgs = args;
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = undefined;
      pendingArgs = undefined;
      fn(...args);
    }, ms);
  };
  wrapped.flush = () => {
    if (timer === undefined || pendingArgs === undefined) return;
    clearTimeout(timer);
    timer = undefined;
    const args = pendingArgs;
    pendingArgs = undefined;
    fn(...args);
  };
  wrapped.cancel = () => {
    clearTimeout(timer);
    timer = undefined;
    pendingArgs = undefined;
  };
  return wrapped;
}

/** 格式化文件大小 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
