/**
 * 纯工具函数
 */

/** 聊天历史窗口：发送给 Agent 的最近消息条数（与后端 messages[-10:] 对齐） */
export const CHAT_HISTORY_WINDOW = 10;

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

/** 防抖（带 flush/cancel）：flush 立即执行挂起的调用，并等待"仍在飞行中"的上一次调用完成，
 * 供"保存"按钮/项目切换前强制落盘（否则已发出未返回的请求会带着旧数据落到新项目上） */
export interface DebouncedFn<T extends (...args: unknown[]) => void> {
  (...args: Parameters<T>): void;
  flush: () => Promise<void>;
  cancel: () => void;
}

export function debounce<T extends (...args: unknown[]) => void>(
  fn: T,
  ms: number,
): DebouncedFn<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pendingArgs: Parameters<T> | undefined;
  /** 已发出、尚未完成的调用（异步 fn 的 Promise 链） */
  let inflight: Promise<void> | undefined;
  const invoke = (args: Parameters<T>) => {
    const p = Promise.resolve(fn(...args) as unknown).then(
      () => { if (inflight === p) inflight = undefined; },
      () => { if (inflight === p) inflight = undefined; },
    );
    inflight = p;
  };
  const wrapped = (...args: Parameters<T>) => {
    pendingArgs = args;
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = undefined;
      pendingArgs = undefined;
      invoke(args);
    }, ms);
  };
  wrapped.flush = async (): Promise<void> => {
    if (timer !== undefined && pendingArgs !== undefined) {
      clearTimeout(timer);
      timer = undefined;
      const args = pendingArgs;
      pendingArgs = undefined;
      invoke(args);
    }
    await inflight;
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

/** 格式化 token 数为业界 K/M 记法：<1000 原数；<1M 显示 K；≥1M 显示 M。
 * 一位小数，整数去掉多余的 .0（如 128000 → 128K、1500000 → 1.5M） */
export function formatTokens(n: number): string {
  const v = Math.max(0, Math.round(n));
  if (v < 1000) return String(v);
  const [div, unit] = v < 1_000_000
    ? ([1000, 'K'] as const)
    : ([1_000_000, 'M'] as const);
  const s = (v / div).toFixed(1);
  return `${s.endsWith('.0') ? s.slice(0, -2) : s}${unit}`;
}
