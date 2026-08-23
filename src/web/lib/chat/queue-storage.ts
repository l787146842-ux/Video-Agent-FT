/**
 * 排队引导消息持久化（推理中刷新不丢排队消息）。
 *
 * 对标 harness「If it isn't in a file, it doesn't exist」：后端 worker 刷新
 * 存活（reattachRunningAgent），前端排队消息也应对称存活。键按「项目 + 对话」
 * 维度由装载方解析注册（store 间无循环依赖）；未注册时静默回落纯内存态（旧行为）。
 */
import type { QueuedMessage } from '@/stores/chat';

let queueKeyResolver: (() => string) | null = null;

/** 注册存储键解析器（LayoutShell 挂载时按当前项目+对话注册） */
export function registerQueueStorageKey(fn: () => string) {
  queueKeyResolver = fn;
}

function queueStorageKey(): string {
  try {
    return queueKeyResolver ? queueKeyResolver() : '';
  } catch {
    return '';
  }
}

/** 落盘当前队列（空队列移除键）；存储不可用时静默回落内存态 */
export function saveQueue(list: QueuedMessage[]) {
  const key = queueStorageKey();
  if (!key) return;
  try {
    if (list.length) localStorage.setItem(key, JSON.stringify(list));
    else localStorage.removeItem(key);
  } catch {
    /* 隐私模式/配额满不阻断交互 */
  }
}

/** 按当前键读取队列（损坏/缺失返回空列表，不抛异常）；
 * 旧格式条目（无 parts/displayText 键）在此结构归一化，读取处不必各自设防 */
export function loadQueue(): QueuedMessage[] {
  const key = queueStorageKey();
  if (!key) return [];
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (m) => m && typeof m.id === 'string' && typeof m.text === 'string',
      )
      .map((m) => ({
        ...m,
        displayText: typeof m.displayText === 'string' ? m.displayText : m.text,
        parts: Array.isArray(m.parts) ? m.parts : [],
      }));
  } catch {
    return [];
  }
}
